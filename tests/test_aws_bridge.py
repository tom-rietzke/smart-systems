from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase, main
from unittest.mock import patch
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from mobilefrost.aws_bridge import (
    ACK_TOPIC_PREFIX,
    COMMAND_TOPIC_PREFIX,
    AwsCommandBridge,
    BridgeConfig,
)


class BridgeConfigTests(TestCase):
    def test_loads_required_configuration(self):
        configuration = BridgeConfig.from_env(bridge_environment())

        self.assertEqual(configuration.device_id, "mobilefrost")
        self.assertEqual(configuration.local_mqtt_port, 1883)
        self.assertEqual(configuration.aws_client_id, "mobilefrost-bridge")

    def test_rejects_missing_endpoint_and_invalid_port(self):
        environment = bridge_environment()
        environment.pop("AWS_IOT_ENDPOINT")
        with self.assertRaises(ValueError):
            BridgeConfig.from_env(environment)

        environment = bridge_environment()
        environment["MQTT_PORT"] = "not-a-port"
        with self.assertRaises(ValueError):
            BridgeConfig.from_env(environment)


class ManualSetupGuideTests(TestCase):
    def test_guide_documents_scoped_topics_used_by_bridge(self):
        guide = (PROJECT_ROOT / "docs" / "amplify-dashboard-setup.md").read_text(
            encoding="utf-8"
        )

        self.assertIn(
            "topic/mobilefrost/commands/mobilefrost/actuators/*",
            guide,
        )
        self.assertIn(
            "topicfilter/mobilefrost/commands/mobilefrost/actuators/*",
            guide,
        )
        self.assertIn(
            "topic/mobilefrost/device/status/mobilefrost/commands",
            guide,
        )
        policy_rows = [line for line in guide.splitlines() if line.startswith("| `iot:")]
        self.assertTrue(policy_rows)
        self.assertFalse(any(":topic/*`" in line for line in policy_rows))


class AwsCommandBridgeTests(TestCase):
    def setUp(self):
        self.cloud_client = FakeMqttClient()
        self.local_client = FakeMqttClient()
        self.bridge = AwsCommandBridge(
            BridgeConfig.from_env(bridge_environment()),
            self.cloud_client,
            self.local_client,
            clock=lambda: "2026-10-01T09:01:00+00:00",
        )

    def test_subscribes_to_only_its_device_command_topic(self):
        self.bridge.on_cloud_connect(self.cloud_client, None, None, 0, None)

        self.assertEqual(
            self.cloud_client.subscriptions,
            [(f"{COMMAND_TOPIC_PREFIX}/mobilefrost/actuators/+", 1)],
        )

    def test_forwards_valid_fan_and_flap_commands_and_acknowledges(self):
        for kind, value, topic in (
            ("fan", 200, "mobilefrost/actuators/fan/set"),
            ("flap", 45, "mobilefrost/actuators/flap/set"),
        ):
            self.bridge.on_cloud_message(
                self.cloud_client,
                None,
                command_message(kind, value),
            )

        self.assertEqual(
            [(topic, payload, qos, retain) for topic, payload, qos, retain in self.local_client.published],
            [
                ("mobilefrost/actuators/fan/set", "200", 1, False),
                ("mobilefrost/actuators/flap/set", "45", 1, False),
            ],
        )
        self.assertEqual(
            [item[0] for item in self.cloud_client.published],
            [
                f"{ACK_TOPIC_PREFIX}/mobilefrost/commands",
                f"{ACK_TOPIC_PREFIX}/mobilefrost/commands",
            ],
        )
        self.assertEqual([result.wait_calls for result in self.cloud_client.results], [0, 0])
        self.assertEqual([result.wait_calls for result in self.local_client.results], [1, 1])

    def test_rejects_malformed_wrong_device_and_out_of_range_commands(self):
        invalid_messages = (
            SimpleNamespace(topic=f"{COMMAND_TOPIC_PREFIX}/mobilefrost/actuators/fan", payload=b"{"),
            command_message("fan", 300),
            command_message("motor", 1),
            command_message("fan", 10, device_id="another-device"),
        )

        for message in invalid_messages:
            self.bridge.on_cloud_message(self.cloud_client, None, message)

        self.assertEqual(self.local_client.published, [])
        self.assertEqual(self.cloud_client.published, [])

    def test_does_not_ack_when_local_publish_fails(self):
        self.local_client.next_result = FakePublishResult(rc=1, published=False)

        self.bridge.on_cloud_message(
            self.cloud_client,
            None,
            command_message("fan", 128),
        )

        self.assertEqual(self.cloud_client.published, [])

    @patch("mobilefrost.aws_bridge.ssl.create_default_context")
    def test_configures_tls_for_aws_iot(self, create_context):
        context = create_context.return_value
        self.bridge.configure_aws_connection()

        create_context.assert_called_once_with(cafile="/secrets/root-ca.pem")
        context.load_cert_chain.assert_called_once_with(
            certfile="/secrets/device-cert.pem",
            keyfile="/secrets/device-private.pem",
        )
        context.set_alpn_protocols.assert_called_once_with(["x-amzn-mqtt-ca"])
        self.assertIs(self.cloud_client.tls_context, context)


class FakePublishResult:
    def __init__(self, rc=0, published=True):
        self.rc = rc
        self.published = published
        self.wait_calls = 0

    def wait_for_publish(self, timeout=None):
        self.wait_calls += 1
        return None

    def is_published(self):
        return self.published


class FakeMqttClient:
    def __init__(self):
        self.subscriptions = []
        self.published = []
        self.results = []
        self.next_result = FakePublishResult()

    def subscribe(self, topic, qos=0):
        self.subscriptions.append((topic, qos))
        return 0, 1

    def publish(self, topic, payload, qos=0, retain=False):
        self.published.append((topic, payload, qos, retain))
        result = self.next_result
        self.results.append(result)
        self.next_result = FakePublishResult()
        return result

    def tls_set_context(self, context):
        self.tls_context = context


def bridge_environment():
    return {
        "AWS_IOT_ENDPOINT": "example-ats.iot.eu-central-1.amazonaws.com",
        "AWS_IOT_THING_NAME": "mobilefrost",
        "AWS_IOT_CERTIFICATE_PATH": "/secrets/device-cert.pem",
        "AWS_IOT_PRIVATE_KEY_PATH": "/secrets/device-private.pem",
        "AWS_IOT_ROOT_CA_PATH": "/secrets/root-ca.pem",
        "MQTT_HOST": "mosquitto",
        "MQTT_PORT": "1883",
    }


def command_message(kind, value, device_id="mobilefrost"):
    import json

    topic = f"{COMMAND_TOPIC_PREFIX}/{device_id}/actuators/{kind}"
    payload = json.dumps(
        {
            "request_id": f"request-{kind}-{value}",
            "device_id": device_id,
            "kind": kind,
            "value": value,
            "created_at": "2026-10-01T09:00:00+00:00",
        }
    ).encode("utf-8")
    return SimpleNamespace(topic=topic, payload=payload)


if __name__ == "__main__":
    main()