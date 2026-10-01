import os
from datetime import timezone

from flask import Flask, jsonify, render_template, request

from .database import connect_db_once, fetch_dashboard_data


ALLOWED_HOURS = {1, 24, 168}
FAN_RANGE = range(0, 256)
FLAP_RANGE = range(0, 91)


class MqttCommandHandler:
    def __init__(self, client=None, host=None, port=None):
        self.client = client
        self.host = host or os.environ.get("MQTT_HOST", "mosquitto")
        self.port = int(os.environ.get("MQTT_PORT", "1883")) if port is None else port

    def send(self, kind, value):
        if self.client is None:
            try:
                import paho.mqtt.client as mqtt
            except Exception:
                return False
            self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)

        try:
            self.client.connect(self.host, self.port, keepalive=30)
            self.client.loop_start()
        except Exception:
            pass

        mapping = {
            ("drive", "start"): ("mobilefrost/drive/start", "1"),
            ("drive", "stop"): ("mobilefrost/drive/stop", "0"),
            ("fan", None): ("mobilefrost/actuators/fan/set", str(value)),
            ("flap", None): ("mobilefrost/actuators/flap/set", str(value)),
        }
        topic, payload = mapping[(kind, value)] if (kind, value) in mapping else mapping[(kind, None)]
        try:
            self.client.publish(topic, payload, retain=False)
            return True
        except Exception:
            return False


def load_dashboard_data(hours):
    connection = connect_db_once()
    try:
        return fetch_dashboard_data(connection, hours)
    finally:
        connection.close()


def create_app(data_loader=load_dashboard_data, command_handler=None):
    application = Flask(__name__)
    drive_state = {"running": False}
    if command_handler is None:
        command_handler = MqttCommandHandler().send

    def require_value(kind, payload, minimum, maximum):
        if not isinstance(payload, dict):
            return None
        try:
            value = int(payload.get("value"))
        except (TypeError, ValueError):
            return None
        if value < minimum or value > maximum:
            return None
        return value

    @application.get("/")
    def dashboard_page():
        return render_template("dashboard.html")

    @application.get("/api/temperatures")
    def temperature_data():
        try:
            hours = int(request.args.get("hours", "24"))
        except ValueError:
            return jsonify(error="Ungültiger Zeitraum"), 400

        if hours not in ALLOWED_HOURS:
            return jsonify(error="Ungültiger Zeitraum"), 400

        try:
            data = data_loader(hours)
        except Exception as error:
            application.logger.error("Dashboard database error: %s", error)
            return jsonify(error="Datenbank nicht erreichbar"), 503

        return jsonify(_serialize_data(data, hours))

    @application.get("/api/drive/status")
    def drive_status():
        return jsonify({"running": drive_state["running"]})

    @application.post("/api/drive/start")
    def drive_start():
        drive_state["running"] = True
        command_handler("drive", "start")
        return jsonify({"status": "started", "running": True})

    @application.post("/api/drive/stop")
    def drive_stop():
        drive_state["running"] = False
        command_handler("drive", "stop")
        return jsonify({"status": "stopped", "running": False})

    @application.post("/api/actuators/fan")
    def set_fan():
        value = require_value("fan", request.get_json(silent=True), 0, 255)
        if value is None:
            return jsonify(error="Ungültiger Wert"), 400
        command_handler("fan", value)
        return jsonify({"kind": "fan", "value": value})

    @application.post("/api/actuators/flap")
    def set_flap():
        value = require_value("flap", request.get_json(silent=True), 0, 90)
        if value is None:
            return jsonify(error="Ungültiger Wert"), 400
        command_handler("flap", value)
        return jsonify({"kind": "flap", "value": value})

    return application


def _serialize_data(data, hours):
    series = {
        sensor_id: [
            {"timestamp": _serialize_timestamp(timestamp), "value": float(value)}
            for timestamp, value in points
        ]
        for sensor_id, points in data["series"].items()
    }
    latest = {
        sensor_id: {
            "timestamp": _serialize_timestamp(timestamp),
            "value": float(value),
        }
        for sensor_id, (timestamp, value) in data["latest"].items()
    }
    return {"hours": hours, "series": series, "latest": latest}


def _serialize_timestamp(timestamp):
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    return timestamp.isoformat()


def main():
    create_app().run(host="0.0.0.0", port=8080)


if __name__ == "__main__":
    main()