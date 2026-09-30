# AWS IoT Cloud Implementation Plan

> **For agentic workers:** Execute the tasks in order. Steps use checkbox (`- [ ]`) syntax. Do not commit changes unless the user explicitly requests a commit.

**Goal:** Persist MobileFrost temperature readings in AWS IoT Core and Timestream while preserving reliable local operation during cloud outages.

**Architecture:** A PostgreSQL outbox is written atomically with each local temperature record. An opt-in Compose worker publishes pending events to AWS IoT Core over TLS/MQTT QoS 1 and marks them accepted after broker acknowledgement; a failed downstream Timestream rule is logged to CloudWatch. Terraform provisions IoT Core routing, Timestream, and error logging; the device private key is created/downloaded separately and is never stored in Terraform state.

**Tech Stack:** Python 3.9+, PostgreSQL/psycopg2, existing paho-mqtt 2.x, Podman Compose, Terraform AWS provider, AWS IoT Core, Amazon Timestream for LiveAnalytics.

## Global Constraints

- Keep the existing local controller, PostgreSQL history, Mosquitto topics, dashboard, and actuator behavior working when AWS is unavailable.
- Publish cloud temperatures over MQTT/TLS with QoS 1 on `mobilefrost/cloud/temperatures/<sensor_id>`.
- Keep each outbox row pending until the publish is acknowledged; retry on later worker iterations.
- Accept possible QoS 1 redelivery after a crash; use the stable outbox ID for traceability and Timestream's sensor/measure/source-time identity to avoid duplicate measurements.
- Never store or commit a device private key, AWS access key, or secret in Terraform state or repository files.
- Use AWS region `eu-central-1` by default and allow configuration.
- Run tests with `python -m unittest discover -s tests -v`; do not commit unless explicitly requested.

---

## File Structure

- Modify `src/mobilefrost/database.py`: create the outbox table, enqueue in the same transaction as local readings, select pending readings, and mark acknowledged rows.
- Create `src/mobilefrost/cloud_sync.py`: serialize readings, publish via an injectable TLS MQTT client, drain a bounded batch, and provide the worker entry point.
- Modify `compose.yml`: add an opt-in cloud-sync service with DB/AWS settings and read-only device certificate mounts.
- Create `terraform/aws_iot/main.tf`: define variables, IoT Thing/policy, Timestream database/table, IoT rule, least-privilege roles, and CloudWatch error logging.
- Modify `.gitignore`: exclude Terraform state, local variable files, downloaded certificates, private keys, and cloud secrets.
- Create `docs/aws-iot-setup.md`: explain prerequisites, Terraform deployment, certificate creation/attachment, Compose startup, verification, costs, and cleanup.
- Modify `README.md`: link the cloud setup guide and describe the cloud data flow.
- Modify `tests/test_app.py`: add focused unit tests using the existing `unittest` and recording test doubles.

## Task 1: Durable Local Outbox

**Files:**
- Modify: `tests/test_app.py`
- Modify: `src/mobilefrost/database.py`

**Interfaces:**
- Keep `store_temperature(cursor, connection, sensor_id, temperature) -> bool` compatible with the controller.
- Add `fetch_pending_cloud_readings(cursor, limit=100) -> list[tuple]`, returning `(outbox_id, sensor_id, value, timestamp)` ordered oldest first.
- Add `mark_cloud_reading_published(cursor, connection, outbox_id) -> bool`.

- [ ] **Step 1: Add an atomic-enqueue test.** Extend `RecordingCursor` to record SQL as well as parameters and return `(temperature_id, timestamp)` for the temperature insert. Add `test_stores_temperature_and_enqueues_cloud_outbox_atomically`; verify a successful call executes the temperature insert and outbox insert before one commit.
- [ ] **Step 2: Run the focused test and verify it fails.** Run `python -m unittest tests.test_app.TemperatureSensorTests.test_stores_temperature_and_enqueues_cloud_outbox_atomically -v`. Expected: the new assertion sees only the existing temperature insert.
- [ ] **Step 3: Add the outbox schema and transactional insert.** In `init_db`, create `cloud_outbox(id SERIAL PRIMARY KEY, temperature_id INTEGER NOT NULL UNIQUE REFERENCES temperatures(id), published_at TIMESTAMP NULL)`. Change the temperature insert to `RETURNING id, timestamp`, then insert that ID into `cloud_outbox` before committing. On either SQL failure, roll back both inserts and return `False`.
- [ ] **Step 4: Add tests for pending selection and acknowledgement.** Verify pending reads join `cloud_outbox` to `temperatures`, sort by timestamp then outbox ID, honor the requested limit, and that marking an ID updates only that row and commits.
- [ ] **Step 5: Implement the pending/mark helpers and run focused tests.** Run `python -m unittest tests.test_app.TemperatureSensorTests -v`. Expected: all database helper tests pass, including the existing rollback case.

## Task 2: Cloud Event Contract and TLS Publisher

**Files:**
- Modify: `tests/test_app.py`
- Create: `src/mobilefrost/cloud_sync.py`

**Interfaces:**
- Add `format_cloud_payload(outbox_id, sensor_id, value, timestamp) -> str`.
- Add `CloudMqttPublisher(client, endpoint, thing_name, certificate_path, private_key_path, root_ca_path)` with `connect()` and `publish(sensor_id, payload) -> bool` methods.
- Add `build_cloud_publisher(...)` to construct the Paho client from environment configuration and wrap it in `CloudMqttPublisher`.
- `connect()` uses AWS IoT Core port `443`, TLS certificate authentication with ALPN `x-amzn-mqtt-ca`, and the Thing name as MQTT client ID. `publish()` sends to `mobilefrost/cloud/temperatures/<sensor_id>` with QoS `1` and returns true only after AWS IoT Core acknowledges the message; this does not guarantee the downstream Timestream rule succeeded.

- [ ] **Step 1: Test the serialized event contract.** Assert compact JSON includes `event_id`, `sensor_id`, numeric `value`, an ISO-8601 UTC `timestamp`, and integer `epoch_ms`. A naive database timestamp must be treated as UTC, matching the existing dashboard convention.
- [ ] **Step 2: Run the contract test and verify it fails.** Run `python -m unittest tests.test_app.CloudSyncTests.test_formats_cloud_payload_with_utc_epoch -v`. Expected: missing `mobilefrost.cloud_sync` module.
- [ ] **Step 3: Implement payload serialization.** Normalize aware timestamps to UTC, attach UTC to naive timestamps, compute epoch milliseconds from that UTC instant, and serialize with compact separators.
- [ ] **Step 4: Test TLS and QoS configuration with a recording client.** Extend `RecordingMqttClient` or add a dedicated fake implementing `tls_set_context`, `connect`, and an acknowledged publish result. Verify the builder applies CA/certificate/key paths, configures ALPN `x-amzn-mqtt-ca`, sets a stable Thing-based client ID, connects to the endpoint on port `443`, and publishes with QoS `1`. Verify a timeout or unsuccessful publish acknowledgement returns `False`.
- [ ] **Step 5: Implement the publisher and run its tests.** Use the existing Paho dependency. Keep client construction injectable so unit tests require no AWS account or network. Run `python -m unittest tests.test_app.CloudSyncTests -v`.

## Task 3: Retryable Batch Sync Worker

**Files:**
- Modify: `tests/test_app.py`
- Modify: `src/mobilefrost/cloud_sync.py`

**Interfaces:**
- Add `sync_once(cursor, connection, publisher, batch_size=100) -> int`, returning the number of acknowledged rows marked delivered.
- Add `cloud_configuration_from_env()` and `main()` for the standalone Compose service.

- [ ] **Step 1: Test one successful batch.** Provide two pending rows and a publisher that acknowledges both; assert each payload is published, both rows are marked delivered, and the return value is `2`.
- [ ] **Step 2: Test failure preserves pending data.** Have the publisher fail on the second event; assert the first row is marked delivered, the second remains pending, and later events in that batch are not marked delivered.
- [ ] **Step 3: Run the sync tests and verify the expected failures.** Run `python -m unittest tests.test_app.CloudSyncTests.test_sync_once_marks_only_acknowledged_rows -v`. Expected: missing `sync_once` implementation.
- [ ] **Step 4: Implement the bounded sync cycle.** Fetch at most `batch_size` rows in chronological order; serialize and publish one at a time; mark each row only after positive acknowledgement; stop at first failed publish so retry order remains predictable.
- [ ] **Step 5: Add an environment-driven worker entry point.** Require `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `AWS_IOT_ENDPOINT`, `AWS_IOT_THING_NAME`, `AWS_IOT_CERTIFICATE_PATH`, `AWS_IOT_PRIVATE_KEY_PATH`, and `AWS_IOT_ROOT_CA_PATH`. Connect to PostgreSQL, initialize schema, connect the MQTT client with TLS, call `sync_once` repeatedly, and wait briefly when there is no work or after a recoverable error. Log IDs/counts and error categories, never credential contents.
- [ ] **Step 6: Run the complete focused test class.** Run `python -m unittest tests.test_app.CloudSyncTests -v`; verify failed publishing leaves rows available for a later cycle.

## Task 4: Terraform AWS Resources

**Files:**
- Create: `terraform/aws_iot/main.tf`
- Modify: `.gitignore`

**Resources and inputs:**
- Variables: `aws_region` defaulting to `eu-central-1`, `project_name` defaulting to `mobilefrost`, and `device_certificate_arn` defaulting to empty for the initial apply.
- Resources: AWS provider, IoT Thing, IoT publish policy, optional certificate-to-Thing and certificate-to-policy attachments, Timestream database/table, IoT rule, least-privilege Timestream writer role/policy, and a CloudWatch log group plus least-privilege rule-error role/policy.
- Outputs: IoT data ATS endpoint, Thing name, cloud topic, database name, and table name.

- [ ] **Step 1: Add ignore rules before generating local infrastructure artifacts.** Ignore `terraform.tfstate*`, `.terraform/`, `*.tfvars`, `terraform/aws_iot/certs/`, `*.pem`, `*.key`, and local `.env` files. Keep provider lock files versioned if Terraform generates one.
- [ ] **Step 2: Add Terraform resources with exact routing.** The IoT policy may publish only to `mobilefrost/cloud/temperatures/*`. The IoT rule selects only `value AS temperature_c`, writes `sensor_id` as the Timestream dimension, and uses `epoch_ms` as a `MILLISECONDS` timestamp; the SELECT alias becomes the Timestream measure name. Add a 14-day CloudWatch log group and an error action for failed rule writes. Scope both IAM roles to the single table or log group they need.
- [ ] **Step 3: Validate formatting and configuration.** Run `terraform -chdir=terraform/aws_iot fmt -check` and `terraform -chdir=terraform/aws_iot validate`. If Terraform is unavailable, report that and still inspect `terraform fmt`/HCL validity before claiming validation.
- [ ] **Step 4: Review the plan without applying it.** Run `terraform -chdir=terraform/aws_iot plan` only after local AWS profile configuration is available. Do not apply resources automatically; the user must run the documented apply when ready.

## Task 5: Compose and AWS Setup Guide

**Files:**
- Modify: `compose.yml`
- Create: `docs/aws-iot-setup.md`
- Modify: `README.md`

- [ ] **Step 1: Add an opt-in Compose service.** Define `cloud_sync` under profile `cloud`; reuse the application image and PostgreSQL environment, set all AWS IoT values through environment variables, and mount a host `./secrets` directory read-only at `/run/secrets/aws-iot`. Use container paths for certificate, private key, and Amazon Root CA; do not put credentials directly in Compose.
- [ ] **Step 2: Document local prerequisites and Terraform deployment.** Explain AWS CLI profile setup, Terraform installation, `terraform init`, creation of a local `terraform.tfvars` with region/project name, review of `terraform plan`, and user-run `terraform apply`. Explain every created resource and which AWS costs it can incur.
- [ ] **Step 3: Document certificate creation without exposing the key.** Provide both PowerShell and Linux shell commands for `aws iot create-keys-and-certificate --set-as-active` with output files for certificate/private key/public key. Save only the returned certificate ARN into ignored `terraform.tfvars`, then run a second `terraform apply` so Terraform attaches the certificate to the Thing and policy. Download the Amazon Root CA to `secrets/`; never display or commit the private key. Explain secure transfer of the private key to the Raspberry Pi and Linux file mode `600` before starting Compose.
- [ ] **Step 4: Document Compose startup and live verification.** Retrieve the IoT ATS endpoint from Terraform outputs, set endpoint and container file paths, then run `podman compose --profile cloud up -d cloud_sync`. Use AWS IoT MQTT test client subscribed to `mobilefrost/cloud/temperatures/#`; confirm a published event arrives and its row appears in Timestream. Explain that the sync container can start while the worker waits for pending local samples, that PUBACK is not a Timestream confirmation, and that rule failures appear in CloudWatch.
- [ ] **Step 5: Document offline behavior and cleanup.** Explain that cloud failures leave outbox rows pending while local sensing/control/storage continue. Explain that `terraform destroy` deletes cloud demo resources/data and detaches the certificate; afterward deactivate and delete the separately created certificate with AWS CLI. State that Timestream retention and current regional pricing must be reviewed before running continuously.
- [ ] **Step 6: Update README architecture and setup links.** Add the opt-in cloud flow to the architecture description and link `docs/aws-iot-setup.md`; preserve all existing local setup instructions.

## Task 6: Integration Verification

**Files:**
- Test: `tests/test_app.py`
- Verify: `compose.yml`, `terraform/aws_iot/main.tf`, `README.md`, `docs/aws-iot-setup.md`

- [ ] **Step 1: Run all Python tests.** Run `python -m unittest discover -s tests -v`; resolve only regressions introduced by this feature.
- [ ] **Step 2: Check Compose interpolation and service configuration.** Run `podman compose config` when Podman is installed and verify the cloud profile is opt-in, the sync service shares PostgreSQL access, and key mounts are read-only.
- [ ] **Step 3: Check Terraform formatting and validation.** Run `terraform -chdir=terraform/aws_iot fmt -check` and `terraform -chdir=terraform/aws_iot validate`.
- [ ] **Step 4: Review the final diff for secrets and scope.** Confirm no private key, AWS secret, local `.tfvars`, Terraform state, or unrelated file change is included. Do not claim live AWS validation unless the user has provisioned the account resources and the smoke test succeeds.