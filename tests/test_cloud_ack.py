from pathlib import Path
import sys
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from mobilefrost.cloud_ack import handle_ack


class CloudAckTests(unittest.TestCase):
    def test_valid_acknowledgement_updates_matching_command(self):
        updates = []
        event = ack_event()

        response = handle_ack(
            event,
            {"device_id": "mobilefrost", "update_command": lambda command: updates.append(command) or True},
        )

        self.assertEqual(response["statusCode"], 200)
        self.assertEqual(updates, [event])

    def test_acknowledgement_rejects_invalid_identity_and_value(self):
        invalid_events = (
            {**ack_event(), "request_id": ""},
            {**ack_event(), "device_id": "another-device"},
            {**ack_event(), "kind": "motor"},
            {**ack_event(), "value": 256},
            {**ack_event(), "value": True},
            {**ack_event(), "timestamp": "not-a-timestamp"},
        )

        for event in invalid_events:
            updates = []
            response = handle_ack(
                event,
                {"device_id": "mobilefrost", "update_command": lambda command: updates.append(command) or True},
            )
            self.assertEqual(response["statusCode"], 400)
            self.assertEqual(updates, [])

    def test_unknown_or_duplicate_command_ack_is_ignored(self):
        response = handle_ack(
            ack_event(),
            {"device_id": "mobilefrost", "update_command": lambda _command: False},
        )

        self.assertEqual(response["statusCode"], 200)
        self.assertEqual(response["body"], '{"status":"ignored"}')

    def test_acknowledgement_storage_error_is_masked(self):
        def unavailable(_command):
            raise RuntimeError("private database detail")

        response = handle_ack(
            ack_event(),
            {"device_id": "mobilefrost", "update_command": unavailable},
        )

        self.assertEqual(response["statusCode"], 503)
        self.assertNotIn("private database detail", response["body"])


def ack_event():
    return {
        "request_id": "request-123",
        "device_id": "mobilefrost",
        "kind": "fan",
        "value": 128,
        "timestamp": "2026-10-01T09:01:00+00:00",
    }


if __name__ == "__main__":
    unittest.main()