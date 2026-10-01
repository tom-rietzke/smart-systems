from datetime import datetime, timezone
from pathlib import Path
import sys
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from mobilefrost.dashboard import create_app


class DashboardTests(unittest.TestCase):
    def test_serves_dashboard_page(self):
        client = self.create_client(lambda _hours: empty_data())

        response = client.get("/")

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Temperaturverlauf", response.data)
        self.assertIn(b'data-hours="24"', response.data)
        self.assertIn(b"temperature-chart", response.data)

    def test_dashboard_chart_uses_numeric_time_axis(self):
        script = (
            PROJECT_ROOT / "src" / "mobilefrost" / "static" / "dashboard.js"
        ).read_text(encoding="utf-8")

        self.assertIn("x: Date.parse(point.timestamp)", script)
        self.assertIn('type: "linear"', script)
        self.assertNotIn("x: formatTime(point.timestamp)", script)

    def test_api_uses_default_24_hour_range(self):
        requested_hours = []
        client = self.create_client(
            lambda hours: requested_hours.append(hours) or empty_data()
        )

        response = client.get("/api/temperatures")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(requested_hours, [24])
        self.assertEqual(response.get_json()["hours"], 24)

    def test_api_accepts_supported_ranges(self):
        requested_hours = []
        client = self.create_client(
            lambda hours: requested_hours.append(hours) or empty_data()
        )

        for hours in (1, 24, 168):
            self.assertEqual(
                client.get(f"/api/temperatures?hours={hours}").status_code,
                200,
            )

        self.assertEqual(requested_hours, [1, 24, 168])

    def test_api_rejects_unsupported_range(self):
        client = self.create_client(lambda _hours: empty_data())

        response = client.get("/api/temperatures?hours=12")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()["error"], "Ungültiger Zeitraum")

    def test_api_serializes_temperature_data(self):
        timestamp = datetime(2026, 9, 18, 10, 30, tzinfo=timezone.utc)
        client = self.create_client(
            lambda _hours: {
                "series": {
                    "arduino_sensor_luis": [(timestamp, 22.5)],
                },
                "latest": {
                    "arduino_sensor_luis": (timestamp, 22.5),
                },
            }
        )

        payload = client.get("/api/temperatures?hours=1").get_json()

        self.assertEqual(
            payload["series"]["arduino_sensor_luis"],
            [{"timestamp": "2026-09-18T10:30:00+00:00", "value": 22.5}],
        )
        self.assertEqual(payload["latest"]["arduino_sensor_luis"]["value"], 22.5)

    def test_api_marks_naive_database_timestamps_as_utc(self):
        timestamp = datetime(2026, 9, 21, 8, 56)
        client = self.create_client(
            lambda _hours: {
                "series": {
                    "arduino_sensor_marten": [(timestamp, 24.6)],
                },
                "latest": {
                    "arduino_sensor_marten": (timestamp, 24.6),
                },
            }
        )

        payload = client.get("/api/temperatures?hours=1").get_json()

        self.assertEqual(
            payload["series"]["arduino_sensor_marten"][0]["timestamp"],
            "2026-09-21T08:56:00+00:00",
        )
        self.assertEqual(
            payload["latest"]["arduino_sensor_marten"]["timestamp"],
            "2026-09-21T08:56:00+00:00",
        )

    def test_api_returns_503_when_database_is_unavailable(self):
        def unavailable(_hours):
            raise RuntimeError("secret database details")

        client = self.create_client(unavailable)

        response = client.get("/api/temperatures")

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.get_json()["error"], "Datenbank nicht erreichbar")
        self.assertNotIn(b"secret database details", response.data)

    def test_api_allows_drive_control_commands(self):
        commands = []
        client = self.create_client(
            lambda _hours: empty_data(),
            command_handler=lambda kind, value: commands.append((kind, value)),
        )

        start = client.post("/api/drive/start")
        stop = client.post("/api/drive/stop")

        self.assertEqual(start.status_code, 200)
        self.assertEqual(stop.status_code, 200)
        self.assertEqual(commands, [("drive", "start"), ("drive", "stop")])

    def test_api_rejects_invalid_actuator_values(self):
        commands = []
        client = self.create_client(
            lambda _hours: empty_data(),
            command_handler=lambda kind, value: commands.append((kind, value)),
        )

        response = client.post(
            "/api/actuators/fan",
            json={"value": 999},
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()["error"], "Ungültiger Wert")
        self.assertEqual(commands, [])

    @staticmethod
    def create_client(data_loader, command_handler=None):
        application = create_app(
            data_loader=data_loader,
            command_handler=command_handler,
        )
        application.config.update(TESTING=True)
        return application.test_client()


def empty_data():
    return {"series": {}, "latest": {}}


if __name__ == "__main__":
    unittest.main()