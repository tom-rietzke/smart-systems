import os
import time

import psycopg2
from psycopg2 import OperationalError


def connect_db_once():
    return psycopg2.connect(
        host=os.environ.get("DB_HOST"),
        port=os.environ.get("DB_PORT"),
        database=os.environ.get("DB_NAME"),
        user=os.environ.get("DB_USER"),
        password=os.environ.get("DB_PASSWORD"),
    )


def connect_db():
    while True:
        try:
            return connect_db_once()
        except OperationalError as error:
            print(f"Datenbank nicht erreichbar: {error}")
            time.sleep(3)


def init_db(connection):
    try:
        cursor = connection.cursor()
        cursor.execute("""CREATE TABLE IF NOT EXISTS temperatures (
            id SERIAL PRIMARY KEY, timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            sensor_id VARCHAR(50), value NUMERIC(5, 2))""")
        cursor.execute("""CREATE TABLE IF NOT EXISTS cloud_outbox (
            id SERIAL PRIMARY KEY,
            temperature_id INTEGER NOT NULL UNIQUE REFERENCES temperatures(id),
            published_at TIMESTAMP NULL)""")
        connection.commit()
    except Exception as error:
        connection.rollback()
        print(f"Fehler beim Erstellen der Tabelle: {error}")


def store_temperature(cursor, connection, sensor_id, temperature):
    try:
        cursor.execute(
            "INSERT INTO temperatures (sensor_id, value) VALUES (%s, %s) RETURNING id",
            (sensor_id, temperature),
        )
        temperature_id = cursor.fetchone()[0]
        cursor.execute(
            "INSERT INTO cloud_outbox (temperature_id) VALUES (%s)",
            (temperature_id,),
        )
        connection.commit()
        return True
    except Exception as error:
        connection.rollback()
        print(f"Datenbankfehler ({sensor_id}): {error}")
        return False


def fetch_pending_cloud_readings(cursor, limit=100):
    cursor.execute(
        """SELECT outbox.id, temperatures.sensor_id, temperatures.value,
                  temperatures.timestamp
           FROM cloud_outbox AS outbox
           JOIN temperatures ON temperatures.id = outbox.temperature_id
           WHERE outbox.published_at IS NULL
           ORDER BY temperatures.timestamp ASC, outbox.id ASC
           LIMIT %s""",
        (limit,),
    )
    return cursor.fetchall()


def mark_cloud_reading_published(cursor, connection, outbox_id):
    try:
        cursor.execute(
            """UPDATE cloud_outbox SET published_at = CURRENT_TIMESTAMP
               WHERE id = %s AND published_at IS NULL""",
            (outbox_id,),
        )
        connection.commit()
        return cursor.rowcount > 0
    except Exception as error:
        connection.rollback()
        print(f"Cloud-Outbox-Fehler ({outbox_id}): {error}")
        return False


def fetch_dashboard_data(connection, hours):
    cursor = connection.cursor()
    try:
        cursor.execute(
            """SELECT sensor_id, timestamp, value
               FROM temperatures
               WHERE timestamp >= CURRENT_TIMESTAMP - (%s * INTERVAL '1 hour')
               ORDER BY timestamp ASC""",
            (hours,),
        )
        history_rows = cursor.fetchall()
        cursor.execute(
            """SELECT DISTINCT ON (sensor_id) sensor_id, timestamp, value
               FROM temperatures
               ORDER BY sensor_id, timestamp DESC"""
        )
        latest_rows = cursor.fetchall()
    finally:
        cursor.close()

    series = {}
    for sensor_id, timestamp, value in history_rows:
        series.setdefault(sensor_id, []).append((timestamp, float(value)))

    latest = {
        sensor_id: (timestamp, float(value))
        for sensor_id, timestamp, value in latest_rows
    }
    return {"series": series, "latest": latest}