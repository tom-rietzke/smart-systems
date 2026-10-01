# Amplify-Dashboard manuell einrichten

Diese Anleitung richtet das Cloud-Dashboard vollständig über die AWS-Konsole ein.
Terraform ist dafür nicht erforderlich. Die AWS-Ressourcen werden nicht aus dem
Repository automatisch erstellt; sie müssen im gewählten AWS-Konto angelegt und
später dort wieder gelöscht werden.

## Voraussetzungen

- Zugriff auf ein AWS-Konto mit Rechten für Amplify, Cognito, API Gateway,
  Lambda, IAM, DynamoDB, Timestream und AWS IoT Core. AWS Academy-/Lab-Konten
  können einzelne Dienste oder IAM-Rollen sperren.
- Ein Git-Repository, das Amplify über den Git-Anbieter verbinden kann.
- Region `eu-central-1` oder eine andere Region, in der alle benötigten Dienste
  verfügbar sind. Alle unten angelegten Dienste müssen dieselbe Region verwenden.
- Der Raspberry Pi ist bereits nach der
  [AWS-IoT-Anleitung](aws-iot-setup.md) mit AWS IoT verbunden. Für die neue
  Bridge werden dasselbe Gerätezertifikat und dieselben drei PEM-Dateien genutzt.
- Vor dem Anlegen die aktuellen AWS-Preise für Amplify, Timestream, DynamoDB,
  API Gateway, IoT Core, Lambda und CloudWatch prüfen.

## 1. Amplify Hosting verbinden

1. AWS-Konsole öffnen und in der Zielregion **AWS Amplify → Create new app**
   wählen.
2. Git-Anbieter verbinden, dieses Repository und den Branch `main` auswählen.
   Die Verbindung über den AWS-Git-Provider-Dialog autorisieren; kein Token in
   Projektdateien oder Chatnachrichten speichern.
3. **My app is a monorepo** aktivieren und als App-Root `frontend` eintragen.
   Amplify setzt `AMPLIFY_MONOREPO_APP_ROOT=frontend`.
4. Als Buildspec die Datei `amplify.yml` im Repository-Stamm verwenden. Sie
   installiert über `npm ci`, baut mit `npm run build` und veröffentlicht
   `frontend/dist`.
5. Die App zunächst erstellen. Die Oberfläche zeigt bis zur vollständigen
   Backend-Konfiguration an, dass Cloud-Login noch nicht konfiguriert ist.
6. Die erste Amplify-URL notieren. Sie hat die Form
   `https://main.<app-id>.amplifyapp.com` und wird später für CORS benötigt.

## 2. Cognito für eingeladene Nutzer

1. In derselben Region **Amazon Cognito → User pools → Create user pool** öffnen.
2. E-Mail als Anmeldenamen wählen und E-Mail-Verifizierung aktivieren.
3. Selbstregistrierung deaktivieren: Nutzer dürfen nur durch Administratoren
   angelegt werden.
4. Einen Web-App-Client für JavaScript anlegen. **Client secret nicht erzeugen**;
   der Browser darf kein Client-Secret verwenden.
5. Als erlaubte Anmeldeabläufe SRP und Refresh Token aktivieren. OAuth-Callback-
   URLs sind für den hier verwendeten direkten Amplify-Auth-Ablauf nicht nötig.
6. User Pool ID und Web-Client-ID notieren. Diese beiden Werte sind öffentliche
   Frontend-Konfiguration und keine Passwörter.
7. Nach dem Backend-Aufbau unter **Users → Create user** die gewünschten Personen
   einladen. Den temporären Zugang sicher über Cognito verteilen. Die App
   unterstützt die Aufforderung, beim ersten Login ein neues Passwort zu setzen.

## 3. DynamoDB und Timestream

### DynamoDB

Unter **Amazon DynamoDB → Tables → Create table** anlegen:

| Einstellung | Wert |
| --- | --- |
| Tabellenname | `mobilefrost-demo-operations` |
| Partition key | `pk`, Typ `String` |
| Sort key | `sk`, Typ `String` |
| Kapazität | On-demand |
| Verschlüsselung | AWS-owned key aktiviert |
| Point-in-time recovery | Aktiviert, falls im Konto verfügbar |

Weitere Attribute werden nicht vorab definiert. Fahrt- und Befehlsdatensätze
verwenden diese Tabelle.

### Timestream

1. Unter **Amazon Timestream for LiveAnalytics** die Datenbank
   `mobilefrost-demo_temperatures` und darin die Tabelle `temperature_readings`
   anlegen.
2. Retention für die Demo: Memory Store 24 Stunden, Magnetic Store 30 Tage.
   Eine kürzere oder längere Aufbewahrung ändert Kosten und Datenverfügbarkeit.
3. Datenbank- und Tabellenname für die API-Lambda notieren.

## 4. Lambda-Funktionen

Erzeuge auf dem Entwicklungsrechner das ZIP aus dem Paketverzeichnis; so liegt
`mobilefrost/` direkt im ZIP-Root, wie es Lambda benötigt:

```powershell
Push-Location src
Compress-Archive -Path .\mobilefrost -DestinationPath ..\mobilefrost-cloud.zip -Force
Pop-Location
```

Lege zwei Funktionen mit Runtime **Python 3.12** an. Lade für beide dasselbe ZIP
`mobilefrost-cloud.zip` hoch. Die Funktionen verwenden nur Python-Standardmodule
und das in der Lambda-Runtime enthaltene `boto3`.

### API-Funktion

| Einstellung | Wert |
| --- | --- |
| Name | `mobilefrost-demo-api` |
| Handler | `mobilefrost.cloud_api.lambda_handler` |
| Timeout | 15 Sekunden |
| Arbeitsspeicher | 256 MB |

Umgebungsvariablen:

| Name | Beispielwert |
| --- | --- |
| `TIMESTREAM_DATABASE` | `mobilefrost-demo_temperatures` |
| `TIMESTREAM_TABLE` | `temperature_readings` |
| `OPERATIONS_TABLE` | `mobilefrost-demo-operations` |
| `DEVICE_ID` | `mobilefrost` |
| `AWS_IOT_DATA_ENDPOINT` | IoT-Data-HTTPS-Hostname ohne `https://` |

Den IoT-Endpunkt findest du unter **AWS IoT Core → Settings → Device data
endpoint**. Beispiel: `abcd123456-ats.iot.eu-central-1.amazonaws.com`.

### API-Lambda-Rolle

Die Rolle braucht `AWSLambdaBasicExecutionRole` für CloudWatch Logs und folgende
zusätzliche Rechte, jeweils nur auf die oben angelegte Tabelle bzw. die
Geräte-Topics beschränkt:

- Timestream: `timestream:Select` auf die Tabelle und
  `timestream:DescribeEndpoints` auf `*`.
- DynamoDB: `GetItem`, `PutItem`, `UpdateItem`, `DeleteItem` und
  `TransactWriteItems` auf `mobilefrost-demo-operations`.
- IoT: `iot:Publish` nur auf
  `arn:aws:iot:<REGION>:<ACCOUNT_ID>:topic/mobilefrost/commands/mobilefrost/actuators/*`.

### Bestätigungs-Lambda

| Einstellung | Wert |
| --- | --- |
| Name | `mobilefrost-demo-ack` |
| Handler | `mobilefrost.cloud_ack.lambda_handler` |
| Timeout | 10 Sekunden |
| Arbeitsspeicher | 128 MB |

Umgebungsvariablen: `OPERATIONS_TABLE=mobilefrost-demo-operations` und
`DEVICE_ID=mobilefrost`. Die Ausführungsrolle braucht `AWSLambdaBasicExecutionRole`
und `dynamodb:UpdateItem` nur auf die Operations-Tabelle.

## 5. API Gateway mit Cognito-JWT

1. **API Gateway → Create API → HTTP API** wählen.
2. Eine Lambda-Proxy-Integration zur Funktion `mobilefrost-demo-api` einrichten.
   In der Lambda-Funktionsberechtigung API Gateway als Aufrufer zulassen und
   den Zugriff auf diese HTTP API beschränken.
3. Einen JWT-Authorizer anlegen:
   - Identity source: `$request.header.Authorization`
   - Issuer:
     `https://cognito-idp.<REGION>.amazonaws.com/<USER_POOL_ID>`
   - Audience: die notierte Cognito-Web-Client-ID.
4. Diese Routen einzeln anlegen und für jede Route den JWT-Authorizer als
   Authorization konfigurieren:

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
`routeKey` auswertet. Keine ungeschützte `$default`-Route anlegen.

5. Eine `$default`-Stage mit Auto-deploy aktivieren und die API-URL notieren,
   zum Beispiel `https://<api-id>.execute-api.<REGION>.amazonaws.com`.
6. Unter CORS als erlaubte Origin ausschließlich die echte Amplify-Branch-URL
   eintragen. Methoden `GET`, `POST`, `OPTIONS`; Header `authorization` und
   `content-type`. Kein Wildcard-Origin.

## 6. AWS IoT Topics und Regeln

### Gerätezertifikat-Policy

Das bereits auf dem Pi liegende Zertifikat muss mit einer IoT-Policy verbunden
sein, die folgende Aktionen und Ressourcen zulässt. Ersetze `<REGION>` und
`<ACCOUNT_ID>` durch die tatsächlichen Werte; keine Rechte auf `topic/*` oder
`iot:*` vergeben.

| Aktion | Ressource |
| --- | --- |
| `iot:Connect` | `arn:aws:iot:<REGION>:<ACCOUNT_ID>:client/mobilefrost` und `...:client/mobilefrost-bridge` |
| `iot:Publish` | `...:topic/mobilefrost/cloud/temperatures/*` |
| `iot:Publish` | `...:topic/mobilefrost/device/status/mobilefrost/commands` |
| `iot:Subscribe` | `...:topicfilter/mobilefrost/commands/mobilefrost/actuators/*` |
| `iot:Receive` | `...:topic/mobilefrost/commands/mobilefrost/actuators/*` |

Die bestehende Cloud-Sync-Verbindung nutzt Client-ID `mobilefrost`; die neue
Bridge nutzt `mobilefrost-bridge`. Beide Verbindungen müssen explizit erlaubt
sein.

### Temperatur-Regel nach Timestream

1. In **AWS IoT Core → Message routing → Rules** eine aktivierte Regel anlegen.
2. SQL-Version `2016-03-23`, SQL:

```sql
SELECT sensor_id, CAST(value AS DOUBLE) AS temperature_c
FROM 'mobilefrost/cloud/temperatures/+'
```

3. Als Aktion **Timestream** auswählen, Datenbank und Tabelle aus Abschnitt 3
   setzen und Dimension `sensor_id` mit dem Substitution Template `${sensor_id}`
   anlegen.
4. Zeitstempel auf `${epoch_ms}` mit Einheit `MILLISECONDS` setzen. Das ist der
   originale Messzeitpunkt aus dem bestehenden Outbox-Payload.
5. Der IoT-Regelrolle `timestream:WriteRecords` nur auf dieser Tabelle und
   `timestream:DescribeEndpoints` auf `*` erlauben.
6. Optional einen CloudWatch-Logs-Fehlerpfad mit 14 Tagen Aufbewahrung
   konfigurieren, damit fehlgeschlagene Timestream-Regelaktionen sichtbar sind.

### Command-Acknowledgement-Regel

1. Eine zweite IoT-Regel für das Topic
   `mobilefrost/device/status/mobilefrost/commands` anlegen; SQL:

```sql
SELECT * FROM 'mobilefrost/device/status/mobilefrost/commands'
```

2. Als Aktion die Lambda-Funktion `mobilefrost-demo-ack` auswählen.
3. Die IoT-Regelberechtigung zum Aufruf genau dieser Lambda-Funktion hinzufügen.
   Die Ack-Lambda-Rolle benötigt keine IoT-Rechte.

## 7. Amplify-Variablen setzen und deployen

Unter **Amplify → App settings → Environment variables** für den Branch `main`
folgende Werte setzen:

| Variable | Wert |
| --- | --- |
| `VITE_API_URL` | API-URL aus Abschnitt 5, ohne abschließenden `/` |
| `VITE_AWS_REGION` | verwendete AWS-Region, z. B. `eu-central-1` |
| `VITE_COGNITO_USER_POOL_ID` | Cognito User Pool ID |
| `VITE_COGNITO_USER_POOL_CLIENT_ID` | Cognito Web-Client-ID ohne Secret |

Das sind nicht geheime Build-Konfigurationen. Niemals AWS Access Keys,
Cognito-Client-Secrets oder IoT-Zertifikate als Frontend-Variablen eintragen.
Nach dem Speichern einen neuen Amplify-Build auslösen. Danach einen Cognito-
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
2. Nach Anmeldung zeigt das Dashboard Messwerte und den Verlauf aus Timestream.
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

Timestream, CloudWatch Logs, IoT-Nachrichten, Lambda/API-Aufrufe und Amplify
können laufende oder nutzungsabhängige Kosten verursachen. Vor längerer Nutzung
Aufbewahrung und regionale Preise prüfen.

Nach dem Test zuerst in Amplify den Branch/die App löschen, dann API Gateway,
Lambda, Cognito-Nutzerpool, IoT-Regeln/Policy-Zuordnungen, DynamoDB-Tabelle,
Timestream-Tabelle/Datenbank, CloudWatch-Ressourcen und zugehörige IAM-Rollen
entfernen. Das Löschen der Timestream-Datenbank löscht auch die Cloud-Historie.
Das IoT-Zertifikat anschließend deaktivieren und löschen, falls es nicht mehr
benötigt wird. Den Pi-Stack separat stoppen:

```bash
podman compose --profile cloud stop cloud_sync aws_bridge
```