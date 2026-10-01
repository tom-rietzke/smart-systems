# AWS IoT Core und Timestream einrichten

Diese Anleitung verbindet den MobileFrost-Raspberry-Pi mit AWS IoT Core. Der Pi
behält seine lokale PostgreSQL-Datenbank; ein zusätzlicher Worker überträgt
ausstehende Messungen zu Timestream. Ein Cloud-Ausfall stoppt die lokale
Messwerterfassung nicht.

## Voraussetzungen

- Ein AWS-Konto mit Berechtigungen für AWS IoT Core, Timestream, CloudWatch Logs
  und IAM-Rollen samt Policies. Manche AWS-Academy-/Lab-Konten sperren das
  Anlegen von IAM-Rollen.
- AWS CLI v2 (nur für die optionale Zertifikatserstellung) und Podman Compose.
- Der Raspberry Pi ist mit dem Internet verbunden und kann ausgehende TLS-
  Verbindungen auf Port `443` aufbauen. Der MQTT-Client verwendet für X.509-
  Authentifizierung das AWS-IoT-ALPN-Protokoll `x-amzn-mqtt-ca`.

AWS IoT Core und Timestream für LiveAnalytics speichern die Daten in der in der
AWS-Konsole ausgewählten Region, empfohlen `eu-central-1`. Vor dem Dauerbetrieb
die aktuelle regionale Preisübersicht für MQTT-Nachrichten, Regelaktionen,
Timestream-Schreibvorgänge, Aufbewahrung und Abfragen prüfen.

## AWS-Zugang vorbereiten

Bei AWS IAM Identity Center (SSO):

```powershell
aws configure sso --profile mobilefrost
aws sso login --profile mobilefrost
$env:AWS_PROFILE = "mobilefrost"
aws sts get-caller-identity
```

Alternativ kann ein bereits eingerichtetes AWS-CLI-Profil verwendet werden.
Keine Access Keys oder Passwörter in Projektdateien oder Chatnachrichten
eintragen. Die Ressourcen werden manuell über die AWS-Konsole eingerichtet.

## AWS-Ressourcen in der Konsole

Für Amplify-Hosting, Cognito, API Gateway, Lambda, DynamoDB, Timestream und die
IoT-Regeln folge der vollständigen
[Amplify-Dashboard-Console-Anleitung](amplify-dashboard-setup.md). Dort sind
Ressourcennamen, Reihenfolge, IAM-Rechte, Topics, Umgebungsvariablen und
Aufräumen beschrieben. Terraform wird nicht benötigt.

## Gerätezertifikat erstellen

Das Zertifikat authentifiziert genau den MQTT-Client des Pi. Erzeuge die Dateien
nicht im Repository und nicht in einem OneDrive-/Dropbox-/Google-Drive-Ordner.
Verwende ein lokales, nicht synchronisiertes Verzeichnis und sichere insbesondere
den privaten Schlüssel verschlüsselt.

In PowerShell:

```powershell
$secretDir = Join-Path $HOME "mobilefrost-aws\secrets"
New-Item -ItemType Directory -Force $secretDir | Out-Null
$certificateArn = aws iot create-keys-and-certificate `
  --set-as-active `
  --certificate-pem-outfile (Join-Path $secretDir "device-cert.pem") `
  --public-key-outfile (Join-Path $secretDir "device-public.pem") `
  --private-key-outfile (Join-Path $secretDir "device-private.pem") `
  --query certificateArn --output text
$certificateArn
```

Die Ausgabe ist die Zertifikats-ARN, kein privater Schlüssel. Gib den privaten
Schlüssel nicht aus und lade ihn nicht in Git hoch. Schränke den Zugriff auf den
Ordner mit den Windows-Dateiberechtigungen ein.

Die äquivalente Bash-Variante:

```bash
secret_dir="$HOME/.mobilefrost/secrets"
mkdir -p "$secret_dir"
chmod 700 "$secret_dir"
aws iot create-keys-and-certificate \
  --set-as-active \
  --certificate-pem-outfile "$secret_dir/device-cert.pem" \
  --public-key-outfile "$secret_dir/device-public.pem" \
  --private-key-outfile "$secret_dir/device-private.pem" \
  --query certificateArn --output text
chmod 600 "$secret_dir/device-private.pem"
```

Das private Schlüsselpaar bleibt ausschließlich im lokalen Geheimnisordner. Lade
die Amazon Root CA separat in denselben Ordner:

```powershell
curl.exe -o (Join-Path $secretDir "AmazonRootCA1.pem") `
  https://www.amazontrust.com/repository/AmazonRootCA1.pem
```

Erstelle bzw. öffne in der AWS-Konsole das Thing und die gerätegebundene
Zertifikat-Policy gemäß der Amplify-Console-Anleitung. Notiere den Device-Data-
Endpoint aus **AWS IoT Core → Settings**. Der Pi authentifiziert sich im Betrieb
mit dem IoT-Zertifikat, nicht mit einem AWS-CLI-Profil.

## Schlüssel auf den Raspberry Pi übertragen

Lege im Pi-Projektstamm einen Ordner `secrets` an. Übertrage Zertifikat,
Privatschlüssel und Root CA über eine vertrauenswürdige SSH-Verbindung. Ersetze
`PI_HOST` und den Zielpfad durch die tatsächliche Pi-Adresse und den geklonten
Projektordner:

```powershell
scp (Join-Path $secretDir "device-cert.pem") `
    (Join-Path $secretDir "device-private.pem") `
    (Join-Path $secretDir "AmazonRootCA1.pem") `
    pi@PI_HOST:~/smart-systems/secrets/
```

Auf dem Pi:

```bash
cd ~/smart-systems
chmod 700 secrets
chmod 600 secrets/device-private.pem
chmod 644 secrets/device-cert.pem secrets/AmazonRootCA1.pem
```

Prüfe vor dem Start, dass `secrets/device-private.pem` nur für den Pi-
Benutzer lesbar ist. Der Compose-Mount ist zusätzlich read-only. Lösche eine
verschlüsselte Sicherung des privaten Schlüssels nicht voreilig; AWS kann den
privaten Schlüssel nach der Erzeugung nicht erneut ausgeben.

## Cloud-Sync starten

Auf dem Pi im Projektstamm `.env` anlegen (die Datei ist durch `.gitignore`
ausgeschlossen):

```dotenv
AWS_IOT_ENDPOINT=DEIN_IOT_ENDPOINT-ats.iot.eu-central-1.amazonaws.com
AWS_IOT_THING_NAME=mobilefrost
```

Dann den Cloud-Service starten:

```bash
podman compose --profile cloud up -d --build cloud_sync
podman compose ps
podman compose logs --tail=100 cloud_sync
```

Die übrigen Services können weiterhin wie gewohnt mit `podman compose up -d
--build` laufen. Ohne `--profile cloud` wird der zusätzliche Worker nicht
gestartet. Nach dem Start wartet er auf lokale Outbox-Einträge.

## Datenfluss prüfen

1. In der AWS-Konsole **IoT Core → Test → MQTT test client** das Topic
   `mobilefrost/cloud/temperatures/#` abonnieren.
2. Eine Temperaturmessung am laufenden System abwarten. Der Worker veröffentlicht
   jede neue lokal gespeicherte Temperatur. Standardmäßig wird je Sensor höchstens
   alle zehn Sekunden ein Messwert lokal gespeichert.
3. Die Nachricht im MQTT-Testclient prüfen. Sie enthält `event_id`, `sensor_id`,
   `value`, den ISO-UTC-Zeitstempel und `epoch_ms`.
4. In **Amazon Timestream → Query editor** die letzten Datensätze abfragen:

```sql
SELECT time, sensor_id, measure_name, measure_value::double AS temperature_c
FROM "mobilefrost_temperatures"."temperature_readings"
WHERE measure_name = 'temperature_c'
ORDER BY time DESC
```

Die Timestream-Regel verwendet `sensor_id` als Dimension und schreibt den
SELECT-Wert `temperature_c` als Messgröße. Ein MQTT-PUBACK bestätigt nur, dass
AWS IoT Core die Nachricht angenommen hat; es bestätigt nicht den Erfolg der
nachgelagerten Timestream-Regel. Bei fehlenden Datensätzen zusätzlich die
CloudWatch-Loggruppe `/aws/iot/mobilefrost/rule-errors` prüfen. `published_at`
in der lokalen Outbox dokumentiert die Annahme durch IoT Core, nicht eine
Ende-zu-Ende-Bestätigung von Timestream.

Für einen Test ohne angeschlossene Sensoren kann auf dem Pi ein Outbox-Datensatz
manuell angelegt werden:

```bash
podman compose exec db psql -U mobilefrost_user -d mobilefrost_db -c \
  "WITH reading AS (
     INSERT INTO temperatures (sensor_id, value)
     VALUES ('cloud_test_sensor', 21.5)
     RETURNING id
   )
   INSERT INTO cloud_outbox (temperature_id)
   SELECT id FROM reading;"
```

Bei einem AWS-/Netzausfall bleiben Einträge mit `published_at IS NULL` lokal
gespeichert. Der Worker versucht die Übertragung später erneut. Sensorsteuerung,
lokale PostgreSQL-Speicherung, Mosquitto und Dashboard bleiben davon unabhängig.

## Kosten, Datenschutz und Aufräumen

Die Region `eu-central-1` hält die Cloud-Daten in der EU. Sensornachrichten
enthalten nur die Sensor-ID, Temperatur und Messzeit, keine Personen- oder
Fahrerdaten. Die Timestream-Tabelle verwendet standardmäßig 24 Stunden Memory-Store- und 30 Tage
Magnetic-Store-Aufbewahrung. CloudWatch-Regelfehlerlogs werden nach 14 Tagen
gelöscht. Preise und Aufbewahrungsbedarf vor längerem Betrieb prüfen; AWS-Preise
können sich ändern.

Demo-Ressourcen nach Abschluss manuell über die AWS-Konsole entfernen. Das löscht
auch Timestream-Datenbank und Tabelle samt Demo-Daten. Das separat erzeugte
Zertifikat danach deaktivieren und löschen:

```powershell
$certificateId = ($certificateArn -split "/")[-1]
aws iot update-certificate --certificate-id $certificateId --new-status INACTIVE
aws iot delete-certificate --certificate-id $certificateId
```

Den privaten Schlüssel lokal sicher löschen, sobald keine Sicherung mehr benötigt
wird. Verifiziere im AWS-Kosten-Explorer, dass keine Demo-Ressourcen oder laufenden
Gebühren verblieben sind.