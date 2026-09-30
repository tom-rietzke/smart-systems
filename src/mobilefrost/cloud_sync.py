from datetime import timezone
import json
import os
import time

from .database import (
    connect_db,
    fetch_pending_cloud_readings,
    init_db,
    mark_cloud_reading_published,
)


CLOUD_TOPIC_PREFIX = "mobilefrost/cloud/temperatures"


class CloudMqttPublisher:
    def __init__(
        self,
        client,
        endpoint,
        thing_name,
        certificate_path,
        private_key_path,
        root_ca_path,
        ack_timeout=10,
    ):
        self.client = client
        self.endpoint = endpoint
        self.thing_name = thing_name
        self.certificate_path = certificate_path
        self.private_key_path = private_key_path
        self.root_ca_path = root_ca_path
        self.ack_timeout = ack_timeout

    def connect(self):
        self.client.tls_set(
            ca_certs=self.root_ca_path,
            certfile=self.certificate_path,
            keyfile=self.private_key_path,
        )
        self.client.connect(self.endpoint, 8883, keepalive=60)
        self.client.loop_start()

    def publish(self, sensor_id, payload):
        try:
            result = self.client.publish(
                f"{CLOUD_TOPIC_PREFIX}/{sensor_id}",
                payload,
                qos=1,
            )
            if result.rc != 0:
                return False
            result.wait_for_publish(timeout=self.ack_timeout)
            return result.is_published()
        except Exception as error:
            print(f"AWS IoT Publish fehlgeschlagen: {error}")
            return False


def format_cloud_payload(outbox_id, sensor_id, value, timestamp):
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    else:
        timestamp = timestamp.astimezone(timezone.utc)

    return json.dumps(
        {
            "event_id": outbox_id,
            "sensor_id": sensor_id,
            "value": float(value),
            "timestamp": timestamp.isoformat(),
            "epoch_ms": int(timestamp.timestamp() * 1000),
        },
        separators=(",", ":"),
    )


def sync_once(cursor, connection, publisher, batch_size=100):
    pending = fetch_pending_cloud_readings(cursor, limit=batch_size)
    published_count = 0

    for outbox_id, sensor_id, value, timestamp in pending:
        payload = format_cloud_payload(outbox_id, sensor_id, value, timestamp)
        if not publisher.publish(sensor_id, payload):
            break
        if not mark_cloud_reading_published(cursor, connection, outbox_id):
            break
        published_count += 1

    return published_count


def cloud_configuration_from_env(environment=None):
    environment = os.environ if environment is None else environment
    required = {
        "db_host": "DB_HOST",
        "db_port": "DB_PORT",
        "db_name": "DB_NAME",
        "db_user": "DB_USER",
        "db_password": "DB_PASSWORD",
        "endpoint": "AWS_IOT_ENDPOINT",
        "thing_name": "AWS_IOT_THING_NAME",
        "certificate_path": "AWS_IOT_CERTIFICATE_PATH",
        "private_key_path": "AWS_IOT_PRIVATE_KEY_PATH",
        "root_ca_path": "AWS_IOT_ROOT_CA_PATH",
    }
    configuration = {
        key: environment.get(variable)
        for key, variable in required.items()
    }
    if any(not value for value in configuration.values()):
        return None
    return configuration


def build_cloud_publisher(configuration, client=None):
    if client is None:
        import paho.mqtt.client as mqtt

        client = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2,
            client_id=configuration["thing_name"],
            protocol=mqtt.MQTTv311,
        )

    return CloudMqttPublisher(
        client,
        configuration["endpoint"],
        configuration["thing_name"],
        configuration["certificate_path"],
        configuration["private_key_path"],
        configuration["root_ca_path"],
    )


def main():
    configuration = cloud_configuration_from_env()
    if configuration is None:
        print("AWS IoT Cloud-Sync deaktiviert: Konfiguration unvollständig")
        return 0

    connection = connect_db()
    init_db(connection)
    cursor = connection.cursor()
    publisher = build_cloud_publisher(configuration)

    while True:
        try:
            publisher.connect()
            break
        except Exception as error:
            print(f"AWS IoT nicht erreichbar: {error}")
            time.sleep(5)

    while True:
        try:
            published_count = sync_once(cursor, connection, publisher)
            connection.rollback()
        except Exception as error:
            print(f"Cloud-Sync fehlgeschlagen: {error}")
            try:
                connection.rollback()
            except Exception:
                connection = connect_db()
                init_db(connection)
                cursor = connection.cursor()
            published_count = 0

        if published_count == 0:
            time.sleep(2)


if __name__ == "__main__":
    raise SystemExit(main())