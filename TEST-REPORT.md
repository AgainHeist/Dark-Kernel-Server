# Again Heist — Executed test report

Report date: 8 November 2026. Source build 1.0.0. This report separates locally executed checks from production acceptance.

## Environment

- Available Python runtime: CPython 3.11.2, isolated virtual environment.
- Production target: Python 3.12+; supplied Dockerfile uses Python 3.12. A runtime download for 3.12 was blocked by network restrictions. No claim of an executed Python 3.12/container deployment.
- FastAPI, SQLAlchemy, Alembic, Pydantic, PyJWT, Argon2 and dependencies pinned in requirements.txt.
- SQLite with foreign keys, WAL and serialized local request transactions.
- Headless Chromium with Playwright for real HTTP/browser UI workflows.
- Tests use disposable databases and test-only accounts, never customer data.

## Backend: 27 pytest scenarios passed

Command: `pytest -q`.

1. Authentication, CSRF, logout and wrong credentials.
2. Owner-only registration and permission isolation.
3. Key generation, credit debit, device binding, form/JSON compatibility and stable expiry.
4. Expiration, reset, suspension/reactivation, extension and permanent revocation.
5. Lifetime and bulk generation.
6. Idempotent generation and conflicting operation IDs.
7. Insufficient funds rollback.
8. Ownership isolation and scoped/revocable API keys.
9. Disabled reseller management access while existing customer licenses remain valid.
10. Credit adjustment replay and nonnegative bounds.
11. Manual payment submission/approval, duplicate reference and approval replay.
12. Manual rejection without credits.
13. Unconfigured automatic gateway fails explicitly.
14. Mocked Razorpay order creation, signed webhook, bad signature, mismatched amount and duplicate-credit prevention.
15. Rotating refresh sessions and password-change revocation.
16. Global settings, CSV export, pagination, dashboard and audit visibility.
17. Malformed native inputs, unsupported version, unusable device fallback, cross-origin rejection and body limit.
18. Concurrent purchases cannot overspend (SQLite execution).
19. Concurrent device binding cannot exceed limit (SQLite execution).
20. Owner-specific route paths reject reseller sessions.
21. Concurrent identical generation operation produces one result and one debit (SQLite execution).
22. Concurrent manual approval credits exactly once (SQLite execution).
23. Login rate counter survives credential rejections.
24. Native validation rate limit preserves legacy HTTP 200 JSON contract.
25. Ledger sum matches wallet and passwords preserve intentional spaces.
26. MySQL DDL compilation for the schema (compile only, NOT a running MySQL database).
27. Signed malformed webhook rejection, failed payment followed by valid capture, and event-ID content mismatch.

Latest run: **27 passed**. One upstream Starlette/httpx deprecation warning: the pinned TestClient currently works, but upstream recommends future httpx2 adoption. This is not an application test failure.

## Browser: 45 checks passed

Command: `npm run test:browser` against a separately running disposable instance, with AH_URL/AH_OWNER/AH_PASSWORD configured. See tests/browser.cjs.

- Again Heist branding and actual Telegram/YouTube destinations.
- Landing page fits 360, 390, 768, 1024 and 1440 px.
- Reduced-motion support.
- Wrong-password inline feedback and owner login/navigation.
- Owner views: license vault, generation, reseller management, payments, ledger, settings, logs, API credentials and profile.
- Bulk generation through the real UI, ALi prefix and native form POST verification.
- License details modal.
- Reseller creation and credit allocation through the UI.
- Reseller login without owner navigation.
- Reseller generation and debit visible in ledger.
- All reseller views render.
- Manual payment request appears pending; owner approval through a custom confirmation dialog succeeds.
- Dashboard fits 360, 390, 768, 1024 and 1440 px.
- One-time API credential presentation.
- No browser JavaScript runtime errors.

Desktop/mobile landing and dashboard screenshots were captured and visually reviewed. Tests create and clearly isolate synthetic data. No test records/database are shipped in the deployment archive.

## Additional executed checks

- Python source compilation and JavaScript syntax check.
- Alembic SQLite upgrade → downgrade → upgrade round-trip on a separate database.
- SQLite maintenance backup created outside the project with private file permissions; opened independently, PRAGMA integrity_check returned `ok` and expected records existed.
- Source archive integrity/file exclusions are checked during packaging.

## Not yet verified — launch gates

1. Native Python 3.12+ installation and Docker build/start.
2. A live MySQL/MariaDB schema, driver, isolation-level/locking behavior and concurrency suite. Use AH_TEST_DATABASE_URL with a dedicated ah_test_ database; tests are destructive.
3. Real provider credentials, real Razorpay order/capture and actual internet webhook delivery. Gateway code is tested with mocked order responses and locally generated signatures, not live money.
4. Public hosting HTTPS, reverse proxy/CORS, persistent storage, rate-limit tuning, monitoring and real production backup/restore operations.
5. The owner's actual rooted Android APK and executable handshake, including expiry/seller/lifetime display and the real device-property fingerprint.
6. Existing domain ownership and deploying API at its hardcoded origin, or an explicitly approved client URL migration.
7. Independent penetration testing, accessibility audit, load testing and payment compliance/provider approval.

## Scope limits / honest completion status

Core API-driven platform, responsive UI, license lifecycle, wallet/ledger, account/session control, manual payments, API credentials, audit and Razorpay adapter are implemented. The full PRD's production acceptance is **not complete** until the launch gates above pass. There is no automatic refund/reconciliation scheduler, MFA/email recovery, forced password change or periodic native revalidation. Reseller removal is intentionally soft disabling. Secrets are not embedded in the UI; license keys remain recoverable in the protected database for authorized inventory/export.

The existing DARKxKernal native source was not changed, and none of this platform was committed/pushed to its GitHub repository.
