# Again Heist

An API-driven license/reseller platform for ALi. FastAPI + SQLAlchemy + JWT/Argon2 authentication, a custom responsive glass-inspired HTML/CSS/JS interface, a legacy-compatible native validation API and a Razorpay payment adapter. No frontend build or CDN fonts required. Telegram: **[@alionera](https://t.me/alionera)** · YouTube: **[@AimTicxon](https://youtube.com/@AimTicxon)**.

## Read this first / important

- This is a substantial working implementation, **not a claim of production sign-off**. Read `TEST-REPORT.md` for executed tests and remaining deployment checks.
- Python hosting is required. Uploading this ZIP to ordinary PHP-only InfinityFree hosting **will not run FastAPI**. Use a Python-capable host/container/VPS with a persistent MySQL service for production.
- The original executable still calls `https://originalcheats.myvipsite.fun/connect`. Deploy at that origin/path if you control it, or get owner approval to update the native URL, rebuild the executable and rebuild the APK. No native files were modified by this project.
- The existing executable sends **form data**, while the new PRD shows JSON. `/connect` intentionally accepts **both** and returns HTTP 200 for normal license decisions, as the existing client expects.
- No private credentials, production accounts, payment receipt screenshots or customer database are included. Deterministic credentials inside tests are disposable test fixtures only, never runtime defaults.

## 1. Local setup (Python 3.12+)

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Put the generated value in `JWT_SECRET` in `.env`. Set `ADMIN_USERNAME` and a unique `ADMIN_PASSWORD` of 12–128 characters. Usernames must be 3–40 letters, digits or underscores. Do not post these secrets in chat, GitHub or frontend files.

```bash
alembic upgrade head
python -m app.bootstrap
uvicorn app.main:app --host 0.0.0.0 --port 8080 --no-proxy-headers
```

Open `http://localhost:8080` then **Workspace**. The first account is an **owner**. Bootstrap is a trusted CLI operation, not a public registration route; it refuses to reset an existing owner. Remove `ADMIN_PASSWORD` after provisioning. Development tables can be initialized automatically, but use Alembic from the outset to maintain migration state.

Windows: activate `.venv\Scripts\activate` instead. Keep `.env` in the project root. Run commands from that root.

**Keep JWT_SECRET stable.** It signs sessions and currently keys device fingerprint hashes; replacing it invalidates sessions and changes fingerprint lookups. Plan explicit device rebinding/secret migration before rotation. Production refuses a missing/short secret.

## 2. First owner workflow

1. **Reseller network → Add reseller**. Share its initial password securely.
2. **Adjust credits** with a reason. Owner grants are not limited to a package (bounded only by safe integer storage).
3. Reseller signs in, chooses plan/devices/quantity and generates keys.
4. Keys default to `ALi-<12 hex>-<12 hex>` (96 random bits). Configurable prefix applies to future keys only.
5. Customer enters the key in the existing APK. First successful validation starts timed expiry and binds the device.
6. Owner/reseller can inspect their authorized keys, suspend/reactivate, reset devices, or permanently revoke.

Owner can extend a timed key. Reset/unblock does not extend expiry. Lifetime keys have no expiry and return `"Lifetime"`; confirm this display in your real APK. Revocation is permanent. Account deletion is soft disabling: it revokes reseller sessions but preserves their existing customer licenses. Block keys separately if needed.

Password change revokes all sessions. Owner can reset a reseller password via the panel; share through a private channel. Forced password-change tokens/MFA/email recovery are not implemented. Trusted operator recovery:

```bash
python -m app.maintenance reset-owner-password
```

This prompts privately and revokes owner sessions. Restrict shell/hosting access.

## 3. Pricing and credits

Default plans: 1, 7, 30, 90 days and lifetime. Costs: 1, 7, 30, 90, 500 credits **per allowed device**, respectively. 1–5 devices and 1–100 keys per generation. Owner issuance is free but audited. Configure costs/durations/packages in **System settings**.

`total cost = plan cost × devices × quantity`.

Timed licenses activate on first successful login. Timed plan updates never rewrite already purchased license durations. Wallets cannot be negative. Costs, wallet mutations, license creation, operation records and the credit ledger commit atomically. Include an `operation_id` (UUID recommended) for mutation routes that require it. Reusing the same ID and input replays the result; changing the input with the same ID is rejected. Keep the same ID on retries. Credits use integer units; amounts use integer **INR paise**. Wallet safety ceiling is 9 quadrillion credits, not a package-based business limit.

Payments snapshot amount/credits at creation. Price edits do not alter pending payment amounts. Existing financial/audit records are preserved.

## 4. Native /connect integration

```bash
curl -X POST https://YOUR-DOMAIN/connect \
  --data-urlencode 'game=FREEFIRE' \
  --data-urlencode 'user_key=ALi-YOUR-GENERATED-KEY' \
  --data-urlencode 'serial=YOUR_DEVICE_ID' \
  --data-urlencode 'version=2.0'
```

Equivalent JSON is accepted:

```json
{"game":"FREEFIRE","user_key":"ALi-YOUR-GENERATED-KEY","serial":"YOUR_DEVICE_ID","version":"2.0"}
```

Success:

```json
{"status":true,"message":"License verified successfully","data":{"expiry":"2027-01-01T00:00:00Z","seller":"partner","credit":100}}
```

Normal failure (HTTP 200 for legacy compatibility):

```json
{"status":false,"message":"Device mismatch"}
```

Only product `FREEFIRE` and version `2.0` are currently supported. API keys are **not required for this legacy validation route**. Missing/unusable serials, including `unknown_device`, are rejected. Devices are stored as keyed hashes, not raw serials; the panel displays a short fingerprint. Client device properties are not tamper-proof hardware attestation. Same device reuses its slot; concurrent bindings are transactionally constrained. Verification events contain outcomes and license IDs, not submitted raw keys/serials.

Owner/reseller credit balance is returned as numeric `credit` because requested by the new PRD. The current native client already has a canonical string `seller` field, so it does not need to use `credit` as a seller fallback.

**Server revocation takes effect at the next validation.** The website cannot terminate an already running executable. Existing native TLS/host/signature verification weaknesses remain unchanged; this backend does not make the client unbreakable. APK root access and its launch handshake are separate from this HTTP server.

## 5. Manual payment workflow

Default packages: starter = 100 credits / ₹100; studio = 500 credits / ₹450. Configure before use.

1. Reseller obtains the real payment instructions directly from verified ALi support. No invented UPI/bank details are embedded.
2. Reseller pays externally and submits an actual reference plus selected package.
3. Pending request **does not add credits**.
4. Owner independently checks receipt/amount, then approves or rejects with a reason.
5. Approval adds the snapshotted credits exactly once, even on duplicate/concurrent approvals. A reference is unique across accounts.

No automatic refunds, chargeback handling or bank-reference validation are claimed. A reference alone is not evidence of payment. An approved manual record contributes to dashboard revenue only after owner approval.

## 6. Automatic payments — Razorpay

An actual Razorpay Orders + signed webhook adapter is implemented, not a simulated payment-success button. Configure your own matching test/live credentials:

```dotenv
PAYMENT_KEY_ID=your_razorpay_key_id
PAYMENT_SECRET=your_razorpay_api_secret
PAYMENT_WEBHOOK_SECRET=your_separate_webhook_secret
```

Configure Razorpay to deliver `payment.captured` and `payment.failed` to:

```text
https://YOUR-DOMAIN/api/payments/webhook
```

- Server creates the order with server-controlled amount/currency.
- Frontend opens official Razorpay Checkout. Browser success **never credits the wallet**.
- Raw webhook body is HMAC-SHA256 verified with `X-Razorpay-Signature`.
- Require a bounded `X-Razorpay-Event-Id`, matching order/amount/currency, captured state and payment ID.
- Order locks, unique webhook IDs, unique gateway payment IDs and ledger references prevent double-crediting.
- A failed attempt may later be followed by a valid capture for the same order; approval still happens only once.
- Unsupported events are ignored. Invalid signatures/mismatched amounts do not credit.
- No credentials: automatic payment creation returns 503 and the UI labels it unconfigured; manual payments remain available.
- Mocked gateway tests passed. **No live provider credentials, external order/capture or real webhook delivery were tested here.** Verify Razorpay API payloads/checkout/CSP in provider test mode, then live mode, before accepting customer money.
- Provider network calls cannot be included in a local database transaction. A rare order-created/database-commit-failed case can leave an unreturned external order; no credits are issued. Reconcile provider orders/receipts and do not assume distributed exactly-once external order creation.
- Do not mark automatic payments approved by hand: gateway credits require a verified webhook. There is no automatic refund/reconciliation scheduler yet.

## 7. Authentication / management API

- JWT access cookie: HttpOnly, 15-minute default expiry.
- Opaque hashed refresh cookie: HttpOnly, rotating refresh sessions, 7-day default expiry.
- Secure cookies in production, SameSite Strict.
- Cookie mutation requests require `X-CSRF-Token`; login/me/refresh returns the session CSRF token. Frontend stores only this CSRF value in sessionStorage, not JWTs.
- `POST /api/auth/refresh` rotates both session and cookies; old session becomes invalid.
- `POST /api/auth/logout` revokes the session.
- `Authorization: Bearer <access token>` is accepted for trusted API clients, still checked against the live enabled session/account.
- `/api/auth/register` is **owner-only** reseller creation, never public owner registration.
- Management API keys are displayed once and stored hashed. They authorize role-scoped license list/detail/export/generation only, not owner administration, payments or password changes. Do not put them in an APK or frontend bundle.
- Account disabling immediately prevents management API/session access. Existing customer keys remain valid by documented policy.

API reference is at `/api/docs` in development; disabled in production. Dashboard and API requests return consistent JSON error detail. Exact native validation failures use the legacy `status/message` contract.

Default persisted-IP limits: auth 30/5 minutes; native validation 180/5 minutes; management mutations 600/5 minutes. Rejections retain counters. Request bodies are limited to 64 KiB. Shared mobile/proxy IPs may require a tuned policy. Forwarded IP headers are not trusted by default. Schedule pruning and use reverse-proxy connection/body/time limits for public deployment.

## 8. Production / MySQL / Python hosting

```dotenv
APP_ENV=production
DATABASE_URL=mysql+pymysql://USER:URL_ENCODED_PASSWORD@HOST/again_heist?charset=utf8mb4
JWT_SECRET=YOUR_STABLE_RANDOM_32_PLUS_CHARACTER_SECRET
CORS_ORIGINS=https://your-domain.example
```

Create the database with utf8mb4/InnoDB. Use restricted database credentials and managed backups. MySQL 8 / a maintained MariaDB release is recommended. Production config rejects SQLite and short/missing JWT secrets. TLS is terminated by your host/reverse proxy; access must be HTTPS.

```bash
alembic upgrade head
# Provision once using private environment variables, then remove ADMIN_PASSWORD:
python -m app.bootstrap
uvicorn app.main:app --host 0.0.0.0 --port 8080 --no-proxy-headers --no-access-log
```

Serve API + frontend from one public origin (relative URLs). Explicitly set `CORS_ORIGINS` to the real HTTPS origin when a proxy terminates TLS and upstream sees HTTP. Do not set wildcard origins with credentials. Configure trusted proxy headers at infrastructure level only if necessary; never blindly trust internet-supplied forwarded headers.

Included Dockerfile uses **Python 3.12**, a non-root user and runs Alembic before Uvicorn. Docker itself was not available/tested in this workspace. Set environment securely and expose the app only through HTTPS. Bootstrap separately inside the configured container after migrations. Start with one instance; coordinate migrations separately before scaling replicas.

Production security headers deny embedding. Development permits only the explicitly listed Arena/preview frame origins. No production payment/database secret is sent to frontend JavaScript; Razorpay's public key ID is intentionally public.

### Native host qualification

Before switching customer traffic, prove native POST works without a browser challenge/JavaScript cookie, provider sleep fits the 30-second timeout, writes persist and `/connect` is not redirected to an HTML page. A free subdomain is not a custom domain. Static/PHP-only hosting cannot run this application as supplied.

## 9. Tests

```bash
pytest -q
```

The suite creates a disposable SQLite database in the system temporary directory. Optional destructive MySQL suite:

```bash
AH_TEST_DATABASE_URL='mysql+pymysql://USER:PASSWORD@HOST/ah_test_disposable' pytest -q
```

**This drops and recreates tables. Never point tests at production.** The database name must start `ah_test_`. MySQL test execution remains required on your production-compatible database.

Browser checks (no runtime Node requirement):

```bash
npm install
npx playwright install chromium
AH_URL=http://127.0.0.1:8080 AH_OWNER=your_test_owner AH_PASSWORD=your_test_password npm run test:browser
```

Use a disposable running development instance: browser tests create resellers, keys, credit adjustments, API credentials and a manual-payment approval. Screenshots default to `/tmp/again-heist-browser`; override `AH_ARTIFACTS`. An already installed browser may be selected with `CHROMIUM_EXECUTABLE_PATH`.

See `TEST-REPORT.md` for measured results and limitations. Do not confuse MySQL DDL compilation with a live MySQL test, or mock webhook tests with real payments.

## 10. Maintenance / backups / recovery

```bash
python -m app.maintenance prune --days 90
python -m app.maintenance backup-sqlite /PRIVATE/BACKUP/PATH/again-backup.sqlite
```

Run pruning on a trusted scheduled job. It removes old verification logs and expired sessions/rate buckets, not financial/audit records. SQLite backup uses the backup API and requires an output path outside the project, protected to mode 0600. Test restoring to a separate development instance.

For production use MySQL-native/managed encrypted backups, daily scheduling and a real restore drill. Do not place backups, `.env` or databases under publicly served frontend paths. The application serves only `frontend/` as static assets; never expose the project root through a generic file server.

`GET /health` checks database connectivity. Structured application request logs contain request IDs, path, method, status and duration, not request bodies or raw credentials. Database audit logs cover sensitive actions. Configure monitoring, retention and external alerting on your host; none is remotely provisioned by this ZIP.

## 11. Scope / decisions / limitations

- Core platform, manual payments and Razorpay adapter are implemented. Live hosting/gateway/native-device acceptance is still pending.
- Initial Python runtime available here was 3.11.2; tests ran on that runtime. Production target and Dockerfile are Python 3.12+. A 3.12 runtime download was blocked by the workspace network, so do not claim a verified 3.12 deployment yet.
- SQLAlchemy models/migration support MySQL, but live MySQL locking/driver behavior must be tested. SQLite local requests serialize transactions with BEGIN IMMEDIATE; this is intentionally not presented as scalable production behavior.
- Standard list pages paginate 25 records. CSV export caps at 10,000 rows. Credits overview helper caps 100 accounts; use paginated reseller management for full inventory. These bounds prevent accidental enormous responses.
- No automated payment refunds, settlement reconciliation, email, MFA, forced-password-change policy, offline validation or periodic native revalidation. Operator password recovery is a trusted CLI workflow.
- Settings support five plans, 1–10 credit packages and an alphanumeric key prefix. Current product/version/currency are FREEFIRE / 2.0 / INR. Extending these requires a deliberate compatibility change, not arbitrary code execution through settings.
- License keys are stored recoverably in the database for authorized display/export. Protect the database/backups; encrypt-at-rest via infrastructure is recommended. API secrets/passwords are hashed. Do not claim all database fields are encrypted by this application.
- No schema/data import from the PHP prototype or existing private server is included. Migrate records only after explicit mapping and backups.
- No GitHub publication, domain provisioning, payment account registration or native client rebuild was performed.

## Files

`app/` backend modules; `frontend/` three static files; `migrations/` immutable initial Alembic schema; `tests/` backend/browser suites; `.env.example`; pinned `requirements.txt`; optional browser `package.json`; Python 3.12 Dockerfile; documentation. Runtime databases/secrets/caches and preview accounts are deliberately excluded from the deployment ZIP.
