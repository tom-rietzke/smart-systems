# Prompt für Gemini: Präsentation zum Projekt MobileFrost

Diesen Prompt kannst du zusammen mit dem Repository-Link an Gemini übergeben, damit
Gemini daraus eine technische Präsentation für das Projekt erstellt.

## Prompt

Du bist ein technischer Präsentationsautor. Erstelle eine fachlich fundierte,
deutschsprachige Präsentation für ein technisches Fachgespräch im Ausbildungsbereich
Smart Systems.

Analysiere dafür zuerst das vollständige GitHub-Repository:

**Repository:** https://github.com/tomrietzke2507/smart-systems

Das Projekt heißt **MobileFrost** und ist eine vernetzte Kühlbox-Anwendung. Mehrere
Arduino-Boards erfassen Messwerte und kommunizieren seriell mit einem Raspberry Pi.
Der Raspberry Pi speichert die Messwerte in PostgreSQL, veröffentlicht Daten über
MQTT, steuert einen Aktor-Arduino mit LCD, Lüfter und Servomotor und stellt ein
Web-Dashboard bereit.

## Ziel der Präsentation

Die Präsentation soll zeigen, wie das Projekt die beiden Challenges des
Bewertungsbogens umsetzt:

1. **Challenge I: Ice Truck Problem - Signale und Bussysteme**
2. **Challenge II: Ice Truck Extension - Kommunikationssysteme und
   Entwicklungswerkzeuge**

Die Präsentation soll für ein technisches Fachgespräch geeignet sein. Erkläre daher
nicht nur, was gebaut wurde, sondern auch die technischen Entscheidungen, Datenflüsse,
Schnittstellen, Schwellenwerte und Grenzen der Umsetzung.

## Verbindliche Regeln für die Analyse

- Verwende ausschließlich Informationen, die im Repository belegt sind.
- Erfinde keine Hardware, Sensoren, Node-RED-Flows, Verdrahtungen, Messwerte oder
  Funktionen.
- Kennzeichne Funktionen, die nur vorbereitet, teilweise umgesetzt oder im Repository
  nicht nachgewiesen sind.
- Unterscheide klar zwischen Quellcode-Nachweis und praktischer Live-Demonstration.
- Weise darauf hin, wenn ein Punkt des Bewertungsbogens nur durch den realen Aufbau
  oder die Präsentation selbst nachgewiesen werden kann.
- Berücksichtige die aktuelle Steuerlogik:
  - Die RGB-LED des DHT11-Arduinos wird bei Temperaturen über `26 °C` rot.
  - Der Lüfter des Aktor-Arduinos schaltet bei einer maximalen Temperatur über
    `26 °C` ein.
  - Die Klappe beziehungsweise der Servo öffnet erst ab `30 °C`.
  - Unter `30 °C` wird die Klappe wieder geschlossen.
- Stelle die serielle Kommunikation mit den konkreten Befehlen und Datenformaten dar.
- Stelle die MQTT-Topic-Hierarchie mit Beispielen dar.
- Beschreibe Node-RED nur als vorhandenen Service beziehungsweise als vorbereitete
  Erweiterung, sofern im Repository kein konkreter Flow versioniert ist.

## Erwartetes Ergebnis

Erstelle:

1. eine fertige Präsentationsstruktur mit ungefähr 10 bis 14 Folien,
2. pro Folie einen aussagekräftigen Titel,
3. kurze, präsentationsgeeignete Stichpunkte,
4. ausführliche Sprechernotizen für das technische Fachgespräch,
5. Vorschläge für Diagramme, Screenshots oder Live-Demonstrationen,
6. eine Abschlussfolie mit Erfüllungsstand und offenen Nachweisen,
7. einen Fragenkatalog mit möglichen Rückfragen und fachlich fundierten Antworten.

Die Folien sollen nicht mit langen Textblöcken überladen sein. Technische Details
gehören bevorzugt in die Sprechernotizen oder in gut lesbare Diagramme.

## Vorgeschlagene Folienstruktur

### Folie 1: Titel und Projektziel

- Projekttitel: MobileFrost
- Smart Systems
- Ice Truck Problem und Ice Truck Extension
- Kurz erklären, welches Problem die Kühlbox-Anwendung löst

### Folie 2: Szenario und Anforderungen

- Temperaturüberwachung einer Kühlbox
- automatische Kühlung
- Anzeige und Speicherung von Messwerten
- Steuerung über Raspberry Pi, MQTT und optionale digitale Endgeräte
- Zusammenhang mit dem Bewertungsbogen

### Folie 3: Gesamtarchitektur

Erstelle ein übersichtliches Architekturdiagramm mit:

- drei Sensor-Arduinos
- Aktor-Arduino
- Raspberry-Pi-Controller
- PostgreSQL
- Mosquitto MQTT
- Node-RED
- Web-Dashboard
- mobilem MQTT-Endgerät beziehungsweise MQTT Explorer

Zeige die Kommunikationswege und kennzeichne serielle Kommunikation, SQL, HTTP und
MQTT jeweils unterschiedlich.

### Folie 4: Sensorik und Arduino-Datenformate

Erkläre:

- DHT11-Sensor
- Temperatur- und Luftfeuchtemessung
- serielle Übertragung mit 9600 Baud
- Temperaturformat:

```text
Aktuelle Temperatur: 22.50
```

- Luftfeuchteformat:

```text
Aktuelle Luftfeuchtigkeit: 48.00
```

- Temperaturkorrektur des Luis-Sensors von `-1.0 °C`

### Folie 5: LED- und Lüfterlogik

Stelle den Zusammenhang zwischen Sensorwert, LED und Lüfter dar:

| Temperatur | LED-Zustand | Lüfter |
| --- | --- | --- |
| unter `24 °C` | blau | aus |
| `24 °C` bis `26 °C` | grün | aus |
| über `26 °C` | rot | ein |

Erkläre, dass die LED-Farben im Arduino-Sketch umgesetzt sind und der Raspberry Pi
die Lüftersteuerung anhand des höchsten bekannten Temperaturwertes ausführt.

### Folie 6: Servo- beziehungsweise Klappensteuerung

Zeige die bewusst getrennte Schwelle:

| Temperatur | Klappe |
| --- | --- |
| unter `30 °C` | geschlossen, `S:0` |
| ab `30 °C` | geöffnet, `S:90` |

Erkläre den seriellen Befehl `S:<winkel>` und die Verarbeitung durch den
Aktor-Arduino. Stelle außerdem heraus, dass der Lüfter bereits bei über `26 °C`
läuft, die Klappe aber erst ab `30 °C` geöffnet wird.

### Folie 7: Kommunikation mehrerer Arduinos

- Gerätepfade und Sensor-IDs aus der Konfiguration zeigen
- Rolle des Raspberry Pi als zentrale Steuerung erklären
- Lesen der seriellen Daten erläutern
- Verhalten bei fehlenden oder später angeschlossenen Sensoren erklären
- LCD-Datenformat `D:<marten>;<andor>;<luis>` zeigen
- Aktor-Befehle `F:<pwm>` und `S:<winkel>` erklären

### Folie 8: Speicherung in PostgreSQL

Erkläre die Tabelle `temperatures` mit:

- `id`
- `timestamp`
- `sensor_id`
- `value`

Beschreibe, warum Messwerte für das Dashboard gespeichert werden und dass pro Sensor
höchstens ein Datenbankeintrag alle zehn Sekunden geschrieben wird, während LCD und
MQTT bei jedem eingehenden Messwert aktualisiert werden.

### Folie 9: MQTT und Topic-Hierarchie

Zeige die Topic-Struktur als Baum:

```text
mobilefrost/
├── temperatures/
│   ├── arduino_sensor_marten
│   ├── arduino_sensor_andor
│   └── arduino_sensor_luis
├── status/
│   └── cooling
└── actuators/
    ├── fan/set
    └── flap/set
```

Erkläre:

- Publisher und Subscriber
- retained Nachrichten
- JSON-Payloads für Temperatur und Kühlstatus
- gültige Wertebereiche für Lüfter und Klappe
- Rolle des Mosquitto-Brokers

### Folie 10: Dashboard, Node-RED und digitales Endgerät

- Flask-Dashboard mit aktuellen Messwerten und Zeiträumen von einer Stunde,
  24 Stunden und sieben Tagen
- Zugriff lokal auf Port `8080`
- Node-RED als Compose-Service auf Port `1880`
- MQTT-App oder MQTT Explorer als weiteres digitales Endgerät
- klar kennzeichnen, welche Teile im Repository konkret implementiert und welche nur
  vorbereitet oder praktisch zu konfigurieren sind

### Folie 11: Automatische Kühlung und Datenfluss

Erstelle ein Ablaufdiagramm:

1. Sensor-Arduino misst Temperatur.
2. Raspberry Pi liest die serielle Nachricht.
3. Wert wird korrigiert und im Speicher aktualisiert.
4. Wert wird an LCD und MQTT weitergegeben.
5. Wert wird gegebenenfalls in PostgreSQL gespeichert.
6. Bei über `26 °C` startet der Lüfter.
7. Ab `30 °C` öffnet die Klappe.

### Folie 12: Bewertung nach dem Bewertungsbogen

Erstelle eine kompakte Tabelle für alle Kriterien aus Challenge I und II mit den
Spalten:

- Kriterium
- Punkte
- Status: umgesetzt, teilweise umgesetzt, vorbereitet, offen
- konkreter Nachweis
- benötigte Live-Demonstration

Verwende als Grundlage die Datei
`docs/anforderungen-bewertungsbogen.md` aus dem Repository.

### Folie 13: Technische Entscheidungen und Grenzen

Bereite Antworten auf diese Themen vor:

- Warum serielle Kommunikation zwischen Arduino und Raspberry Pi?
- Warum MQTT für die Erweiterung?
- Warum PostgreSQL statt ausschließlich flüchtiger Speicherung?
- Warum wird der höchste bekannte Temperaturwert für die Kühlregel verwendet?
- Warum sind Lüfter- und Servo-Schwelle getrennt?
- Wie werden fehlende Sensoren behandelt?
- Welche Sicherheitsrisiken entstehen durch einen offen erreichbaren MQTT-Broker?
- Warum ist der Node-RED-Flow noch als praktische Ergänzung zu betrachten, falls kein
  Flow im Repository vorliegt?

### Folie 14: Live-Demo und Fazit

Schlage eine kurze Live-Demonstration vor:

1. Sensorwert und serielle Nachricht zeigen.
2. LED-Farbe bei verschiedenen Temperaturwerten demonstrieren.
3. Bei über `26 °C` den Lüfter zeigen.
4. Bei mindestens `30 °C` das Öffnen der Klappe zeigen.
5. MQTT-Nachricht mit MQTT Explorer oder einer mobilen App zeigen.
6. Datenbankeintrag und Dashboard-Verlauf zeigen.

Schließe mit einer ehrlichen Zusammenfassung von erfüllten Anforderungen und offenen
Punkten.

## Fragenkatalog

Erstelle zusätzlich mindestens 12 mögliche Fragen eines Prüfers mit kurzen,
technisch korrekten Antworten. Decke mindestens diese Themen ab:

- PWM bei der Lüftersteuerung
- Servo-Winkel und serielle Befehle
- serielle Baudrate und Datenformat
- MQTT Publisher, Subscriber und Topics
- retained MQTT-Nachrichten
- SQL-Tabelle und Schreibintervall
- Temperaturkorrektur
- Verhalten bei Sensorausfall
- automatische Kühlregel
- Unterschied zwischen LED-Schwelle und Servo-Schwelle
- Docker beziehungsweise Podman Compose
- Node-RED und seine Rolle
- Dashboard und Tailscale
- mögliche Verbesserungen für Produktion und Sicherheit

## Format der Antwort

Gib die Präsentation in dieser Form aus:

```text
Folie 1 - Titel
Sichtbare Inhalte:
- ...

Sprechernotizen:
...

Visualisierung oder Demo:
...
```

Verwende klare deutsche Fachsprache. Die Präsentation soll realistisch in etwa
10 bis 15 Minuten vortragbar sein. Markiere Annahmen und fehlende Repository-
Nachweise deutlich, damit im Fachgespräch keine nicht vorhandene Funktion als
fertig umgesetzt dargestellt wird.