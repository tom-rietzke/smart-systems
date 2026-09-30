# AWS IoT Core und Timestream einrichten

Diese Anleitung verbindet den MobileFrost-Raspberry-Pi mit AWS IoT Core. Der Pi
behält seine lokale PostgreSQL-Datenbank; ein zusätzlicher Worker überträgt
ausstehende Messungen zu Timestream. Ein Cloud-Ausfall stoppt die lokale
Messwerterfassung nicht.

## Voraussetzungen

- Ein AWS-Konto mit Berechtigungen für AWS IoT Core, Timestream, CloudWatch Logs
  und IAM-Rollen samt Policies. Manche AWS-Academy-/Lab-Konten sperren das
  Anlegen von IAM-Rollen.
- AWS CLI v2, Terraform ab Version 1.5 und Podman Compose.
- Der Raspberry Pi ist mit dem Internet verbunden und kann ausgehende TLS-
  Verbindungen auf Port `443` aufbauen. Der MQTT-Client verwendet für X.509-
  Authentifizierung das AWS-IoT-ALPN-Protokoll `x-amzn-mqtt-ca`.

AWS IoT Core und Timestream für LiveAnalytics speichern die Daten in der bei
Terraform gewählten Region, standardmäßig `eu-central-1`. Vor dem Dauerbetrieb
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
Keine Access Keys oder Passwörter in Projektdateien, Terraform-Variablen oder
Chatnachrichten eintragen. Die folgenden Terraform-Befehle führen keine
Ressourcenänderung aus, bis `apply` bestätigt wird.

## Infrastruktur mit Terraform

Im Repository-Stamm ausführen:

```powershell
terraform -chdir=terraform/aws_iot init
```

Eine lokale, durch Git ignorierte Datei
`terraform/aws_iot/terraform.tfvars` anlegen:

```hcl
aws_region  = "eu-central-1"
project_name = "mobilefrost"
```

Plan prüfen und die Infrastruktur zuerst ohne Gerätezertifikat erstellen:

```powershell
terraform -chdir=terraform/aws_iot plan
terraform -chdir=terraform/aws_iot apply
```

Terraform zeigt die Änderungen an und fragt vor dem Anlegen nochmals nach. Es
werden ein IoT Thing und eine auf den Cloud-Temperatur-Topic begrenzte IoT-Policy,
eine Timestream-Datenbank/-Tabelle, eine IoT-Regel sowie eine IAM-Rolle mit
Schreibrecht nur auf diese Tabelle angelegt. Die Rolle benötigt zusätzlich
`timestream:DescribeEndpoints`. Fehlgeschlagene Regelaktionen werden in einer
CloudWatch-Loggruppe mit 14 Tagen Aufbewahrung protokolliert.

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

Kopiere nur die Zertifikats-ARN in `terraform/aws_iot/terraform.tfvars`:

```hcl
aws_region             = "eu-central-1"
project_name            = "mobilefrost"
device_certificate_arn = "arn:aws:iot:eu-central-1:ACCOUNT_ID:cert/CERTIFICATE_ID"
```

Dann die Bindung des Zertifikats an Thing und Policy anwenden:

```powershell
terraform -chdir=terraform/aws_iot plan
terraform -chdir=terraform/aws_iot apply
```

Das private Schlüsselpaar wird nicht von Terraform erstellt und kommt nicht in
den Terraform-State. Lade die Amazon Root CA separat in denselben lokalen
Geheimnisordner:

```powershell
curl.exe -o (Join-Path $secretDir "AmazonRootCA1.pem") `
  https://www.amazontrust.com/repository/AmazonRootCA1.pem
```

Terraform-Ausgaben anzeigen:

```powershell
terraform -chdir=terraform/aws_iot output
```

Notiere `iot_endpoint` und `thing_name`. Der AWS-Zugang/CLI-Profile wird nur für
Infrastrukturverwaltung gebraucht; der laufende Pi authentifiziert sich mit dem
IoT-Zertifikat.

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
Fahrerdaten. Die Terraform-Tabelle verwendet 24 Stunden Memory-Store- und 30 Tage
Magnetic-Store-Aufbewahrung. CloudWatch-Regelfehlerlogs werden nach 14 Tagen
gelöscht. Preise und Aufbewahrungsbedarf vor längerem Betrieb prüfen; AWS-Preise
können sich ändern.

Demo-Ressourcen nach Abschluss entfernen:

```powershell
terraform -chdir=terraform/aws_iot destroy
```

`destroy` löscht auch Timestream-Datenbank und Tabelle samt Demo-Daten und trennt
das Zertifikat von Thing und Policy. Das separat erzeugte Zertifikat danach
deaktivieren und löschen:

```powershell
$certificateId = ($certificateArn -split "/")[-1]
aws iot update-certificate --certificate-id $certificateId --new-status INACTIVE
aws iot delete-certificate --certificate-id $certificateId
```

Den privaten Schlüssel lokal sicher löschen, sobald keine Sicherung mehr benötigt
wird. Verifiziere im AWS-Kosten-Explorer, dass keine Demo-Ressourcen oder laufenden
Gebühren verblieben sind.