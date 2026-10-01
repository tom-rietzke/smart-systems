import os
import json

from .config import MQTT_HOST, MQTT_PORT


TEMPERATURE_TOPIC_PREFIX = "mobilefrost/temperatures"
COOLING_STATUS_TOPIC = "mobilefrost/status/cooling"
FAN_SET_TOPIC = "mobilefrost/actuators/fan/set"
FLAP_SET_TOPIC = "mobilefrost/actuators/flap/set"


def format_temperature_payload(sensor_id, value, timestamp):
    return json.dumps(
        {
            "sensor_id": sensor_id,
            "value": float(value),
            "timestamp": timestamp.isoformat(),
        },
        separators=(",", ":"),
    )


def format_cooling_payload(enabled, source="automatic"):
    return json.dumps(
        {"enabled": bool(enabled), "source": source},
        separators=(",", ":"),
    )


def parse_actuator_command(topic, payload):
    if isinstance(payload, bytes):
        payload = payload.decode("utf-8", errors="replace")

    payload = str(payload).strip()
    try:
        value = int(payload)
    except ValueError:
        try:
            decoded_payload = json.loads(payload)
            value = int(decoded_payload)
        except (TypeError, ValueError, json.JSONDecodeError):
            return None

    if topic == FAN_SET_TOPIC and 0 <= value <= 255:
        return ("fan", value)
    if topic == FLAP_SET_TOPIC and 0 <= value <= 90:
        return ("flap", value)
    return None

class MqttAdapter:
    def __init__(self, client=None, host=None, port=None):
        self.client = client
        self.host = host
        self.port = port

    def _publish(self, topic, payload, retain=False):
        if self.client is None:
            return

        try:
            self.client.publish(topic, payload, retain=retain)
        except Exception as error:
            print(f"MQTT Publish fehlgeschlagen: {error}")

    def start(self, on_command):
        if self.client is None or self.host is None or self.port is None:
            return

        def handle_message(_client, _userdata, message):
            command = parse_actuator_command(message.topic, message.payload)
            if command is None:
                print(f"Ungültiges MQTT-Kommando: {message.topic} {message.payload!r}")
                return
            on_command(*command)

        def handle_connect(client, _userdata, _flags, _reason_code, _properties):
            client.subscribe(FAN_SET_TOPIC)
            client.subscribe(FLAP_SET_TOPIC)

        self.client.on_connect = handle_connect
        self.client.on_message = handle_message
        try:
            self.client.connect_async(self.host, self.port)
            self.client.loop_start()
        except Exception as error:
            print(f"MQTT nicht erreichbar: {error}")

    def publish_temperature(self, sensor_id, value, timestamp):
        topic = f"{TEMPERATURE_TOPIC_PREFIX}/{sensor_id}"
        self._publish(
            topic,
            format_temperature_payload(sensor_id, value, timestamp),
            retain=True,
        )

    def publish_cooling_state(self, enabled, source="automatic"):
        self._publish(
            COOLING_STATUS_TOPIC,
            format_cooling_payload(enabled, source),
            retain=True,
        )


def build_mqtt_adapter():
    host = os.environ.get("MQTT_HOST", MQTT_HOST)
    port = int(os.environ.get("MQTT_PORT", str(MQTT_PORT)))
    username = os.environ.get("MQTT_USERNAME")
    password = os.environ.get("MQTT_PASSWORD")

    try:
        import paho.mqtt.client as mqtt
    except Exception as error:
        print(f"MQTT deaktiviert: {error}")
        return None

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    if username:
        client.username_pw_set(username, password)

    return MqttAdapter(client=client, host=host, port=port)