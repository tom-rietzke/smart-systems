# AWS IoT Cloud Design

## Goal

Store MobileFrost temperature readings in AWS as well as locally so the data is
available off-site and can be evaluated for the Ice Truck cloud challenge. Keep
the local controller, PostgreSQL history, Mosquitto consumers, and dashboard
working when AWS or the internet is unavailable.

## Architecture

PostgreSQL remains the local source of truth and durable upload queue. Each
successful temperature insert creates a pending cloud-outbox record in the same
database transaction. A separate `cloud_sync` process reads pending records and
publishes them to AWS IoT Core using MQTT over TLS and QoS 1. It marks a record
delivered only after AWS IoT Core acknowledges the publish. This confirms broker
acceptance, not successful completion of the downstream Timestream rule. Failed
connections or publishes leave records pending for a later retry; sensor
acquisition and local control do not wait for AWS. Timestream rule-action errors
are recorded in a short-retention CloudWatch log group for operator diagnosis.

An AWS IoT Core rule routes the cloud topic into an Amazon Timestream for
LiveAnalytics database and table. The cloud event carries the sensor ID, numeric
temperature, original UTC timestamp, and its epoch-millisecond equivalent so
Timestream stores the measurement time rather than the rule processing time.
The existing local MQTT topics remain unchanged; cloud data uses a separate,
documented topic.

## AWS Resources and Terraform

Terraform provisions one AWS IoT Thing, a least-privilege IoT policy for the
cloud temperature topic, a Timestream database and table, an IoT rule, the
least-privilege IAM role/policy that lets the rule write to that table, and a
CloudWatch log group/role for failed rule actions. The recommended default region
is `eu-central-1`; it remains configurable. Terraform state contains
infrastructure metadata only and must not contain a device private key.

The device certificate and private key are created and downloaded separately
through the AWS IoT console, then attached to the Thing and IoT policy. The
private key is mounted read-only into the `cloud_sync` container from a
device-local directory excluded from version control. The setup guide documents
AWS CLI/profile prerequisites, deployment, certificate attachment, Compose
configuration, verification, cleanup, cost awareness, and data residency.

## Runtime and Failure Behavior

The cloud sync process uses independent TLS MQTT credentials and does not share
or replace the local Mosquitto connection. It polls the PostgreSQL outbox, uses
bounded batches, and retries pending records after connection or publish
failures. Acknowledged events are not sent again in normal operation. QoS 1 can
still produce duplicates across a crash between AWS acknowledgement and the
local delivered update. Each event carries its stable database ID for tracing;
Timestream's record identity uses a stable measure name, sensor dimension, and
source timestamp so a retry does not create a second measurement.

Cloud credentials are optional at runtime. Without a complete cloud
configuration, the local controller and dashboard continue to work and no
cloud sync process is started. Credentials and private keys are never committed
or printed by application code.

## Scope

- Add a transactional PostgreSQL outbox for newly stored temperature samples.
- Add a cloud sync process that publishes the outbox to AWS IoT Core over TLS.
- Add an opt-in Compose service and read-only certificate mount.
- Add Terraform for IoT Core, Timestream, CloudWatch error logs, and
  least-privilege rule permissions.
- Document setup, operating cost considerations, validation, and resource
  cleanup.
- Leave local MQTT commands, sensor loops, dashboard behavior, and actuator
  control unchanged.

## Testing

Unit tests cover atomic local storage plus enqueue, selection and delivery-state
updates, payload schema and UTC timestamps, and retry behavior when publish
fails. Adapter tests verify TLS configuration and QoS without requiring AWS
credentials. Infrastructure validation uses `terraform fmt -check` and
`terraform validate` when Terraform is installed. The documented live smoke test
publishes a sample event, confirms its arrival in Timestream, then checks that a
brief AWS outage leaves data pending and that sync resumes after connectivity is
restored.

## Assumptions and Limits

- AWS IoT Core and Timestream for LiveAnalytics are available in the selected
  region and account.
- The team creates AWS credentials locally; no account secrets are added to the
  repository.
- Cloud persistence is for temperature samples in the current schema. Humidity,
  actuator telemetry, alerting, predictive-maintenance models, and a cloud UI
  are outside this increment.
- AWS resources incur usage-based costs. The guide must call out that the user
  should review current regional pricing and destroy the demo resources when
  finished.