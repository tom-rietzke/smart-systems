# AWS IoT Core und DynamoDB einrichten

Diese Anleitung richtet das Pi-Gerätezertifikat für AWS IoT Core ein. Der Pi
behält seine lokale PostgreSQL-Datenbank; ein zusätzlicher Worker überträgt
ausstehende Messungen an AWS IoT Core. Eine Terraform-IoT-Regel speichert diese
in DynamoDB. Ein Cloud-Ausfall stoppt die lokale Messwerterfassung nicht.

## Voraussetzungen

- Ein AWS-Konto mit Berechtigungen für AWS IoT Core, DynamoDB, CloudWatch Logs
  und IAM-Rollen samt Policies. Manche AWS-Academy-/Lab-Konten sperren das
  Anlegen von IAM-Rollen.
- AWS CLI v2 (nur für die optionale Zertifikatserstellung) und Podman Compose.
- Der Raspberry Pi ist mit dem Internet verbunden und kann ausgehende TLS-
  Verbindungen auf Port `443` aufbauen. Der MQTT-Client verwendet für X.509-
  Authentifizierung das AWS-IoT-ALPN-Protokoll `x-amzn-mqtt-ca`.

AWS IoT Core und DynamoDB speichern die Daten in der in Terraform ausgewählten
Region, empfohlen `eu-central-1`. Vor dem Dauerbetrieb
die aktuelle regionale Preisübersicht für MQTT-Nachrichten, DynamoDB-Lese- und
Schreibvorgänge, Speicher, Aufbewahrung und Abfragen prüfen.

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
eintragen. Terraform nutzt die lokale AWS-CLI-Session.

## Terraform-Ressourcen

Amplify, Cognito, API Gateway, Lambda, beide DynamoDB-Tabellen, IoT-Regeln und
IAM-Rollen werden im Ordner `terraform/amplify` verwaltet. Die Variablen und
Befehle stehen in der [Terraform-Amplify-Anleitung](amplify-dashboard-setup.md).
Das Gerätezertifikat und sein privater Schlüssel werden separat erstellt; nur
die Zertifikats-ARN wird als Terraform-Variable übergeben.

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

Kopiere die Zertifikats-ARN in `device_certificate_arn` der lokalen
`terraform/amplify/terraform.tfvars`. Terraform erstellt Thing, Policy und
Zertifikatszuordnung. Der Device-Data-Endpoint wird nach `terraform apply` als
Output `iot_endpoint` angezeigt. Der Pi authentifiziert sich im Betrieb mit
dem IoT-Zertifikat, nicht mit einem AWS-CLI-Profil.

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
podman compose --profile cloud up -d --build cloud_sync aws_bridge
podman compose ps
podman compose logs --tail=100 cloud_sync aws_bridge
```

Die übrigen Services können weiterhin wie gewohnt mit `podman compose up -d
--build` laufen. Ohne `--profile cloud` werden Cloud-Sync und Bridge nicht
gestartet. Der Worker wartet auf lokale Outbox-Einträge.

## Datenfluss prüfen

1. In der AWS-Konsole **IoT Core → Test → MQTT test client** das Topic
   `mobilefrost/cloud/temperatures/#` abonnieren.
2. Eine Temperaturmessung am laufenden System abwarten. Der Worker veröffentlicht
   jede neue lokal gespeicherte Temperatur. Standardmäßig wird je Sensor höchstens
   alle zehn Sekunden ein Messwert lokal gespeichert.
3. Die Nachricht im MQTT-Testclient prüfen. Sie enthält `event_id`, `sensor_id`,
   `value`, den ISO-UTC-Zeitstempel und `epoch_ms`.
4. In **DynamoDB → Tables → mobilefrost-demo-readings → Explore table items**
  prüfen, ob Items mit `sensor_id`, `timestamp`, `value` und `event_id`
  geschrieben werden. Bei fehlenden Items die IoT-Regel und die CloudWatch-
  Fehlerloggruppe `/aws/iot/mobilefrost-demo/rule-errors` prüfen. Ein MQTT-PUBACK
  bestätigt nur die Annahme durch IoT Core, nicht den Erfolg der Regelaktion.

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
Fahrerdaten. DynamoDB löscht Messwerte standardmäßig nicht automatisch; die
Aufbewahrung und Tabellenkosten bei Dauerbetrieb regelmäßig prüfen. CloudWatch-
Regelfehlerlogs werden nach 14 Tagen gelöscht. AWS-Preise können sich ändern.

Demo-Ressourcen nach Abschluss mit `terraform -chdir=terraform/amplify destroy`
entfernen. Das löscht die DynamoDB-Messwerttabelle samt Daten. Das separat
erzeugte Zertifikat danach deaktivieren und löschen:

```powershell
$certificateId = ($certificateArn -split "/")[-1]
aws iot update-certificate --certificate-id $certificateId --new-status INACTIVE
aws iot delete-certificate --certificate-id $certificateId
```

Den privaten Schlüssel lokal sicher löschen, sobald keine Sicherung mehr benötigt
wird. Verifiziere im AWS-Kosten-Explorer, dass keine Demo-Ressourcen oder laufenden
Gebühren verblieben sind.