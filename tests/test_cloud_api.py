from datetime import datetime, timezone
from decimal import Decimal
import json
from pathlib import Path
import sys
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from mobilefrost.cloud_api import handle_request


class CloudApiTests(unittest.TestCase):
    def test_temperature_route_accepts_supported_ranges(self):
        requested_hours = []

        for hours in (1, 24, 168):
            response = handle_request(
                api_event(hours=hours),
                {"query_temperatures": lambda value: requested_hours.append(value) or empty_data(value)},
            )
            self.assertEqual(response["statusCode"], 200)

        self.assertEqual(requested_hours, [1, 24, 168])

    def test_temperature_route_rejects_unsupported_and_malformed_ranges(self):
        for hours in ("12", "abc", ""):
            response = handle_request(
                api_event(hours=hours),
                {"query_temperatures": lambda _value: empty_data(24)},
            )
            self.assertEqual(response["statusCode"], 400)
            self.assertEqual(json.loads(response["body"])["error"], "Ungültiger Zeitraum")

    def test_temperature_route_requires_authenticated_claims(self):
        event = api_event()
        event["requestContext"]["authorizer"]["jwt"]["claims"] = {}

        response = handle_request(
            event,
            {"query_temperatures": lambda _hours: empty_data(24)},
        )

        self.assertEqual(response["statusCode"], 401)
        self.assertEqual(json.loads(response["body"])["error"], "Nicht angemeldet")

    def test_temperature_route_serializes_latest_and_history(self):
        timestamp = datetime(2026, 10, 1, 9, 30, tzinfo=timezone.utc)

        response = handle_request(
            api_event(hours=1),
            {
                "query_temperatures": lambda _hours: {
                    "series": {
                        "arduino_sensor_marten": [(timestamp, 22.5)],
                    },
                    "latest": {
                        "arduino_sensor_marten": (timestamp, 22.5),
                    },
                }
            },
        )

        payload = json.loads(response["body"])
        self.assertEqual(response["statusCode"], 200)
        self.assertEqual(payload["hours"], 1)
        self.assertEqual(
            payload["series"]["arduino_sensor_marten"],
            [{"timestamp": "2026-10-01T09:30:00+00:00", "value": 22.5}],
        )
        self.assertEqual(payload["latest"]["arduino_sensor_marten"]["value"], 22.5)

    def test_temperature_route_masks_cloud_dependency_errors(self):
        def unavailable(_hours):
            raise RuntimeError("private AWS failure details")

        response = handle_request(
            api_event(),
            {"query_temperatures": unavailable},
        )

        self.assertEqual(response["statusCode"], 503)
        self.assertEqual(json.loads(response["body"])["error"], "Cloud-Daten nicht erreichbar")
        self.assertNotIn("private AWS failure details", response["body"])

    def test_drive_start_is_idempotent_while_a_session_is_active(self):
        store = FakeDriveStore()
        dependencies = drive_dependencies(store)

        first = handle_request(api_event(route="POST /api/drive/start"), dependencies)
        second = handle_request(api_event(route="POST /api/drive/start"), dependencies)

        first_body = json.loads(first["body"])
        second_body = json.loads(second["body"])
        self.assertEqual(first["statusCode"], 200)
        self.assertEqual(first_body["status"], "started")
        self.assertEqual(second_body["session"], first_body["session"])
        self.assertEqual(store.create_count, 1)

    def test_drive_stop_records_end_and_repeated_stop_is_idempotent(self):
        store = FakeDriveStore()
        dependencies = drive_dependencies(store)
        started = handle_request(api_event(route="POST /api/drive/start"), dependencies)
        session = json.loads(started["body"])["session"]

        stopped = handle_request(api_event(route="POST /api/drive/stop"), dependencies)
        repeated = handle_request(api_event(route="POST /api/drive/stop"), dependencies)

        stopped_body = json.loads(stopped["body"])
        self.assertEqual(stopped["statusCode"], 200)
        self.assertEqual(stopped_body["status"], "stopped")
        self.assertEqual(stopped_body["session"]["session_id"], session["session_id"])
        self.assertEqual(stopped_body["session"]["status"], "stopped")
        self.assertIsNotNone(stopped_body["session"]["ended_at"])
        self.assertEqual(json.loads(repeated["body"]), {"status": "stopped", "active": None})

    def test_drive_start_recovers_from_concurrent_active_session(self):
        existing = drive_session("existing-session")
        store = FakeDriveStore(active_after_conflict=existing)

        response = handle_request(
            api_event(route="POST /api/drive/start"),
            drive_dependencies(store, conflict_on_create=True),
        )

        self.assertEqual(response["statusCode"], 200)
        self.assertEqual(json.loads(response["body"])["session"], existing)

    def test_actuator_routes_accept_bounds_and_persist_before_publish(self):
        for kind, values in (("fan", (0, 255)), ("flap", (0, 90))):
            for value in values:
                store = FakeCommandStore()
                dependencies = command_dependencies(store)
                response = handle_request(
                    api_event(
                        route=f"POST /api/actuators/{kind}",
                        body={"value": value},
                    ),
                    dependencies,
                )

                self.assertEqual(response["statusCode"], 202)
                body = json.loads(response["body"])
                self.assertEqual(body, {"request_id": "request-123", "status": "pending"})
                self.assertEqual(store.commands["request-123"]["value"], value)
                self.assertEqual(store.published[0]["kind"], kind)
                self.assertEqual(store.published[0]["value"], value)

    def test_actuator_routes_reject_invalid_values(self):
        invalid_values = (-1, 256, 1.5, True, "10", None)
        for value in invalid_values:
            store = FakeCommandStore()
            response = handle_request(
                api_event(route="POST /api/actuators/fan", body={"value": value}),
                command_dependencies(store),
            )
            self.assertEqual(response["statusCode"], 400)
            self.assertEqual(store.commands, {})
            self.assertEqual(store.published, [])

    def test_actuator_publish_failure_marks_command_failed(self):
        store = FakeCommandStore(fail_publish=True)

        response = handle_request(
            api_event(route="POST /api/actuators/fan", body={"value": 128}),
            command_dependencies(store),
        )

        self.assertEqual(response["statusCode"], 502)
        self.assertEqual(store.commands["request-123"]["status"], "failed")

    def test_command_status_reports_pending_acknowledged_and_unknown(self):
        store = FakeCommandStore()
        dependencies = command_dependencies(store)
        handle_request(
            api_event(route="POST /api/actuators/fan", body={"value": 128}),
            dependencies,
        )

        pending = handle_request(
            api_event(
                route="GET /api/commands/{request_id}",
                path_parameters={"request_id": "request-123"},
            ),
            dependencies,
        )
        store.commands["request-123"].update(
            status="acknowledged",
            reported_value=128,
            acknowledged_at="2026-10-01T09:01:00+00:00",
        )
        acknowledged = handle_request(
            api_event(
                route="GET /api/commands/{request_id}",
                path_parameters={"request_id": "request-123"},
            ),
            dependencies,
        )
        unknown = handle_request(
            api_event(
                route="GET /api/commands/{request_id}",
                path_parameters={"request_id": "missing"},
            ),
            dependencies,
        )

        self.assertEqual(json.loads(pending["body"])["status"], "pending")
        self.assertEqual(json.loads(acknowledged["body"])["reported_value"], 128)
        self.assertEqual(unknown["statusCode"], 404)

    def test_pending_command_status_times_out(self):
        store = FakeCommandStore()
        store.commands["request-123"] = {
            "request_id": "request-123",
            "status": "pending",
            "created_at": "2026-10-01T09:00:00+00:00",
        }
        dependencies = command_dependencies(store)
        dependencies["now"] = lambda: datetime(2026, 10, 1, 9, 1, tzinfo=timezone.utc)

        response = handle_request(
            api_event(
                route="GET /api/commands/{request_id}",
                path_parameters={"request_id": "request-123"},
            ),
            dependencies,
        )

        self.assertEqual(json.loads(response["body"])["status"], "timed_out")

    def test_command_status_serializes_dynamodb_decimal_values(self):
        response = handle_request(
            api_event(
                route="GET /api/commands/{request_id}",
                path_parameters={"request_id": "request-123"},
            ),
            {
                "get_command": lambda _request_id: {
                    "request_id": "request-123",
                    "kind": "fan",
                    "value": Decimal("128"),
                    "status": "acknowledged",
                    "reported_value": Decimal("128"),
                }
            },
        )

        self.assertEqual(response["statusCode"], 200)
        self.assertEqual(json.loads(response["body"])["reported_value"], 128)


class FakeDriveStore:
    def __init__(self, active_after_conflict=None):
        self.active = None
        self.active_after_conflict = active_after_conflict
        self.create_count = 0
        self.conflict_on_create = False

    def get_active(self):
        return self.active

    def create(self):
        self.create_count += 1
        if self.conflict_on_create:
            self.active = self.active_after_conflict
            raise RuntimeError("ConditionalCheckFailedException")
        self.active = drive_session("new-session")
        return self.active

    def stop(self, session):
        self.active = None
        return {
            **session,
            "status": "stopped",
            "ended_at": "2026-10-01T09:45:00+00:00",
        }


def drive_dependencies(store, conflict_on_create=False):
    store.conflict_on_create = conflict_on_create
    return {
        "query_temperatures": lambda hours: empty_data(hours),
        "get_active_drive": store.get_active,
        "create_drive_session": store.create,
        "stop_drive_session": store.stop,
    }


class FakeCommandStore:
    def __init__(self, fail_publish=False):
        self.commands = {}
        self.published = []
        self.fail_publish = fail_publish

    def store(self, command):
        self.commands[command["request_id"]] = {**command, "status": "pending"}

    def publish(self, command):
        if command["request_id"] not in self.commands:
            raise AssertionError("command must be stored before publishing")
        if self.fail_publish:
            raise RuntimeError("private IoT failure details")
        self.published.append(command)

    def get(self, request_id):
        return self.commands.get(request_id)

    def fail(self, request_id):
        self.commands[request_id]["status"] = "failed"


def command_dependencies(store):
    return {
        "query_temperatures": lambda hours: empty_data(hours),
        "get_active_drive": lambda: None,
        "store_command": store.store,
        "publish_command": store.publish,
        "get_command": store.get,
        "mark_command_failed": store.fail,
        "new_request_id": lambda: "request-123",
        "device_id": "mobilefrost",
        "now": lambda: datetime(2026, 10, 1, 9, 0, tzinfo=timezone.utc),
    }


def drive_session(session_id):
    return {
        "session_id": session_id,
        "device_id": "mobilefrost",
        "started_at": "2026-10-01T09:00:00+00:00",
        "ended_at": None,
        "status": "active",
    }


def api_event(hours=24, route="GET /api/temperatures", body=None, path_parameters=None):
    method, path = route.split(" ", 1)
    return {
        "version": "2.0",
        "routeKey": route,
        "rawPath": path,
        "requestContext": {
            "http": {"method": method},
            "authorizer": {
                "jwt": {
                    "claims": {"sub": "cognito-user-123"},
                }
            },
        },
        "queryStringParameters": {"hours": str(hours)},
        "pathParameters": path_parameters or {},
        "body": json.dumps(body) if body is not None else None,
    }


def empty_data(hours):
    return {"hours": hours, "series": {}, "latest": {}}


if __name__ == "__main__":
    unittest.main()