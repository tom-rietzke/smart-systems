from datetime import datetime, timezone
import json
import os


def handle_ack(event, dependencies):
    if not isinstance(event, dict) or not _valid_ack(event, dependencies["device_id"]):
        return _response(400, {"error": "Ungültige Bestätigung"})

    try:
        updated = dependencies["update_command"](event)
    except Exception:
        return _response(503, {"error": "Bestätigung konnte nicht gespeichert werden"})

    if not updated:
        return _response(200, {"status": "ignored"})
    return _response(200, {"status": "acknowledged"})


def lambda_handler(event, context):
    try:
        import boto3

        table = boto3.resource("dynamodb").Table(os.environ["OPERATIONS_TABLE"])
        dependencies = {
            "device_id": os.environ["DEVICE_ID"],
            "update_command": lambda command: update_command(table, command),
        }
    except Exception:
        return _response(503, {"error": "Bestätigung konnte nicht gespeichert werden"})

    return handle_ack(event, dependencies)


def update_command(table, command):
    try:
        table.update_item(
            Key={
                "pk": f"COMMAND#{command['request_id']}",
                "sk": "COMMAND",
            },
            UpdateExpression=(
                "SET #status = :acknowledged, reported_value = :value, "
                "acknowledged_at = :acknowledged_at"
            ),
            ConditionExpression=(
                "device_id = :device_id AND kind = :kind AND #value = :value "
                "AND (#status = :pending OR "
                "(#status = :acknowledged AND reported_value = :value))"
            ),
            ExpressionAttributeNames={
                "#status": "status",
                "#value": "value",
            },
            ExpressionAttributeValues={
                ":device_id": command["device_id"],
                ":kind": command["kind"],
                ":value": command["value"],
                ":pending": "pending",
                ":acknowledged": "acknowledged",
                ":acknowledged_at": command["timestamp"],
            },
        )
        return True
    except Exception as error:
        response = getattr(error, "response", {}) or {}
        error_details = response.get("Error", {})
        if error_details.get("Code") == "ConditionalCheckFailedException":
            return False
        raise


def _valid_ack(event, device_id):
    request_id = event.get("request_id")
    kind = event.get("kind")
    value = event.get("value")
    if (
        not isinstance(request_id, str)
        or not request_id
        or len(request_id) > 128
        or event.get("device_id") != device_id
        or kind not in {"fan", "flap"}
        or type(value) is not int
    ):
        return False

    maximum = 255 if kind == "fan" else 90
    if value < 0 or value > maximum:
        return False

    try:
        timestamp = event.get("timestamp")
        if not isinstance(timestamp, str):
            return False
        datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except ValueError:
        return False
    return True


def _response(status_code, payload):
    return {
        "statusCode": status_code,
        "headers": {"content-type": "application/json; charset=utf-8"},
        "body": json.dumps(payload, separators=(",", ":")),
    }