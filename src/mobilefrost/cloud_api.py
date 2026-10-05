from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
import os
import uuid


ALLOWED_HOURS = {1, 24, 168}
COMMAND_TIMEOUT_SECONDS = 30
SENSOR_IDS = (
    "arduino_sensor_marten",
    "arduino_sensor_andor",
    "arduino_sensor_luis",
)


def handle_request(event, dependencies):
    if not _authenticated_subject(event):
        return _response(401, {"error": "Nicht angemeldet"})

    route_key = event.get("routeKey", "")
    if route_key == "GET /api/temperatures":
        return _get_temperatures(event, dependencies)
    if route_key == "GET /api/drive":
        try:
            return _response(
                200,
                {"active": dependencies["get_active_drive"]()},
            )
        except Exception:
            return _response(503, {"error": "Fahrtstatus nicht erreichbar"})
    if route_key == "POST /api/drive/start":
        return _start_drive(dependencies)
    if route_key == "POST /api/drive/stop":
        return _stop_drive(dependencies)
    if route_key in (
        "POST /api/actuators/fan",
        "POST /api/actuators/flap",
    ):
        return _set_actuator(event, dependencies, route_key.rsplit("/", 1)[-1])
    if route_key == "GET /api/commands/{request_id}":
        return _get_command(event, dependencies)
    return _response(404, {"error": "Nicht gefunden"})


def _get_temperatures(event, dependencies):
    parameters = event.get("queryStringParameters") or {}
    try:
        hours = int(parameters.get("hours", "24"))
    except (TypeError, ValueError):
        return _response(400, {"error": "Ungültiger Zeitraum"})

    if hours not in ALLOWED_HOURS:
        return _response(400, {"error": "Ungültiger Zeitraum"})

    try:
        data = dependencies["query_temperatures"](hours)
        return _response(200, _serialize_data(data, hours))
    except Exception:
        return _response(503, {"error": "Cloud-Daten nicht erreichbar"})


def _start_drive(dependencies):
    try:
        active = dependencies["get_active_drive"]()
        if active is not None:
            return _response(200, {"status": "started", "session": active})
        try:
            session = dependencies["create_drive_session"]()
        except Exception:
            active = dependencies["get_active_drive"]()
            if active is None:
                raise
            session = active
        return _response(200, {"status": "started", "session": session})
    except Exception:
        return _response(503, {"error": "Fahrt konnte nicht gestartet werden"})


def _stop_drive(dependencies):
    try:
        active = dependencies["get_active_drive"]()
        if active is None:
            return _response(200, {"status": "stopped", "active": None})
        try:
            session = dependencies["stop_drive_session"](active)
        except Exception:
            if dependencies["get_active_drive"]() is None:
                return _response(200, {"status": "stopped", "active": None})
            raise
        return _response(200, {"status": "stopped", "session": session})
    except Exception:
        return _response(503, {"error": "Fahrt konnte nicht beendet werden"})


def _set_actuator(event, dependencies, kind):
    payload = _json_body(event)
    if not isinstance(payload, dict):
        return _response(400, {"error": "Ungültiger Wert"})

    value = payload.get("value")
    maximum = 255 if kind == "fan" else 90
    if type(value) is not int or value < 0 or value > maximum:
        return _response(400, {"error": "Ungültiger Wert"})

    now = dependencies.get("now", lambda: datetime.now(timezone.utc))()
    command = {
        "request_id": dependencies.get("new_request_id", lambda: str(uuid.uuid4()))(),
        "device_id": dependencies["device_id"],
        "kind": kind,
        "value": value,
        "created_at": _serialize_timestamp(now),
        "status": "pending",
    }
    try:
        dependencies["store_command"](command)
    except Exception:
        return _response(503, {"error": "Befehl konnte nicht gespeichert werden"})

    try:
        dependencies["publish_command"](command)
    except Exception:
        try:
            dependencies["mark_command_failed"](command["request_id"])
        except Exception:
            pass
        return _response(
            502,
            {"request_id": command["request_id"], "status": "failed"},
        )

    return _response(
        202,
        {"request_id": command["request_id"], "status": "pending"},
    )


def _get_command(event, dependencies):
    path_parameters = event.get("pathParameters") or {}
    request_id = path_parameters.get("request_id")
    if not request_id:
        return _response(400, {"error": "Ungültige Befehls-ID"})

    try:
        command = dependencies["get_command"](request_id)
    except Exception:
        return _response(503, {"error": "Befehlsstatus nicht erreichbar"})
    if command is None:
        return _response(404, {"error": "Befehl nicht gefunden"})

    result = {
        key: value
        for key, value in command.items()
        if key not in {"pk", "sk"}
    }
    if result.get("status") == "pending":
        now = dependencies.get("now", lambda: datetime.now(timezone.utc))()
        created_at = _parse_timestamp(result["created_at"])
        if (now - created_at).total_seconds() >= COMMAND_TIMEOUT_SECONDS:
            result["status"] = "timed_out"
    return _response(200, result)


def _json_body(event):
    body = event.get("body")
    if not isinstance(body, str):
        return None
    try:
        if event.get("isBase64Encoded"):
            import base64

            body = base64.b64decode(body, validate=True).decode("utf-8")
        return json.loads(body)
    except (ValueError, UnicodeDecodeError):
        return None


def lambda_handler(event, context):
    if not _authenticated_subject(event):
        return _response(401, {"error": "Nicht angemeldet"})

    try:
        import boto3

        dynamodb = boto3.resource("dynamodb")
        table = dynamodb.Table(os.environ["OPERATIONS_TABLE"])
        readings_table = dynamodb.Table(os.environ["READINGS_TABLE"])
        iot_data = boto3.client(
            "iot-data",
            endpoint_url=f"https://{os.environ['AWS_IOT_DATA_ENDPOINT']}",
        )
        device_id = os.environ["DEVICE_ID"]
        dependencies = {
            "query_temperatures": lambda hours: query_dynamodb_temperatures(
                readings_table,
                hours,
            ),
            "get_active_drive": lambda: get_active_drive(table, device_id),
            "create_drive_session": lambda: create_drive_session(
                table,
                device_id,
                datetime.now(timezone.utc),
                str(uuid.uuid4()),
            ),
            "stop_drive_session": lambda session: stop_drive_session(
                table,
                session,
                datetime.now(timezone.utc),
            ),
            "store_command": lambda command: store_command(table, command),
            "publish_command": lambda command: publish_command(
                iot_data,
                command,
            ),
            "get_command": lambda request_id: get_command(table, request_id),
            "mark_command_failed": lambda request_id: mark_command_failed(
                table,
                request_id,
            ),
            "device_id": device_id,
        }
    except Exception:
        return _response(503, {"error": "Cloud-Daten nicht erreichbar"})

    return handle_request(event, dependencies)


def get_active_drive(table, device_id):
    response = table.get_item(
        Key={"pk": f"DEVICE#{device_id}", "sk": "ACTIVE_DRIVE"},
        ConsistentRead=True,
    )
    item = response.get("Item")
    if item is None:
        return None
    return _public_session(item)


def create_drive_session(table, device_id, started_at, session_id):
    from boto3.dynamodb.types import TypeSerializer

    started_at = _serialize_timestamp(started_at)
    session = {
        "session_id": session_id,
        "device_id": device_id,
        "started_at": started_at,
        "status": "active",
    }
    active_item = {
        "pk": f"DEVICE#{device_id}",
        "sk": "ACTIVE_DRIVE",
        **session,
    }
    session_item = {
        "pk": f"DRIVE#{session_id}",
        "sk": "SESSION",
        **session,
    }
    serializer = TypeSerializer()
    serialize_item = lambda item: {
        key: serializer.serialize(value) for key, value in item.items()
    }
    table.meta.client.transact_write_items(
        TransactItems=[
            {
                "Put": {
                    "TableName": table.name,
                    "Item": serialize_item(active_item),
                    "ConditionExpression": "attribute_not_exists(pk)",
                }
            },
            {
                "Put": {
                    "TableName": table.name,
                    "Item": serialize_item(session_item),
                    "ConditionExpression": "attribute_not_exists(pk)",
                }
            },
        ]
    )
    return session


def stop_drive_session(table, session, ended_at):
    from boto3.dynamodb.types import TypeSerializer

    ended_at = _serialize_timestamp(ended_at)
    serializer = TypeSerializer()
    serialize_value = serializer.serialize
    table.meta.client.transact_write_items(
        TransactItems=[
            {
                "Update": {
                    "TableName": table.name,
                    "Key": {
                        "pk": serialize_value(f"DRIVE#{session['session_id']}"),
                        "sk": serialize_value("SESSION"),
                    },
                    "UpdateExpression": "SET #status = :stopped, ended_at = :ended_at",
                    "ConditionExpression": "#status = :active",
                    "ExpressionAttributeNames": {"#status": "status"},
                    "ExpressionAttributeValues": {
                        ":active": serialize_value("active"),
                        ":stopped": serialize_value("stopped"),
                        ":ended_at": serialize_value(ended_at),
                    },
                }
            },
            {
                "Delete": {
                    "TableName": table.name,
                    "Key": {
                        "pk": serialize_value(f"DEVICE#{session['device_id']}"),
                        "sk": serialize_value("ACTIVE_DRIVE"),
                    },
                    "ConditionExpression": "session_id = :session_id",
                    "ExpressionAttributeValues": {
                        ":session_id": serialize_value(session["session_id"]),
                    },
                }
            },
        ]
    )
    return {
        **session,
        "status": "stopped",
        "ended_at": ended_at,
    }


def _public_session(item):
    fields = ("session_id", "device_id", "started_at", "ended_at", "status")
    return {field: item[field] for field in fields if field in item}


def store_command(table, command):
    table.put_item(
        Item={
            "pk": f"COMMAND#{command['request_id']}",
            "sk": "COMMAND",
            **command,
        },
        ConditionExpression="attribute_not_exists(pk)",
    )


def publish_command(client, command):
    topic = (
        f"mobilefrost/commands/{command['device_id']}/"
        f"actuators/{command['kind']}"
    )
    payload = {
        key: command[key]
        for key in ("request_id", "device_id", "kind", "value", "created_at")
    }
    client.publish(
        topic=topic,
        qos=1,
        payload=json.dumps(payload, separators=(",", ":")).encode("utf-8"),
    )


def get_command(table, request_id):
    response = table.get_item(
        Key={"pk": f"COMMAND#{request_id}", "sk": "COMMAND"},
        ConsistentRead=True,
    )
    return response.get("Item")


def mark_command_failed(table, request_id):
    table.update_item(
        Key={"pk": f"COMMAND#{request_id}", "sk": "COMMAND"},
        UpdateExpression="SET #status = :failed",
        ConditionExpression="#status = :pending",
        ExpressionAttributeNames={"#status": "status"},
        ExpressionAttributeValues={":failed": "failed", ":pending": "pending"},
    )


def query_dynamodb_temperatures(table, hours, now=None, key_factory=None):
    if hours not in ALLOWED_HOURS:
        raise ValueError("Unsupported temperature range")
    now = datetime.now(timezone.utc) if now is None else now
    if now.tzinfo is None or now.utcoffset() is None:
        now = now.replace(tzinfo=timezone.utc)
    start_time = (now.astimezone(timezone.utc) - timedelta(hours=hours)).isoformat()
    key_factory = _dynamodb_key if key_factory is None else key_factory
    series = {sensor_id: [] for sensor_id in SENSOR_IDS}
    latest = {}

    for sensor_id in SENSOR_IDS:
        history = _query_readings(
            table,
            sensor_id,
            key_factory,
            start_time=start_time,
        )
        series[sensor_id] = [
            (_parse_timestamp(item["timestamp"]), float(item["value"]))
            for item in history
        ]

        latest_items = _query_readings(
            table,
            sensor_id,
            key_factory,
            scan_forward=False,
            limit=1,
        )
        if latest_items:
            item = latest_items[0]
            latest[sensor_id] = (
                _parse_timestamp(item["timestamp"]),
                float(item["value"]),
            )

    return {"series": series, "latest": latest}


def _query_readings(table, sensor_id, key_factory, start_time=None, scan_forward=True, limit=None):
    key_condition = key_factory("sensor_id").eq(sensor_id)
    if start_time is not None:
        key_condition = key_condition & key_factory("timestamp").gte(start_time)

    query = {
        "KeyConditionExpression": key_condition,
        "ScanIndexForward": scan_forward,
    }
    if limit is not None:
        query["Limit"] = limit

    items = []
    response = table.query(**query)
    items.extend(response.get("Items", []))
    while response.get("LastEvaluatedKey") and limit is None:
        query["ExclusiveStartKey"] = response["LastEvaluatedKey"]
        response = table.query(**query)
        items.extend(response.get("Items", []))
    return items


def _dynamodb_key(name):
    from boto3.dynamodb.conditions import Key

    return Key(name)


def _parse_timestamp(value):
    if not isinstance(value, str):
        raise ValueError("Invalid Timestream timestamp")
    normalized = value.replace("Z", "+00:00")
    timestamp = datetime.fromisoformat(normalized)
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    return timestamp.astimezone(timezone.utc)


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
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    return timestamp.astimezone(timezone.utc).isoformat()


def _authenticated_subject(event):
    request_context = event.get("requestContext") or {}
    authorizer = request_context.get("authorizer") or {}
    jwt = authorizer.get("jwt") or {}
    claims = jwt.get("claims") or {}
    return claims.get("sub")


def _response(status_code, payload):
    return {
        "statusCode": status_code,
        "headers": {"content-type": "application/json; charset=utf-8"},
        "body": json.dumps(
            payload,
            separators=(",", ":"),
            default=_json_default,
        ),
    }


def _json_default(value):
    if isinstance(value, Decimal) and value.is_finite():
        if value == value.to_integral_value():
            return int(value)
        return float(value)
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")