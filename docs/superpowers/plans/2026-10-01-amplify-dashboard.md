# Amplify Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Host a login-protected MobileFrost dashboard on Amplify that reads cloud temperatures, records drive sessions, and sends acknowledged actuator commands to the Raspberry Pi without exposing the Pi to inbound internet traffic.

**Architecture:** Amplify serves a static JavaScript frontend authenticated with Cognito. API Gateway validates Cognito JWTs and invokes Python Lambda handlers for DynamoDB temperature queries, drive/command state, and IoT Core command publication. Terraform manages the AWS resources. An opt-in Pi cloud-bridge service subscribes to device-scoped AWS IoT topics, forwards commands to local Mosquitto, and publishes acknowledgements; the local controller and dashboard continue to operate independently.

**Tech Stack:** AWS Amplify Hosting, Amazon Cognito, API Gateway HTTP API, AWS Lambda Python, AWS IoT Core MQTT/TLS, DynamoDB, Terraform, Vite, AWS Amplify JavaScript Auth, Chart.js, Python `unittest`.

## Global Constraints

- Access is restricted to invited authenticated users; anonymous public access is not enabled.
- No public listener, port forwarding, or inbound tunnel is added to the Raspberry Pi.
- Local sensing, PostgreSQL storage, automatic cooling, and Mosquitto operation remain independent from cloud availability.
- Drive start/stop records an operational session only; it does not start a motor or claim GPS/distance tracking.
- An actuator acknowledgement confirms Pi-bridge forwarding to local Mosquitto, not measured physical fan/servo position.
- Manual actuator settings may be overwritten by automatic temperature control on a later sensor update.
- Device private keys, cloud credentials, and repository access tokens are never committed or exposed to the frontend.
- Provision AWS resources with Terraform; never run `terraform apply` without reviewing the plan and explicit user confirmation.
- Do not create Git commits unless requested.

---

### Task 1: Define Cloud API Contracts

**Files:**
- Create: `tests/test_cloud_api.py`
- Create: `src/mobilefrost/cloud_api.py`

**Interfaces:**
- `lambda_handler(event, context)` is the Lambda entry point.
- `handle_request(event, dependencies)` routes API Gateway v2 events and returns an API Gateway response with JSON body and status code.
- Dependencies expose DynamoDB query/session/command operations and IoT Data Plane operations; tests inject fakes without AWS credentials.

- [ ] **Step 1: Add failing API tests** for allowed temperature ranges (`1`, `24`, `168`), malformed ranges, missing JWT claims, latest/history response shape, and 503 masking when a cloud dependency fails.
- [ ] **Step 2: Run `python -m unittest tests.test_cloud_api -v`** and verify the module/import or expected-route tests fail before implementation.
- [ ] **Step 3: Implement the handler and route dispatch** for `GET /api/temperatures?hours=...`, reading `requestContext.authorizer.jwt.claims.sub` and returning only JSON responses. Reject unsupported hours with 400; return a generic 503 on dependency errors.
- [ ] **Step 4: Run `python -m unittest tests.test_cloud_api -v`** and verify all API contract tests pass.

### Task 2: Add Drive Session Persistence

**Files:**
- Modify: `src/mobilefrost/cloud_api.py`
- Modify: `tests/test_cloud_api.py`
- Create: `tests/fakes.py` only if a small shared DynamoDB fake is needed by more than one test module.

**Interfaces:**
- `GET /api/drive` returns `{"active": null}` or the active session object.
- `POST /api/drive/start` returns `{"status":"started","session":{...}}` and is idempotent while a session is active.
- `POST /api/drive/stop` closes the active session and returns it; repeated stop requests return `{"status":"stopped","active":null}`.
- Session records contain `session_id`, `device_id`, `started_at`, optional `ended_at`, and `status`, with UTC ISO-8601 timestamps.

- [ ] **Step 1: Add failing tests** for first start, repeated start returning the same active session, stop recording `ended_at`, repeated stop, and concurrent-start conditional-write conflict.
- [ ] **Step 2: Run `python -m unittest tests.test_cloud_api -v`** and verify each new session test fails for the missing route/behavior.
- [ ] **Step 3: Implement DynamoDB session operations** using a transaction to create the session record and active-session pointer together; stop updates the session and removes the pointer conditionally. On a conditional start conflict, reread and return the active session.
- [ ] **Step 4: Run `python -m unittest tests.test_cloud_api -v`** and verify start/stop/idempotency tests pass.

### Task 3: Add Correlated Actuator Commands

**Files:**
- Modify: `src/mobilefrost/cloud_api.py`
- Modify: `tests/test_cloud_api.py`
- Create: `src/mobilefrost/cloud_ack.py`
- Create: `tests/test_cloud_ack.py`

**Interfaces:**
- `POST /api/actuators/fan` accepts JSON `{"value": int}` for `0..255`.
- `POST /api/actuators/flap` accepts JSON `{"value": int}` for `0..90`.
- Valid requests create a UUID `request_id`, persist a pending command, publish `mobilefrost/commands/{device_id}/actuators/{kind}` at QoS 1, and return HTTP 202 with `{"request_id": ..., "status":"pending"}`.
- `GET /api/commands/{request_id}` returns pending, acknowledged, failed, or timed-out state and the acknowledged value when available.
- `cloud_ack.lambda_handler(event, context)` validates an IoT rule event and stores the acknowledgement for its request ID.

- [ ] **Step 1: Add failing API tests** for fan/flap boundary values, invalid/missing/fractional values, command persistence before publication, generated request IDs, publish failure, unknown request IDs, and pending/acknowledged status responses.
- [ ] **Step 2: Run `python -m unittest tests.test_cloud_api -v`** and verify the actuator routes and command-state behavior fail.
- [ ] **Step 3: Implement command validation and publish flow**. Use server-side integer checks (reject booleans and non-integral numbers), persist pending state, publish compact JSON with `request_id`, `device_id`, `kind`, `value`, and `timestamp`, and mark publish exceptions as failed without returning a false success.
- [ ] **Step 4: Add failing acknowledgement-handler tests** for valid, malformed, and unknown request IDs; run `python -m unittest tests.test_cloud_ack -v` to verify the baseline fails.
- [ ] **Step 5: Implement acknowledgement updates** so only a matching pending command transitions to acknowledged and records bridge-forwarded value/time.
- [ ] **Step 6: Run `python -m unittest tests.test_cloud_api tests.test_cloud_ack -v`** and verify all command/ack tests pass.

### Task 4: Build the Pi AWS IoT Bridge

**Files:**
- Create: `src/mobilefrost/aws_bridge.py`
- Create: `tests/test_aws_bridge.py`
- Modify: `compose.yml`

**Interfaces:**
- `BridgeConfig.from_env(environment)` validates AWS endpoint, device ID, certificate/key/root CA paths, and local MQTT host/port.
- `AwsCommandBridge` subscribes only to `mobilefrost/commands/{device_id}/actuators/+`, validates JSON command IDs/kinds/value bounds, publishes fan/flap values to the existing local `FAN_SET_TOPIC` or `FLAP_SET_TOPIC`, and publishes a correlated acknowledgement to `mobilefrost/device/status/{device_id}/commands` only after local MQTT publish succeeds.
- Module execution starts the bridge process and reconnects after AWS/local broker interruptions.

- [ ] **Step 1: Add failing bridge tests** for exact subscription topic, valid fan/flap forwarding, malformed JSON, unsupported kind, out-of-range values, failed local publish, correlated acknowledgement, and TLS paths/options.
- [ ] **Step 2: Run `python -m unittest tests.test_aws_bridge -v`** and verify the new module behavior fails.
- [ ] **Step 3: Implement the bridge** with an AWS IoT MQTT/TLS client and a separate local Mosquitto client. Reuse the existing local MQTT topic constants and `parse_actuator_command` bounds where applicable; never log certificate contents or private paths beyond safe error context.
- [ ] **Step 4: Add an opt-in `aws_bridge` Compose service** under the `cloud` profile, depending on Mosquitto, mounting `./secrets` read-only, and receiving only non-secret endpoint/device/path configuration through environment variables.
- [ ] **Step 5: Run `python -m unittest tests.test_aws_bridge -v`** and verify the bridge tests pass.

### Task 5: Create the Amplify Frontend

**Files:**
- Create: `frontend/package.json`
- Create: `frontend/index.html`
- Create: `frontend/src/main.js`
- Create: `frontend/src/api.js`
- Create: `frontend/src/style.css`
- Create: `frontend/vite.config.js`
- Create: `frontend/src/api.test.js`
- Create: `amplify.yml`
- Modify: `.gitignore`

**Interfaces:**
- Build-time config uses `VITE_API_URL`, `VITE_AWS_REGION`, `VITE_COGNITO_USER_POOL_ID`, and `VITE_COGNITO_USER_POOL_CLIENT_ID`; none are secrets.
- `api.js` exports `request(path, options)` which obtains the current Cognito ID token, sends it as `Authorization: Bearer <token>`, parses JSON, and throws a typed error for non-2xx responses.
- The UI supports sign-in/sign-out, temperature chart/ranges, active drive start/stop, fan/flap controls, pending command polling, acknowledgement/failure display, and offline/API-error states.

- [ ] **Step 1: Add frontend tests** for Authorization header use, JSON error parsing, unauthenticated request rejection, and pending-versus-acknowledged command states.
- [ ] **Step 2: Run `npm --prefix frontend test -- --run`** and verify tests fail because the frontend modules are not implemented.
- [ ] **Step 3: Add Vite and dependencies** `aws-amplify`, `chart.js`, `vite`, `vitest`, and `jsdom`; configure the test environment to use jsdom.
- [ ] **Step 4: Implement Cognito sign-in and authenticated API requests** using Amplify Auth `signIn`, `signOut`, and `fetchAuthSession`; never place device credentials or AWS secret keys in frontend config.
- [ ] **Step 5: Implement the dashboard UI** with a separate signed-in view, existing MobileFrost sensor colors/temperature chart, explicit pending/ack/error states, and a notice that automatic cooling may override manual settings.
- [ ] **Step 6: Run `npm --prefix frontend test -- --run` and `npm --prefix frontend run build`**; verify tests pass and the static output is generated in `frontend/dist`.
- [ ] **Step 7: Add repository-root `amplify.yml`** using monorepo `appRoot: frontend`, `npm ci`, `npm run build`, and artifact directory `dist`; ignore `frontend/node_modules/` and `frontend/dist/` in Git.

### Task 6: Provision AWS with Terraform

**Files:**
- Modify: `terraform/amplify/main.tf`
- Modify: `terraform/amplify/api.tf`
- Modify: `terraform/amplify/data.tf`
- Modify: `terraform/amplify/variables.tf`
- Modify: `terraform/amplify/outputs.tf`

- [ ] **Step 1: Create the DynamoDB readings table** with partition key `sensor_id`, sort key `timestamp`, on-demand billing, and encryption.
- [ ] **Step 2: Change the API Lambda policy and configuration** from Timestream to `dynamodb:Query` on the readings table and set `READINGS_TABLE`.
- [ ] **Step 3: Change the temperature IoT rule** to the DynamoDBv2 action with `SELECT *`; grant its role only `dynamodb:PutItem` on the readings table.
- [ ] **Step 4: Remove obsolete Timestream resources, variables, IAM actions, outputs, and documentation.** Preserve the existing separate operations table.
- [ ] **Step 5: Run `terraform -chdir=terraform/amplify fmt -check`, `validate`, and `plan`; do not run apply automatically.**

### Task 7: Document Setup, Operations, and Safety

**Files:**
- Modify: `docs/aws-iot-setup.md`
- Modify: `README.md`
- Create: `docs/amplify-dashboard-setup.md`

- [ ] **Step 1: Document prerequisites and secret handling** for AWS Console access, Git-provider authorization, certificate storage on the Pi, and Cognito invited-user creation.
- [ ] **Step 2: Document Terraform inputs, private state handling, plan review, explicit apply, and cleanup.**
- [ ] **Step 3: Document Compose startup and verification** for the local stack and opt-in cloud bridge, including MQTT topics, API health/auth checks, command acknowledgement limits, and local operation during cloud outage.
- [ ] **Step 4: Document teardown** for Amplify, Cognito, API/Lambda, IoT, DynamoDB, CloudWatch, and IAM resources; warn that destroying the readings table removes cloud history.
- [ ] **Step 5: Run `python -m unittest discover -s tests -v`, `npm --prefix frontend test -- --run`, and `npm --prefix frontend run build`.**

### Task 8: End-to-End Contract Verification

**Files:**
- Modify: `tests/test_app.py`
- Modify: `tests/test_dashboard.py`
- Modify: `tests/test_cloud_api.py`
- Modify: `tests/test_aws_bridge.py`

- [ ] **Step 1: Add integration contract tests** verifying the AWS bridge's published local topics match `mqtt_io.py`, the setup guide's IoT policies match the bridge command/ack topics, and cloud API response shapes match frontend calls.
- [ ] **Step 2: Run all Python tests** with `python -m unittest discover -s tests -v` and preserve existing local dashboard/controller behavior.
- [ ] **Step 3: Run frontend tests and build** with `npm --prefix frontend test -- --run` and `npm --prefix frontend run build`.
- [ ] **Step 4: Report remaining deployment prerequisites** (AWS account/region, Git-provider token, Pi certificate ARN, and explicit plan review). Do not claim a live deployment until apply and smoke tests succeed.