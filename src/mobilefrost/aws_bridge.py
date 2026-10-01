from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
import ssl
import threading

from .mqtt_io import FAN_SET_TOPIC, FLAP_SET_TOPIC


COMMAND_TOPIC_PREFIX = "mobilefrost/commands"
ACK_TOPIC_PREFIX = "mobilefrost/device/status"
LOCAL_PUBLISH_TIMEOUT = 10


@dataclass(frozen=True)
class BridgeConfig:
    endpoint: str
    device_id: str
    certificate_path: str
    private_key_path: str
    root_ca_path: str
    local_mqtt_host: str
    local_mqtt_port: int

    @property
    def aws_client_id(self):
        return f"{self.device_id}-bridge"

    @property
    def command_topic(self):
        return f"{COMMAND_TOPIC_PREFIX}/{self.device_id}/actuators/+"

    @property
    def acknowledgement_topic(self):
        return f"{ACK_TOPIC_PREFIX}/{self.device_id}/commands"

    @classmethod
    def from_env(cls, environment=None):
        environment = os.environ if environment is None else environment
        required = {
            "endpoint": "AWS_IOT_ENDPOINT",
            "device_id": "AWS_IOT_THING_NAME",
            "certificate_path": "AWS_IOT_CERTIFICATE_PATH",
            "private_key_path": "AWS_IOT_PRIVATE_KEY_PATH",
            "root_ca_path": "AWS_IOT_ROOT_CA_PATH",
            "local_mqtt_host": "MQTT_HOST",
        }
        values = {
            key: environment.get(variable)
            for key, variable in required.items()
        }
        if any(not value for value in values.values()):
            raise ValueError("AWS IoT bridge configuration is incomplete")

        try:
            port = int(environment.get("MQTT_PORT", "1883"))
        except (TypeError, ValueError) as error:
            raise ValueError("MQTT_PORT must be a valid TCP port") from error
        if not 1 <= port <= 65535:
            raise ValueError("MQTT_PORT must be a valid TCP port")

        return cls(**values, local_mqtt_port=port)


class AwsCommandBridge:
    def __init__(self, configuration, cloud_client, local_client, clock=None):
        self.configuration = configuration
        self.cloud_client = cloud_client
        self.local_client = local_client
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def configure_aws_connection(self):
        tls_context = ssl.create_default_context(
            cafile=self.configuration.root_ca_path
        )
        tls_context.load_cert_chain(
            certfile=self.configuration.certificate_path,
            keyfile=self.configuration.private_key_path,
        )
        tls_context.set_alpn_protocols(["x-amzn-mqtt-ca"])
        self.cloud_client.tls_set_context(tls_context)

    def start(self):
        self.configure_aws_connection()
        self.cloud_client.on_connect = self.on_cloud_connect
        self.cloud_client.on_message = self.on_cloud_message
        self.local_client.connect_async(
            self.configuration.local_mqtt_host,
            self.configuration.local_mqtt_port,
        )
        self.local_client.loop_start()
        self.cloud_client.connect_async(
            self.configuration.endpoint,
            443,
            keepalive=60,
        )
        self.cloud_client.loop_start()

    def on_cloud_connect(self, client, _userdata, _flags, reason_code, _properties):
        if getattr(reason_code, "is_failure", False) or reason_code != 0:
            print("AWS IoT Bridge: Verbindung fehlgeschlagen")
            return
        client.subscribe(self.configuration.command_topic, qos=1)

    def on_cloud_message(self, _client, _userdata, message):
        command = self._parse_command(message.topic, message.payload)
        if command is None:
            print("AWS IoT Bridge: Ungültigen Aktorbefehl verworfen")
            return

        local_topic = FAN_SET_TOPIC if command["kind"] == "fan" else FLAP_SET_TOPIC
        try:
            result = self.local_client.publish(
                local_topic,
                str(command["value"]),
                qos=1,
                retain=False,
            )
            if not _publish_confirmed(result, LOCAL_PUBLISH_TIMEOUT):
                print("AWS IoT Bridge: Lokaler MQTT-Befehl nicht bestätigt")
                return
            self._publish_acknowledgement(command)
        except Exception as error:
            print(f"AWS IoT Bridge: Lokale Weiterleitung fehlgeschlagen: {error}")

    def _parse_command(self, topic, payload):
        topic_parts = topic.split("/")
        if (
            len(topic_parts) != 5
            or topic_parts[:2] != COMMAND_TOPIC_PREFIX.split("/")
            or topic_parts[2] != self.configuration.device_id
            or topic_parts[3] != "actuators"
        ):
            return None

        topic_kind = topic_parts[4]
        if topic_kind not in {"fan", "flap"}:
            return None
        try:
            command = json.loads(payload.decode("utf-8") if isinstance(payload, bytes) else payload)
        except (UnicodeDecodeError, json.JSONDecodeError, TypeError):
            return None

        if not isinstance(command, dict):
            return None
        request_id = command.get("request_id")
        kind = command.get("kind")
        value = command.get("value")
        if (
            not isinstance(request_id, str)
            or not request_id
            or len(request_id) > 128
            or command.get("device_id") != self.configuration.device_id
            or kind != topic_kind
            or type(value) is not int
        ):
            return None

        maximum = 255 if kind == "fan" else 90
        if value < 0 or value > maximum:
            return None
        return {"request_id": request_id, "device_id": self.configuration.device_id, "kind": kind, "value": value}

    def _publish_acknowledgement(self, command):
        timestamp = self.clock()
        if isinstance(timestamp, datetime):
            timestamp = timestamp.astimezone(timezone.utc).isoformat()
        payload = json.dumps(
            {
                **command,
                "timestamp": timestamp,
            },
            separators=(",", ":"),
        ).encode("utf-8")
        result = self.cloud_client.publish(
            self.configuration.acknowledgement_topic,
            payload,
            qos=1,
            retain=False,
        )
        if result is None or getattr(result, "rc", 1) != 0:
            print("AWS IoT Bridge: Bestätigung wurde nicht angenommen")


def _publish_confirmed(result, timeout):
    if result is None or getattr(result, "rc", 1) != 0:
        return False
    result.wait_for_publish(timeout=timeout)
    return result.is_published()


def _build_clients(configuration):
    import paho.mqtt.client as mqtt

    cloud_client = mqtt.Client(
        mqtt.CallbackAPIVersion.VERSION2,
        client_id=configuration.aws_client_id,
        protocol=mqtt.MQTTv311,
    )
    local_client = mqtt.Client(
        mqtt.CallbackAPIVersion.VERSION2,
        client_id=f"{configuration.device_id}-local-bridge",
        protocol=mqtt.MQTTv311,
    )
    return cloud_client, local_client


def main():
    configuration = BridgeConfig.from_env()
    cloud_client, local_client = _build_clients(configuration)
    bridge = AwsCommandBridge(configuration, cloud_client, local_client)
    bridge.start()
    threading.Event().wait()


if __name__ == "__main__":
    main()