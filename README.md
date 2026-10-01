# MobileFrost Smart Systems

MobileFrost ist eine vernetzte Kühlbox-Anwendung für das Projekt Smart Systems.
Mehrere Arduino-Boards liefern Messwerte an einen Raspberry Pi. Der Raspberry Pi
speichert die Daten, steuert den Aktor-Arduino und stellt Messwerte zusätzlich über
MQTT und ein Web-Dashboard bereit.

Eine detaillierte Gegenüberstellung mit dem Bewertungsbogen steht in
[`docs/anforderungen-bewertungsbogen.md`](docs/anforderungen-bewertungsbogen.md).

## Architektur

```mermaid
flowchart LR
    A[Arduino-Sensoren] -->|Seriell| B[Controller]
    B -->|Messwerte| C[(PostgreSQL)]
    B -->|MQTT retained| D[Mosquitto]
    D --> E[Node-RED]
    D --> F[Dashboard / MQTT-Clients]
    B -->|Seriell| G[Arduino-Aktor]
    G --> H[LCD / Lüfter / Servo]
    B -->|Outbox| I[AWS IoT Core]
    I --> J[Amazon Timestream]
    I -->|Aktor-Befehle| L[Pi AWS-Bridge]
    L --> D
    U[Angemeldete Nutzer] --> M[Amplify Dashboard]
    M --> N[Cognito JWT API]
    N --> I
    N --> J
```

### Bestandteile

- [`src/mobilefrost/`](src/mobilefrost/): Python-Controller, Datenbankzugriff,
	MQTT-Adapter und Flask-Dashboard
- [`sketches/`](sketches/): Arduino-Programme für Sensoren und Aktor
- [`compose.yml`](compose.yml): PostgreSQL, Mosquitto, Controller, Dashboard und
	Node-RED
- [`tests/`](tests/): automatisierte Unit- und Dashboard-Tests
- [`docs/`](docs/): technische Pläne, Konfigurationshinweise und Nachweise

## Hardware und Datenformate

Der Controller erwartet diese stabilen Gerätenamen:

| Aufgabe | Gerätename | Sensor-ID |
| --- | --- | --- |
| Sensor Marten | `/dev/arduino_sensor_marten` | `arduino_sensor_marten` |
| Sensor Andor | `/dev/arduino_sensor_andor` | `arduino_sensor_andor` |
| Sensor Luis | `/dev/arduino_sensor_luis` | `arduino_sensor_luis` |
| Aktor | `/dev/arduino_aktor` | - |

Temperatursensoren senden über die serielle Schnittstelle bei 9600 Baud:

```text
Aktuelle Temperatur: 22.50
```

Der DHT11-Sketch sendet zusätzlich:

```text
Aktuelle Luftfeuchtigkeit: 48.00
```

Der Aktor-Arduino empfängt unter anderem folgende Befehle:

```text
D:21.7;22.4;23.9   # drei Temperaturen für das LCD
F:255              # Lüfter-PWM von 0 bis 255
S:90               # Servo-Winkel von 0 bis 180 Grad
```

Der Luis-Sensor erhält im Controller eine Korrektur von `-1.0 °C`. Fehlende Sensoren
werden auf dem LCD als `--.-` dargestellt und automatisch erneut verbunden.

## Voraussetzungen

- Raspberry Pi oder Linux-Rechner mit den vier seriellen Geräten
- Podman mit Compose-Unterstützung
- geflashte Arduino-Boards
- Arduino-Bibliotheken `DHT sensor library` und `Adafruit Unified Sensor` für
	[`sketch_humidity/sketch_humidity.ino`](sketches/sketch_humidity/sketch_humidity.ino)

Die Sketches werden vor dem Containerstart mit der Arduino IDE auf die Boards
geflasht. Der Arduino-Code läuft nicht im Container.

## Starten

Auf dem Linux-Rechner, der die seriellen Geräte bereitstellt:

```bash
podman compose up -d --build
```

Der Stack startet PostgreSQL, Mosquitto, den Controller, das Dashboard und Node-RED.
Die Datenbank wird im Volume `pgdata` und die Node-RED-Daten im Volume `nodered_data`
gespeichert.

Logs und Status prüfen:

```bash
podman compose ps
podman compose logs --tail=100 controller
podman compose logs --tail=100 dashboard
```

Die Compose-Konfiguration bindet `/dev` ein, damit später angeschlossene Sensoren
erkannt werden können. Der Aktor ist für den Controller erforderlich; fehlt er,
wird der Container neu gestartet.

## Tests

```bash
python -m unittest discover -s tests -v
```

## Dashboard

Das Dashboard ist nur auf dem Raspberry-Pi-Loopback unter Port `8080` veröffentlicht:

```bash
curl http://127.0.0.1:8080
```

Es zeigt aktuelle Messwerte sowie Zeitreihen für eine Stunde, 24 Stunden oder sieben
Tage. Die Aktualisierung erfolgt alle zehn Sekunden. Für den Zugriff von einem
Laptop kann Tailscale Serve verwendet werden:

```bash
sudo tailscale serve --bg http://127.0.0.1:8080

```

Tailscale Funnel soll nicht aktiviert werden, da das Dashboard nur im eigenen
Tailnet erreichbar sein soll.

## Datenbank

Messwerte werden in PostgreSQL in der Tabelle `temperatures` gespeichert:

| Spalte | Bedeutung |
| --- | --- |
| `id` | fortlaufende ID |
| `timestamp` | Zeitpunkt der Messung |
| `sensor_id` | zugehöriger Arduino-Sensor |
| `value` | Temperaturwert in °C |

Pro Sensor wird höchstens ein Datenbankwert alle zehn Sekunden geschrieben. Das LCD
und MQTT werden bei jedem eingehenden Messwert aktualisiert.

Für die optionale Cloud-Sicherung legt der Controller den lokalen Temperaturdatensatz
und einen Eintrag in `cloud_outbox` gemeinsam an. Der separate Cloud-Sync überträgt
ausstehende Werte an AWS IoT Core und bestätigt einen Outbox-Eintrag erst nach der
QoS-1-Brokerbestätigung.

## MQTT und Node-RED

Der MQTT-Broker ist unter Port `1883` erreichbar. Der Controller veröffentlicht
beibehaltene Nachrichten und nimmt Aktor-Befehle entgegen.

| Zweck | Topic | Payload |
| --- | --- | --- |
| Temperatur Marten | `mobilefrost/temperatures/arduino_sensor_marten` | JSON |
| Temperatur Andor | `mobilefrost/temperatures/arduino_sensor_andor` | JSON |
| Temperatur Luis | `mobilefrost/temperatures/arduino_sensor_luis` | JSON |
| Kühlstatus | `mobilefrost/status/cooling` | JSON |
| Lüfter setzen | `mobilefrost/actuators/fan/set` | `0` bis `255` |
| Klappe setzen | `mobilefrost/actuators/flap/set` | `0` bis `90` |

Node-RED läuft auf dem Raspberry Pi unter `127.0.0.1:1880`. Innerhalb des Compose-
Netzwerks verwenden MQTT-Nodes den Broker `mosquitto` auf Port `1883`. Ein konkreter
Node-RED-Flow ist in diesem Repository noch nicht versioniert.

## AWS Cloud

AWS IoT Core und Amazon Timestream sind optional. Zertifikats-Setup, Betrieb,
Datenerfassung, Kostenhinweise und Cleanup stehen in der
[AWS-IoT-Einrichtungsanleitung](docs/aws-iot-setup.md). Das login-geschützte
Cloud-Dashboard mit Cognito, API und Pi-Aktor-Rückkanal wird manuell nach der
[Amplify-Console-Anleitung](docs/amplify-dashboard-setup.md) eingerichtet.
Terraform ist nicht erforderlich. Auf dem Raspberry Pi starten Cloud-Sync und
AWS-Bridge nur mit dem Cloud-Profil:

```bash
podman compose --profile cloud up -d --build cloud_sync aws_bridge
```

Die automatische Kühlregel schaltet ab einer maximalen Temperatur über `26.0 °C`
den Lüfter ein. Die Klappe öffnet erst ab `30.0 °C` und schließt darunter wieder.
Damit entspricht die Lüfter-Schwelle dem roten LED-Zustand des DHT11-Sketches.
Manuelle MQTT-Befehle können beim nächsten Temperaturwert durch diese Automatik
überschrieben werden.
