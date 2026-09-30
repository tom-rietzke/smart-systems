import importlib
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import types
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

sys.modules.setdefault("serial", types.SimpleNamespace(Serial=object))

fake_psycopg2 = types.ModuleType("psycopg2")
fake_psycopg2.OperationalError = Exception
fake_psycopg2.connect = lambda **kwargs: None
sys.modules.setdefault("psycopg2", fake_psycopg2)

app = importlib.import_module("mobilefrost.__main__")
config = importlib.import_module("mobilefrost.config")
controller = importlib.import_module("mobilefrost.controller")
database = importlib.import_module("mobilefrost.database")
display = importlib.import_module("mobilefrost.display")
mqtt_io = importlib.import_module("mobilefrost.mqtt_io")
cloud_sync = importlib.import_module("mobilefrost.cloud_sync")
sensor_io = importlib.import_module("mobilefrost.sensor_io")


class TemperatureSensorTests(unittest.TestCase):
    def test_parses_temperature_line(self):
        self.assertEqual(sensor_io.parse_temperature("Aktuelle Temperatur: 21.75"), 21.75)
        self.assertIsNone(sensor_io.parse_temperature("Bereit"))
        self.assertIsNone(sensor_io.parse_temperature("Aktuelle Temperatur: nan?"))

    def test_configures_all_named_sensors(self):
        sensor_ids = [sensor["id"] for sensor in config.SENSORS]

        self.assertEqual(
            sensor_ids,
            [
                "arduino_sensor_marten",
                "arduino_sensor_andor",
                "arduino_sensor_luis",
            ],
        )
        self.assertEqual(config.SENSORS[2]["temperature_offset"], -1.0)
        self.assertEqual(config.DATABASE_WRITE_INTERVAL, 10.0)

    def test_config_declares_mqtt_defaults(self):
        self.assertEqual(config.MQTT_HOST, "mosquitto")
        self.assertEqual(config.MQTT_PORT, 1883)

    def test_applies_configured_temperature_offset(self):
        sensor = {
            "id": "arduino_sensor_luis",
            "port": "/dev/arduino_sensor_luis",
            "temperature_offset": -1.0,
        }
        manager = sensor_io.SensorManager(
            serial_factory=lambda _port, _baud_rate, timeout: ReadingSerial(
                b"Aktuelle Temperatur: 24.0\n"
            ),
            clock=lambda: 0.0,
            sensors=(sensor,),
        )
        manager.connect_available()

        self.assertEqual(
            list(manager.readings()),
            [("arduino_sensor_luis", 23.0)],
        )

    def test_formats_display_command_for_all_sensors(self):
        last_temperatures = {
            "arduino_sensor_marten": 21.74,
            "arduino_sensor_andor": 22.35,
            "arduino_sensor_luis": 23.86,
        }

        command = display.format_display_command(last_temperatures)

        self.assertEqual(command, "D:21.7;22.4;23.9\n")

    def test_stores_temperature_and_commits(self):
        cursor = RecordingCursor()
        connection = RecordingConnection()

        self.assertTrue(
            database.store_temperature(
                cursor, connection, "arduino_sensor_luis", 23.5
            )
        )
        self.assertEqual(
            cursor.executions[0], ("arduino_sensor_luis", 23.5)
        )
        self.assertEqual(connection.commits, 1)
        self.assertEqual(connection.rollbacks, 0)

    def test_stores_temperature_and_enqueues_cloud_outbox_atomically(self):
        cursor = RecordingCursor()
        connection = RecordingConnection()

        self.assertTrue(
            database.store_temperature(
                cursor, connection, "arduino_sensor_luis", 23.5
            )
        )

        self.assertEqual(len(cursor.queries), 2)
        self.assertIn("INSERT INTO temperatures", cursor.queries[0])
        self.assertIn("INSERT INTO cloud_outbox", cursor.queries[1])
        self.assertEqual(connection.commits, 1)
        self.assertEqual(connection.rollbacks, 0)

    def test_outbox_insert_failure_rolls_back_temperature_insert(self):
        cursor = RecordingCursor(error_on_query="INSERT INTO cloud_outbox")
        connection = RecordingConnection()

        self.assertFalse(
            database.store_temperature(
                cursor, connection, "arduino_sensor_luis", 23.5
            )
        )

        self.assertEqual(connection.commits, 0)
        self.assertEqual(connection.rollbacks, 1)

    def test_fetches_pending_cloud_readings_in_timestamp_order(self):
        rows = [
            (7, "arduino_sensor_luis", 23.5, datetime(2026, 9, 30, 9, 0)),
            (8, "arduino_sensor_marten", 22.0, datetime(2026, 9, 30, 9, 1)),
        ]
        cursor = RecordingCursor(rows=rows)

        result = database.fetch_pending_cloud_readings(cursor, limit=2)

        self.assertEqual(result, rows)
        self.assertIn("published_at IS NULL", cursor.queries[0])
        self.assertIn("ORDER BY temperatures.timestamp ASC", cursor.queries[0])
        self.assertEqual(cursor.parameters, (2,))

    def test_marks_cloud_reading_published_and_commits(self):
        cursor = RecordingCursor(rowcount=1)
        connection = RecordingConnection()

        result = database.mark_cloud_reading_published(cursor, connection, 7)

        self.assertTrue(result)
        self.assertIn("UPDATE cloud_outbox", cursor.queries[0])
        self.assertEqual(cursor.parameters, (7,))
        self.assertEqual(connection.commits, 1)

    def test_database_error_rolls_back_without_raising(self):
        cursor = RecordingCursor(error=RuntimeError("database unavailable"))
        connection = RecordingConnection()

        self.assertFalse(
            database.store_temperature(
                cursor, connection, "arduino_sensor_luis", 23.5
            )
        )
        self.assertEqual(connection.commits, 0)
        self.assertEqual(connection.rollbacks, 1)

    def test_initial_display_command_contains_placeholders(self):
        self.assertEqual(display.format_display_command({}), "D:--.-;--.-;--.-\n")

    def test_initializes_display_after_serial_connection(self):
        serial_connection = RecordingSerial()

        display.initialize_display(serial_connection)

        self.assertEqual(serial_connection.writes, [b"D:--.-;--.-;--.-\n"])

    def test_connects_available_sensors_when_one_is_unavailable(self):
        def serial_factory(port, _baud_rate, timeout):
            self.assertEqual(timeout, 2)
            if port.endswith("luis"):
                raise OSError("device missing")
            return RecordingSerial()

        manager = sensor_io.SensorManager(serial_factory=serial_factory)
        manager.connect_available()

        self.assertEqual(
            list(manager.connections),
            ["arduino_sensor_marten", "arduino_sensor_andor"],
        )

    def test_reconnects_sensor_after_retry_interval(self):
        now = [0.0]
        luis_available = [False]

        def serial_factory(port, _baud_rate, timeout):
            self.assertEqual(timeout, 2)
            if port.endswith("luis") and not luis_available[0]:
                raise OSError("device missing")
            return RecordingSerial()

        manager = sensor_io.SensorManager(
            serial_factory=serial_factory,
            clock=lambda: now[0],
            retry_interval=5.0,
        )
        manager.connect_available()
        self.assertNotIn("arduino_sensor_luis", manager.connections)

        luis_available[0] = True
        now[0] = 5.0
        manager.retry_missing()

        self.assertIn("arduino_sensor_luis", manager.connections)

    def test_read_error_disconnects_only_failed_sensor(self):
        serial_connections = {
            "/dev/arduino_sensor_marten": ReadingSerial(error=OSError("disconnected")),
            "/dev/arduino_sensor_andor": ReadingSerial(b"Aktuelle Temperatur: 22.0\n"),
            "/dev/arduino_sensor_luis": ReadingSerial(b"Aktuelle Temperatur: 23.0\n"),
        }
        manager = sensor_io.SensorManager(
            serial_factory=lambda port, _baud_rate, timeout: serial_connections[port],
            clock=lambda: 0.0,
        )
        manager.connect_available()

        self.assertEqual(
            list(manager.readings()),
            [
                ("arduino_sensor_andor", 22.0),
                ("arduino_sensor_luis", 22.0),
            ],
        )
        self.assertNotIn("arduino_sensor_marten", manager.connections)
        self.assertIn("arduino_sensor_andor", manager.connections)
        self.assertTrue(serial_connections["/dev/arduino_sensor_marten"].closed)

    def test_controller_processes_available_sensor(self):
        actuator = RecordingSerial()
        manager = RecordingSensorManager([
            ("arduino_sensor_luis", 23.5),
        ])
        cursor = RecordingCursor()
        connection = RecordingConnection()
        service = controller.Controller(
            actuator,
            manager,
            cursor,
            connection,
            sleep_func=lambda _seconds: None,
        )

        self.assertEqual(service.run_once(), 1)

        self.assertEqual(actuator.writes[0], b"D:--.-;--.-;23.5\n")
        self.assertEqual(
            cursor.executions[0], ("arduino_sensor_luis", 23.5)
        )
        self.assertEqual(manager.retry_calls, 1)

    def test_controller_displays_every_reading_and_stores_every_ten_seconds(self):
        now = [0.0]
        sleeps = []
        actuator = RecordingSerial()
        manager = RecordingSensorManager([("arduino_sensor_luis", 23.5)])
        cursor = RecordingCursor()
        connection = RecordingConnection()
        service = controller.Controller(
            actuator,
            manager,
            cursor,
            connection,
            clock=lambda: now[0],
            sleep_func=sleeps.append,
        )

        service.run_once()
        now[0] = 5.0
        service.run_once()
        now[0] = 10.0
        service.run_once()

        self.assertEqual(
            actuator.writes,
            [
                b"D:--.-;--.-;23.5\n",
                b"F:0\n",
                b"S:0\n",
                b"D:--.-;--.-;23.5\n",
                b"D:--.-;--.-;23.5\n",
            ],
        )
        self.assertEqual(
            sum("INSERT INTO temperatures" in query for query in cursor.queries),
            2,
        )
        self.assertEqual(sleeps, [])

    def test_controller_retries_database_write_after_failure(self):
        now = [0.0]
        cursor = RecordingCursor(error=RuntimeError("database unavailable"))
        connection = RecordingConnection()
        service = controller.Controller(
            RecordingSerial(),
            RecordingSensorManager([("arduino_sensor_luis", 23.5)]),
            cursor,
            connection,
            clock=lambda: now[0],
            sleep_func=lambda _seconds: None,
        )

        service.run_once()
        cursor.error = None
        now[0] = 1.0
        service.run_once()

        self.assertEqual(connection.rollbacks, 1)
        self.assertEqual(connection.commits, 1)

    def test_controller_publishes_temperature_reading_to_mqtt(self):
        timestamp = datetime(2026, 9, 21, 12, 34, 56, tzinfo=timezone.utc)
        mqtt_adapter = RecordingMqttAdapter()
        service = controller.Controller(
            RecordingSerial(),
            RecordingSensorManager([("arduino_sensor_luis", 23.5)]),
            RecordingCursor(),
            RecordingConnection(),
            clock=lambda: 42.0,
            wall_clock=lambda: timestamp,
            mqtt_adapter=mqtt_adapter,
            sleep_func=lambda _seconds: None,
        )

        service.run_once()

        self.assertEqual(
            mqtt_adapter.temperatures,
            [("arduino_sensor_luis", 23.5, timestamp)],
        )

    def test_controller_publishes_cooling_state_changes_to_mqtt(self):
        mqtt_adapter = RecordingMqttAdapter()
        actuator = RecordingSerial()
        service = controller.Controller(
            actuator,
            RecordingSensorManager([("arduino_sensor_luis", 27.0)]),
            RecordingCursor(),
            RecordingConnection(),
            mqtt_adapter=mqtt_adapter,
            sleep_func=lambda _seconds: None,
        )

        service.run_once()

        self.assertEqual(mqtt_adapter.cooling_states, [(True, "automatic")])
        self.assertEqual(actuator.writes, [b"D:--.-;--.-;27.0\n", b"F:255\n", b"S:0\n"])

    def test_controller_opens_flap_at_thirty_degrees(self):
        actuator = RecordingSerial()
        service = controller.Controller(
            actuator,
            RecordingSensorManager([("arduino_sensor_luis", 30.0)]),
            RecordingCursor(),
            RecordingConnection(),
            sleep_func=lambda _seconds: None,
        )

        service.run_once()

        self.assertEqual(actuator.writes, [b"D:--.-;--.-;30.0\n", b"F:255\n", b"S:90\n"])

    def test_controller_opens_flap_when_temperature_rises_after_fan_started(self):
        actuator = RecordingSerial()
        service = controller.Controller(
            actuator,
            RecordingSensorManager([("arduino_sensor_luis", 27.0)]),
            RecordingCursor(),
            RecordingConnection(),
            sleep_func=lambda _seconds: None,
        )

        service.run_once()
        service.sensor_manager = RecordingSensorManager([("arduino_sensor_luis", 30.0)])
        service.run_once()

        self.assertEqual(
            actuator.writes,
            [
                b"D:--.-;--.-;27.0\n",
                b"F:255\n",
                b"S:0\n",
                b"D:--.-;--.-;30.0\n",
                b"S:90\n",
            ],
        )

    def test_controller_handles_mqtt_actuator_commands(self):
        actuator = RecordingSerial()
        service = controller.Controller(
            actuator,
            RecordingSensorManager([]),
            RecordingCursor(),
            RecordingConnection(),
            sleep_func=lambda _seconds: None,
        )

        service.handle_actuator_command("fan", 128)
        service.handle_actuator_command("flap", 45)

        self.assertEqual(actuator.writes, [b"F:128\n", b"S:45\n"])


class RecordingCursor:
    def __init__(self, error=None, rows=None, rowcount=1, error_on_query=None):
        self.error = error
        self.error_on_query = error_on_query
        self.parameters = None
        self.executions = []
        self.queries = []
        self.rows = rows or []
        self.rowcount = rowcount

    def execute(self, query, parameters):
        if self.error:
            raise self.error
        self.queries.append(query)
        if self.error_on_query and self.error_on_query in query:
            raise RuntimeError("outbox unavailable")
        self.parameters = parameters
        self.executions.append(parameters)

    def fetchone(self):
        return (42, datetime(2026, 9, 30, tzinfo=timezone.utc))

    def fetchall(self):
        return self.rows


class RecordingConnection:
    def __init__(self):
        self.commits = 0
        self.rollbacks = 0

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


class RecordingSerial:
    def __init__(self):
        self.writes = []

    def write(self, value):
        self.writes.append(value)


class ReadingSerial:
    def __init__(self, value=b"", error=None):
        self.value = value
        self.error = error
        self.closed = False

    def readline(self):
        if self.error:
            raise self.error
        return self.value

    def close(self):
        self.closed = True


class RecordingSensorManager:
    def __init__(self, readings):
        self._readings = readings
        self.retry_calls = 0

    def retry_missing(self):
        self.retry_calls += 1

    def readings(self):
        return iter(self._readings)


class RecordingMqttAdapter:
    def __init__(self):
        self.started_with = None
        self.temperatures = []
        self.cooling_states = []

    def start(self, on_command):
        self.started_with = on_command

    def publish_temperature(self, sensor_id, value, timestamp):
        self.temperatures.append((sensor_id, value, timestamp))

    def publish_cooling_state(self, enabled, source="automatic"):
        self.cooling_states.append((enabled, source))


class RecordingMqttClient:
    def __init__(self):
        self.published = []
        self.connected = None
        self.subscriptions = []
        self.loop_started = False
        self.on_connect = None
        self.on_message = None

    def publish(self, topic, payload, retain=False):
        self.published.append((topic, payload, retain))

    def connect_async(self, host, port):
        self.connected = (host, port)

    def subscribe(self, topic):
        self.subscriptions.append(topic)

    def loop_start(self):
        self.loop_started = True


class RecordingPublishInfo:
    def __init__(self, published):
        self.rc = 0
        self.published = published

    def wait_for_publish(self, timeout=None):
        self.timeout = timeout

    def is_published(self):
        return self.published


class RecordingCloudMqttClient:
    def __init__(self, published=True):
        self.published_result = published
        self.tls_configuration = None
        self.connection = None
        self.published = []
        self.loop_started = False

    def tls_set(self, **configuration):
        self.tls_configuration = configuration

    def connect(self, endpoint, port, keepalive):
        self.connection = (endpoint, port, keepalive)

    def loop_start(self):
        self.loop_started = True

    def publish(self, topic, payload, qos):
        self.published.append((topic, payload, qos))
        return RecordingPublishInfo(self.published_result)


class RecordingCloudPublisher:
    def __init__(self, results):
        self.results = list(results)
        self.events = []

    def publish(self, sensor_id, payload):
        self.events.append((sensor_id, payload))
        return self.results.pop(0)


class FailingMqttClient:
    def publish(self, _topic, _payload, retain=False):
        raise RuntimeError("broker unavailable")


class MqttIoTests(unittest.TestCase):
    def test_formats_temperature_payload_as_json(self):
        timestamp = datetime(2026, 9, 21, 12, 34, 56, tzinfo=timezone.utc)

        payload = mqtt_io.format_temperature_payload(
            "arduino_sensor_marten",
            22.5,
            timestamp,
        )

        self.assertEqual(
            payload,
            '{"sensor_id":"arduino_sensor_marten","value":22.5,"timestamp":"2026-09-21T12:34:56+00:00"}',
        )

    def test_formats_cooling_payload_as_json(self):
        payload = mqtt_io.format_cooling_payload(True)

        self.assertEqual(payload, '{"enabled":true,"source":"automatic"}')

    def test_parses_valid_actuator_commands(self):
        self.assertEqual(
            mqtt_io.parse_actuator_command(mqtt_io.FAN_SET_TOPIC, b"128"),
            ("fan", 128),
        )
        self.assertEqual(
            mqtt_io.parse_actuator_command(mqtt_io.FAN_SET_TOPIC, b'"128"'),
            ("fan", 128),
        )
        self.assertEqual(
            mqtt_io.parse_actuator_command(mqtt_io.FLAP_SET_TOPIC, "90"),
            ("flap", 90),
        )

    def test_ignores_invalid_actuator_commands(self):
        invalid_commands = [
            (mqtt_io.FAN_SET_TOPIC, b"256"),
            (mqtt_io.FAN_SET_TOPIC, b"-1"),
            (mqtt_io.FLAP_SET_TOPIC, b"91"),
            (mqtt_io.FLAP_SET_TOPIC, b"open"),
            ("mobilefrost/actuators/unknown/set", b"1"),
        ]

        for topic, payload in invalid_commands:
            with self.subTest(topic=topic, payload=payload):
                self.assertIsNone(mqtt_io.parse_actuator_command(topic, payload))


class CloudSyncTests(unittest.TestCase):
    def test_formats_cloud_payload_with_utc_epoch(self):
        timestamp = datetime(2026, 9, 30, 9, 0)

        payload = cloud_sync.format_cloud_payload(
            7, "arduino_sensor_luis", 23.5, timestamp
        )

        self.assertEqual(
            json.loads(payload),
            {
                "event_id": 7,
                "sensor_id": "arduino_sensor_luis",
                "value": 23.5,
                "timestamp": "2026-09-30T09:00:00+00:00",
                "epoch_ms": 1790758800000,
            },
        )

    def test_cloud_publisher_configures_tls_and_waits_for_qos_one_ack(self):
        client = RecordingCloudMqttClient()
        publisher = cloud_sync.CloudMqttPublisher(
            client,
            "example-ats.iot.eu-central-1.amazonaws.com",
            "mobilefrost-pi",
            "/run/secrets/device-cert.pem",
            "/run/secrets/device-private.pem",
            "/run/secrets/AmazonRootCA1.pem",
        )

        publisher.connect()
        acknowledged = publisher.publish(
            "arduino_sensor_luis", '{"event_id":7}'
        )

        self.assertTrue(acknowledged)
        self.assertEqual(
            client.tls_configuration,
            {
                "ca_certs": "/run/secrets/AmazonRootCA1.pem",
                "certfile": "/run/secrets/device-cert.pem",
                "keyfile": "/run/secrets/device-private.pem",
            },
        )
        self.assertEqual(
            client.connection,
            ("example-ats.iot.eu-central-1.amazonaws.com", 8883, 60),
        )
        self.assertEqual(
            client.published,
            [
                (
                    "mobilefrost/cloud/temperatures/arduino_sensor_luis",
                    '{"event_id":7}',
                    1,
                )
            ],
        )

    def test_cloud_publisher_returns_false_without_publish_ack(self):
        client = RecordingCloudMqttClient(published=False)
        publisher = cloud_sync.CloudMqttPublisher(
            client,
            "example-ats.iot.eu-central-1.amazonaws.com",
            "mobilefrost-pi",
            "device-cert.pem",
            "device-private.pem",
            "AmazonRootCA1.pem",
        )

        self.assertFalse(
            publisher.publish("arduino_sensor_luis", '{"event_id":7}')
        )

    def test_sync_once_marks_only_acknowledged_rows(self):
        rows = [
            (7, "arduino_sensor_luis", 23.5, datetime(2026, 9, 30, 9, 0)),
            (8, "arduino_sensor_marten", 22.0, datetime(2026, 9, 30, 9, 1)),
        ]
        cursor = RecordingCursor(rows=rows)
        connection = RecordingConnection()
        publisher = RecordingCloudPublisher([True, True])

        count = cloud_sync.sync_once(cursor, connection, publisher, batch_size=2)

        self.assertEqual(count, 2)
        self.assertEqual(
            [parameters for parameters in cursor.executions[1:]],
            [(7,), (8,)],
        )
        self.assertEqual(len(publisher.events), 2)
        self.assertEqual(connection.commits, 2)

    def test_sync_once_leaves_failed_and_later_rows_pending(self):
        rows = [
            (7, "arduino_sensor_luis", 23.5, datetime(2026, 9, 30, 9, 0)),
            (8, "arduino_sensor_marten", 22.0, datetime(2026, 9, 30, 9, 1)),
            (9, "arduino_sensor_andor", 22.4, datetime(2026, 9, 30, 9, 2)),
        ]
        cursor = RecordingCursor(rows=rows)
        connection = RecordingConnection()
        publisher = RecordingCloudPublisher([True, False])

        count = cloud_sync.sync_once(cursor, connection, publisher, batch_size=3)

        self.assertEqual(count, 1)
        self.assertEqual(cursor.executions[1:], [(7,)])
        self.assertEqual(len(publisher.events), 2)
        self.assertEqual(connection.commits, 1)

    def test_cloud_configuration_is_disabled_when_incomplete(self):
        self.assertIsNone(cloud_sync.cloud_configuration_from_env({}))

    def test_cloud_configuration_accepts_database_and_tls_paths(self):
        environment = {
            "DB_HOST": "db",
            "DB_PORT": "5432",
            "DB_NAME": "mobilefrost_db",
            "DB_USER": "mobilefrost_user",
            "DB_PASSWORD": "local-db-password",
            "AWS_IOT_ENDPOINT": "example-ats.iot.eu-central-1.amazonaws.com",
            "AWS_IOT_THING_NAME": "mobilefrost-pi",
            "AWS_IOT_CERTIFICATE_PATH": "/run/secrets/device-cert.pem",
            "AWS_IOT_PRIVATE_KEY_PATH": "/run/secrets/device-private.pem",
            "AWS_IOT_ROOT_CA_PATH": "/run/secrets/AmazonRootCA1.pem",
        }

        configuration = cloud_sync.cloud_configuration_from_env(environment)

        self.assertEqual(configuration["endpoint"], environment["AWS_IOT_ENDPOINT"])
        self.assertEqual(configuration["thing_name"], "mobilefrost-pi")
        self.assertEqual(
            configuration["private_key_path"],
            "/run/secrets/device-private.pem",
        )

    def test_adapter_publishes_temperature_to_sensor_topic(self):
        client = RecordingMqttClient()
        adapter = mqtt_io.MqttAdapter(client=client)
        timestamp = datetime(2026, 9, 21, 12, 34, 56, tzinfo=timezone.utc)

        adapter.publish_temperature("arduino_sensor_marten", 22.5, timestamp)

        self.assertEqual(
            client.published,
            [
                (
                    "mobilefrost/temperatures/arduino_sensor_marten",
                    '{"sensor_id":"arduino_sensor_marten","value":22.5,"timestamp":"2026-09-21T12:34:56+00:00"}',
                    True,
                )
            ],
        )

    def test_adapter_publishes_cooling_state(self):
        client = RecordingMqttClient()
        adapter = mqtt_io.MqttAdapter(client=client)

        adapter.publish_cooling_state(False)

        self.assertEqual(
            client.published,
            [("mobilefrost/status/cooling", '{"enabled":false,"source":"automatic"}', True)],
        )

    def test_adapter_ignores_publish_errors(self):
        adapter = mqtt_io.MqttAdapter(client=FailingMqttClient())
        timestamp = datetime(2026, 9, 21, 12, 34, 56, tzinfo=timezone.utc)

        adapter.publish_temperature("arduino_sensor_marten", 22.5, timestamp)
        adapter.publish_cooling_state(True)

    def test_adapter_starts_subscription_for_actuator_commands(self):
        commands = []
        client = RecordingMqttClient()
        adapter = mqtt_io.MqttAdapter(client=client, host="broker", port=1883)

        adapter.start(lambda kind, value: commands.append((kind, value)))
        self.assertEqual(client.subscriptions, [])

        client.on_connect(client, None, None, None, None)
        client.on_message(
            None,
            None,
            types.SimpleNamespace(topic=mqtt_io.FAN_SET_TOPIC, payload=b"128"),
        )

        self.assertEqual(client.connected, ("broker", 1883))
        self.assertEqual(
            client.subscriptions,
            [mqtt_io.FAN_SET_TOPIC, mqtt_io.FLAP_SET_TOPIC],
        )
        self.assertTrue(client.loop_started)
        self.assertEqual(commands, [("fan", 128)])


class ArduinoIntegrationTests(unittest.TestCase):
    def test_dockerfile_installs_and_runs_package(self):
        dockerfile = (PROJECT_ROOT / "Dockerfile").read_text(encoding="utf-8")

        self.assertIn("COPY pyproject.toml ./", dockerfile)
        self.assertIn("COPY src ./src", dockerfile)
        self.assertIn("RUN pip install --no-cache-dir .", dockerfile)
        self.assertIn('CMD ["python", "-u", "-m", "mobilefrost"]', dockerfile)

    def test_compose_allows_missing_and_reconnected_sensors(self):
        compose = (PROJECT_ROOT / "compose.yml").read_text(encoding="utf-8")

        self.assertIn('"/dev:/dev"', compose)
        self.assertNotIn("device_cgroup_rules", compose)
        self.assertNotIn('"/dev/arduino_sensor_luis:/dev/arduino_sensor_luis"', compose)
        self.assertIn("keep-groups", compose)

    def test_compose_exposes_dashboard_on_loopback_only(self):
        compose = (PROJECT_ROOT / "compose.yml").read_text(encoding="utf-8")

        self.assertIn("dashboard:", compose)
        self.assertIn('"127.0.0.1:8080:8080"', compose)
        self.assertIn("mobilefrost.dashboard:create_app()", compose)

    def test_compose_adds_mqtt_and_nodered_services(self):
        compose = (PROJECT_ROOT / "compose.yml").read_text(encoding="utf-8")

        self.assertIn("mosquitto:", compose)
        self.assertIn("image: eclipse-mosquitto:2", compose)
        self.assertIn('"1883:1883"', compose)
        self.assertIn("nodered:", compose)
        self.assertIn("image: nodered/node-red:latest", compose)
        self.assertIn('"127.0.0.1:1880:1880"', compose)

    def test_compose_adds_opt_in_cloud_sync_with_read_only_certificates(self):
        compose = (PROJECT_ROOT / "compose.yml").read_text(encoding="utf-8")

        self.assertIn("cloud_sync:", compose)
        self.assertIn("profiles:\n      - cloud", compose)
        self.assertIn("python", compose)
        self.assertIn("-m", compose)
        self.assertIn("mobilefrost.cloud_sync", compose)
        self.assertIn("AWS_IOT_ENDPOINT", compose)
        self.assertIn("./secrets:/run/secrets/aws-iot:ro", compose)

    def test_controller_receives_mqtt_environment(self):
        compose = (PROJECT_ROOT / "compose.yml").read_text(encoding="utf-8")

        self.assertIn("- MQTT_HOST=mosquitto", compose)
        self.assertIn("- MQTT_PORT=1883", compose)

    def test_pyproject_declares_mqtt_dependency(self):
        pyproject = (PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8")

        self.assertIn('"paho-mqtt>=2.0,<3",', pyproject)

    def test_main_passes_mqtt_adapter_to_controller(self):
        main_file = (PROJECT_ROOT / "src" / "mobilefrost" / "__main__.py").read_text(encoding="utf-8")

        self.assertIn("from .mqtt_io import build_mqtt_adapter", main_file)
        self.assertIn("mqtt_adapter=build_mqtt_adapter()", main_file)

    def test_humidity_sketch_uses_requested_hardware(self):
        sketch = (
            PROJECT_ROOT / "sketches" / "sketch_humidity" / "sketch_humidity.ino"
        ).read_text(encoding="utf-8")

        self.assertIn("DHT dht(A0, DHT11);", sketch)
        self.assertIn("const int LED_R = 9;", sketch)
        self.assertIn("const int LED_G = 10;", sketch)
        self.assertIn("const int LED_B = 11;", sketch)
        self.assertIn('Serial.print("Aktuelle Temperatur: ");', sketch)
        self.assertIn('Serial.print("Aktuelle Luftfeuchtigkeit: ");', sketch)

    def test_actuator_displays_third_temperature_bottom_right(self):
        sketch = (
            PROJECT_ROOT / "sketches" / "sketch_fanANDled" / "sketch_fanANDled.ino"
        ).read_text(encoding="utf-8")

        self.assertIn("String tempLuis", sketch)
        self.assertIn("lcd.setCursor(11, 0);", sketch)
        self.assertIn("lcd.setCursor(11, 1);", sketch)


if __name__ == "__main__":
    unittest.main()