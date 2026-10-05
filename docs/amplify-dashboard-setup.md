# Amplify-Dashboard mit Terraform einrichten

Diese Anleitung richtet das Cloud-Dashboard mit Terraform ein. Temperaturwerte
werden in DynamoDB gespeichert; Timestream wird nicht verwendet. Terraform
erstellt die AWS-Ressourcen, aber führt keine Änderungen aus, bis du selbst
`terraform apply` bestätigst.

## Voraussetzungen

- Zugriff auf ein AWS-Konto mit Rechten für Amplify, Cognito, API Gateway,
  Lambda, IAM, DynamoDB und AWS IoT Core. AWS Academy-/Lab-Konten
  können einzelne Dienste oder IAM-Rollen sperren.
- Ein Git-Repository, das Amplify über den Git-Anbieter verbinden kann.
- Region `eu-central-1` oder eine andere Region, in der alle benötigten Dienste
  verfügbar sind. Alle unten angelegten Dienste müssen dieselbe Region verwenden.
- Der Raspberry Pi ist bereits nach der
  [AWS-IoT-Anleitung](aws-iot-setup.md) mit AWS IoT verbunden. Für die neue
  Bridge werden dasselbe Gerätezertifikat und dieselben drei PEM-Dateien genutzt.
- Vor dem Anlegen die aktuellen AWS-Preise für Amplify, DynamoDB,
  API Gateway, IoT Core, Lambda und CloudWatch prüfen.

## 1. Terraform vorbereiten und prüfen

Aktiviere zuerst das passende AWS-CLI-Profil bzw. die AWS-Credentials. Lege im
Projektordner `terraform/amplify/terraform.tfvars` an. Sie wird durch
`.gitignore` von Git ausgeschlossen, aber wie gewünscht mit OneDrive
synchronisiert. Der GitHub-Token steht darin im Klartext und ist für Personen
mit Zugriff auf dieses OneDrive freigegeben.

Beschaffe die Werte so:

- **AWS Account-ID und angemeldetes Konto:** Im Projektstamm in PowerShell
   `aws sts get-caller-identity --query Account --output text` ausführen. Die
   angezeigte 12-stellige ID muss zum Konto passen, in dem Terraform deployen soll.
   Eine separate `account_id`-Variable ist nicht nötig.
- **IoT-Zertifikats-ARN:** Die ARN wird bei der Zertifikatserstellung in
   [docs/aws-iot-setup.md](aws-iot-setup.md) ausgegeben. Bei einem bestehenden
   Zertifikat findest/kopierst du sie in **AWS IoT Core → Security → Certificates**.
   Die ARN enthält die Account-ID.
- **Git-Repository-URL:** Im Projektstamm `git remote get-url origin` ausführen.
   Verwende die HTTPS-URL ohne eingebettete Zugangsdaten, etwa
   `https://github.com/OWNER/REPOSITORY.git`.

### AWS Amplify GitHub App installieren

1. Melde dich auf GitHub mit einem Konto an, das das Repository verwalten darf.
2. Öffne die Installationsseite für die konfigurierte AWS-Region. Für
   `eu-central-1` ist das:
   <https://github.com/apps/aws-amplify-eu-central-1/installations/new>
   Für eine andere Region ersetze `eu-central-1` im Link durch den Wert von
   `aws_region`.
3. Wähle den GitHub-Account bzw. die Organisation, der/die das Repo besitzt.
4. **Only select repositories** wählen und nur das MobileFrost-Repository
   freigeben. Danach **Install & Authorize** bestätigen.
5. Falls das Repository einer Organisation gehört und du keine Adminrechte hast,
   muss ein Organisations-Admin die Installation genehmigen.

### GitHub Personal Access Token erzeugen

1. In GitHub **Settings → Developer settings → Personal access tokens → Tokens
   (classic) → Generate new token** öffnen.
2. Eine Ablaufzeit setzen und den Scope `admin:repo_hook` wählen. Dieser Token
   wird für den Amplify-Webhook benötigt.
3. Token erzeugen und direkt in `amplify_repository_access_token` in
   `terraform.tfvars` eintragen. GitHub zeigt den Wert später nicht erneut an.

```hcl
aws_region                      = "eu-central-1"
project_name                    = "mobilefrost"
environment                     = "demo"
device_id                       = "mobilefrost"
device_certificate_arn          = "REPLACE_WITH_DEVICE_CERTIFICATE_ARN"
amplify_repository_url          = "https://github.com/OWNER/REPOSITORY.git"
amplify_repository_access_token = "REPLACE_WITH_GITHUB_TOKEN"
amplify_branch_name             = "main"
```

Ersetze die Werte so:

| Variable im Beispiel | Was eintragen | Woher bekommst du es? |
| --- | --- | --- |
| `aws_region` | AWS-Region, z. B. `eu-central-1` | AWS-Konsole oben rechts; dieselbe Region für alle Ressourcen verwenden. Der Beispielwert kann bleiben. |
| `project_name` | Namenspräfix, `mobilefrost` | Kann so bleiben. |
| `environment` | Umgebung, z. B. `demo` | Kann so bleiben. |
| `device_id` | IoT-Thing-Name, `mobilefrost` | Muss mit `AWS_IOT_THING_NAME` auf dem Pi übereinstimmen; kann so bleiben. |
| `device_certificate_arn` | Ganze ARN statt `REPLACE_WITH_DEVICE_CERTIFICATE_ARN` | Ausgabe von `aws iot create-keys-and-certificate` oder AWS IoT Core → Security → Certificates → Zertifikat → ARN. Die ARN enthält Region, 12-stellige Account-ID und Certificate-ID. |
| `amplify_repository_url` | HTTPS-URL statt `OWNER/REPOSITORY` | `git remote get-url origin`; falls die Ausgabe mit `git@github.com:` beginnt, die HTTPS-Form `https://github.com/OWNER/REPOSITORY.git` verwenden. |
| `amplify_repository_access_token` | GitHub-PAT statt `REPLACE_WITH_GITHUB_TOKEN` | In GitHub erzeugen, siehe GitHub-Token-Schritt oben. Den Token vollständig zwischen die Anführungszeichen setzen. |
| `amplify_branch_name` | Git-Branch, meist `main` | Branchname im Repository. Der Beispielwert kann bleiben, wenn dein Branch `main` heißt. |

Die Account-ID musst du nicht separat eintragen. Prüfe, dass Terraform beim Planen
mit dem richtigen AWS-Konto verbunden ist:

```powershell
aws sts get-caller-identity --query Account --output text
```

Der Token wird über OneDrive synchronisiert und ist für Personen mit Zugriff auf
dieses OneDrive lesbar. Terraform-State ebenfalls nicht öffentlich speichern.

Im Projektstamm:

```powershell
terraform -chdir=terraform/amplify init
terraform -chdir=terraform/amplify fmt -check
terraform -chdir=terraform/amplify validate
terraform -chdir=terraform/amplify plan
```

Prüfe im Plan Region, IAM-Rechte, Ressourcen und Kosten. Erst wenn der Plan
erwartet aussieht, `terraform -chdir=terraform/amplify apply` ausführen. Die
Bestätigung gibst du selbst ein; `apply` nicht starten, wenn du den Plan nicht
vollständig geprüft hast.

Terraform erstellt Amplify, Cognito, API Gateway, Lambda, DynamoDB, AWS-IoT-
Regeln, Rollen und Policies. Die Amplify-App hängt am Branch `main` und verwendet
die Repository-`amplify.yml` mit `frontend` als Monorepo-App-Root.

## 2. Cognito-Nutzer einladen

Terraform erstellt den User Pool mit E-Mail-Anmeldung und deaktivierter
Selbstregistrierung. Der Web-App-Client hat kein Client-Secret und verwendet
SRP plus Refresh Token. Nach erfolgreichem Apply in **Cognito → User pools →
mobilefrost-demo-users → Users → Create user** die gewünschten Personen
einladen. Die App unterstützt beim ersten Login das Setzen eines neuen Passworts.

Wichtige Werte findest du anschließend mit:

```powershell
terraform -chdir=terraform/amplify output
```

Die Outputs enthalten Amplify-URL, API-URL, Cognito User Pool/Client IDs,
IoT-Endpunkt und Namen der DynamoDB-Tabellen.

## 3. DynamoDB

Terraform legt zwei DynamoDB-Tabellen mit On-demand-Abrechnung und
serverseitiger Verschlüsselung an.

### Operations-Tabelle

| Einstellung | Wert |
| --- | --- |
| Tabellenname | `mobilefrost-demo-operations` |
| Partition key | `pk`, Typ `String` |
| Sort key | `sk`, Typ `String` |
| Kapazität | On-demand |
| Verschlüsselung | AWS-owned key aktiviert |
| Point-in-time recovery | Deaktiviert |

Die Operations-Tabelle speichert Fahrt-Sitzungen und Aktorbefehle.

### Messwert-Tabelle

| Einstellung | Wert |
| --- | --- |
| Tabellenname | `mobilefrost-demo-readings` |
| Partition key | `sensor_id`, Typ `String` |
| Sort key | `timestamp`, Typ `String` |
| Kapazität | On-demand |
| Verschlüsselung | AWS-owned key aktiviert |
| Point-in-time recovery | Deaktiviert |

AWS IoT speichert den Cloud-Payload direkt als DynamoDB-Item. Der vorhandene
Payload enthält `sensor_id` und `timestamp` auf der obersten JSON-Ebene; der
UTC-ISO-Zeitstempel wird für sortierte Zeitbereichsabfragen verwendet.

## 4. Lambda-Funktionen

Terraform paketiert den Quellcode aus `src/` und erstellt beide Funktionen mit
Runtime **Python 3.12**, Handler und den unten aufgeführten Umgebungsvariablen.
Die ZIP-Datei wird innerhalb des Terraform-Arbeitsordners in `.terraform/`
erstellt und nicht manuell in der Konsole hochgeladen. Die Funktionen verwenden
das in der Lambda-Runtime enthaltene `boto3`.

### API-Funktion

| Einstellung | Wert |
| --- | --- |
| Name | `mobilefrost-demo-api` |
| Handler | `mobilefrost.cloud_api.lambda_handler` |
| Timeout | 15 Sekunden |
| Arbeitsspeicher | 256 MB |

Terraform setzt diese Umgebungsvariablen:

| Name | Beispielwert |
| --- | --- |
| `READINGS_TABLE` | `mobilefrost-demo-readings` |
| `OPERATIONS_TABLE` | `mobilefrost-demo-operations` |
| `DEVICE_ID` | `mobilefrost` |
| `AWS_IOT_DATA_ENDPOINT` | IoT-Data-HTTPS-Hostname ohne `https://` |

Diese Werte kommen in **Lambda → Configuration → Environment variables** der
API-Funktion. `AWS_IOT_DATA_ENDPOINT` ist kein Amplify-Wert.
Den IoT-Endpunkt findest du unter **AWS IoT Core → Settings → Device data
endpoint**. Beispiel: `abcd123456-ats.iot.eu-central-1.amazonaws.com`.

### API-Lambda-Rolle

Terraform erstellt die API-Rolle mit `AWSLambdaBasicExecutionRole` für
CloudWatch Logs sowie folgenden eng begrenzten Rechten:

- DynamoDB: `Query` auf `mobilefrost-demo-readings`.
- DynamoDB: `GetItem`, `PutItem`, `UpdateItem`, `DeleteItem` und
   `TransactWriteItems` auf `mobilefrost-demo-operations`.
- IoT: `iot:Publish` nur auf
  `arn:aws:iot:<REGION>:<ACCOUNT_ID>:topic/mobilefrost/commands/mobilefrost/actuators/*`.

Zum manuellen Testen im Lambda-Tab **Test** ein neues Testevent mit diesem
API-Gateway-v2-Format anlegen. Es fragt den Fahrtstatus aus DynamoDB ab und
prüft Handler, Rolle und Tabellennamen, ohne einen Aktor zu bewegen:

```json
{
   "version": "2.0",
   "routeKey": "GET /api/drive",
   "rawPath": "/api/drive",
   "requestContext": {
      "authorizer": {
         "jwt": {
            "claims": { "sub": "lambda-console-test" }
         }
      }
   }
}
```

Erwartet wird HTTP-Status `200` mit `{"active":null}`, sofern keine Fahrt läuft.
Ein `401` weist auf fehlende Test-Claims hin; ein `503` meist auf fehlende
Umgebungsvariablen oder DynamoDB-Rechte.

### Bestätigungs-Lambda

| Einstellung | Wert |
| --- | --- |
| Name | `mobilefrost-demo-ack` |
| Handler | `mobilefrost.cloud_ack.lambda_handler` |
| Timeout | 10 Sekunden |
| Arbeitsspeicher | 128 MB |

Terraform setzt `OPERATIONS_TABLE=mobilefrost-demo-operations` und
`DEVICE_ID=mobilefrost` und weist der separaten Ack-Rolle
`dynamodb:UpdateItem` nur auf der Operations-Tabelle zu. Die Funktion wird von
der IoT-Regel aufgerufen; private Geräteschlüssel gehören nicht in Lambda.

## 5. API Gateway mit Cognito-JWT

Terraform erstellt die HTTP API mit Lambda-Proxy-Integration, Cognito-JWT-
Authorizer, `$default`-Stage, API-Aufrufberechtigung und CORS. Alle folgenden
Routen sind geschützt:

| Methode | Route |
| --- | --- |
| GET | `/api/temperatures` |
| GET | `/api/drive` |
| POST | `/api/drive/start` |
| POST | `/api/drive/stop` |
| POST | `/api/actuators/fan` |
| POST | `/api/actuators/flap` |
| GET | `/api/commands/{request_id}` |

Die Route-Namen müssen exakt sein, weil der Lambda-Handler API-Gateway-v2-
`routeKey` auswertet. Die API-URL steht nach dem Apply im Terraform-Output
`api_url`; CORS erlaubt nur die konfigurierte Amplify-Branch-Origin.

## 6. AWS IoT Topics und Regeln

### Gerätezertifikat-Policy

Terraform erstellt und bindet die IoT-Policy an die in `device_certificate_arn`
angegebene Zertifikats-ARN. Sie ist auf folgende Aktionen und Ressourcen
beschränkt; keine Rechte auf `topic/*` oder `iot:*` vergeben.

| Aktion | Ressource |
| --- | --- |
| `iot:Connect` | `arn:aws:iot:<REGION>:<ACCOUNT_ID>:client/mobilefrost` und `...:client/mobilefrost-bridge` |
| `iot:Publish` | `...:topic/mobilefrost/cloud/temperatures/*` |
| `iot:Publish` | `...:topic/mobilefrost/device/status/mobilefrost/commands` |
| `iot:Subscribe` | `...:topicfilter/mobilefrost/commands/mobilefrost/actuators/*` |
| `iot:Receive` | `...:topic/mobilefrost/commands/mobilefrost/actuators/*` |

Die bestehende Cloud-Sync-Verbindung nutzt Client-ID `mobilefrost`; die neue
Bridge nutzt `mobilefrost-bridge`. Terraform erlaubt beide Client-IDs.

### Temperatur-Regel nach DynamoDB

Terraform legt eine aktivierte DynamoDBv2-Regel mit SQL-Version `2016-03-23` an:

```sql
SELECT * FROM 'mobilefrost/cloud/temperatures/+'
```

Die DynamoDBv2-Aktion schreibt den gesamten JSON-Payload in
`mobilefrost-demo-readings`. Die IoT-Regelrolle erhält nur `dynamodb:PutItem` auf
diese Tabelle. Der Payload muss die Primärschlüssel `sensor_id` und `timestamp`
enthalten; diese sind im aktuellen Cloud-Sync-Payload bereits vorhanden.

### Command-Acknowledgement-Regel

Terraform erstellt eine zweite IoT-Regel für das Topic
`mobilefrost/device/status/mobilefrost/commands` mit SQL:

```sql
SELECT * FROM 'mobilefrost/device/status/mobilefrost/commands'
```

Die Regel ruft die Funktion `mobilefrost-demo-ack` auf. Terraform beschränkt die
Lambda-Aufrufberechtigung auf genau diese Regel; die Ack-Lambda-Rolle benötigt
keine IoT-Rechte.

## 7. Amplify-Variablen und Deploy

Terraform setzt diese Buildvariablen am Amplify-Branch aus den erstellten
Ressourcen:

| Variable | Wert |
| --- | --- |
| `VITE_API_URL` | API-URL aus Abschnitt 5, ohne abschließenden `/` |
| `VITE_AWS_REGION` | verwendete AWS-Region, z. B. `eu-central-1` |
| `VITE_COGNITO_USER_POOL_ID` | Cognito User Pool ID |
| `VITE_COGNITO_USER_POOL_CLIENT_ID` | Cognito Web-Client-ID ohne Secret |

Terraform setzt `AWS_IOT_DATA_ENDPOINT` nur in der API-Lambda-Umgebung;
`AWS_IOT_ENDPOINT` bleibt in der `.env` auf dem Pi. AWS Access Keys,
Cognito-Client-Secrets und IoT-Zertifikate gehören nicht in Frontend-Variablen.
Nach `apply` startet Amplify den Branch-Build. Danach im Cognito User Pool einen
Nutzer administrativ einladen und mit diesem anmelden.

## 8. Raspberry Pi starten und prüfen

Auf dem Pi die drei vorhandenen Zertifikatsdateien in `secrets/` belassen, `.env`
mit `AWS_IOT_ENDPOINT` und `AWS_IOT_THING_NAME=mobilefrost` konfigurieren und den
Cloud-Service starten:

```bash
podman compose --profile cloud up -d --build cloud_sync aws_bridge
podman compose logs --tail=100 cloud_sync aws_bridge
```

Prüfreihenfolge:

1. Ohne Cognito-Anmeldung liefern alle API-Routen einen Authorizer-Fehler.
2. Nach Anmeldung zeigt das Dashboard Messwerte und den Verlauf aus DynamoDB.
3. Fahrt starten und beenden; in DynamoDB entstehen eine Session und ein
   aktiver Session-Zeiger, der beim Beenden entfernt wird.
4. Lüfter oder Klappe einstellen. Die UI zeigt zunächst „wird übertragen“ und
   meldet Erfolg erst nach der IoT-Acknowledgement-Regel.
5. Das Ack bestätigt die Weiterleitung durch die Pi-Bridge an lokales Mosquitto,
   nicht die physische Lüfterdrehzahl oder Servoposition. Die Temperatur-
   Automatik kann den manuellen Sollwert beim nächsten Messwert überschreiben.
6. Internet/AWS kurz trennen: lokale Sensorik, Datenbank und automatische
   Regelung müssen weiterarbeiten. Cloud-Steuerung bleibt offline.

## 9. Kosten und Aufräumen

On-demand-DynamoDB-Lese-/Schreibvorgänge und gespeicherte Messwerte, CloudWatch
Logs, IoT-Nachrichten, Lambda/API-Aufrufe und Amplify können nutzungsabhängige
Kosten verursachen. Die Messwert-Tabelle hat standardmäßig keine automatische
Ablaufzeit; bei Dauerbetrieb Datenaufbewahrung und regionale Preise prüfen.

Nach dem Test `terraform -chdir=terraform/amplify destroy` prüfen und
bestätigen. Das entfernt API Gateway, Lambda, Cognito, IoT, DynamoDB, Amplify,
CloudWatch und IAM-Ressourcen. Das Löschen der Messwert-Tabelle löscht auch die
Cloud-Historie.
Das IoT-Zertifikat anschließend deaktivieren und löschen, falls es nicht mehr
benötigt wird. Den Pi-Stack separat stoppen:

```bash
podman compose --profile cloud stop cloud_sync aws_bridge
```