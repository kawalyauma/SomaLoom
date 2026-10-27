# Local verification without GitHub Actions

Use Ubuntu 24.04, Python 3.12, Node 22 and Docker Engine/Compose v2. Install system packages: python3.12-venv, tesseract-ocr, fonts-dejavu-core, libcairo2-dev, pkg-config, gcc and python3-dev. The API image includes these plus ClamAV. Scanning needs current signature databases mounted read-only.

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.lock
.venv/bin/pip install --no-deps -e .
npm --prefix apps/web ci
bash tools/verify_local.sh
bash tools/verify_integration.sh
```

Set PYTHON to an alternative venv interpreter if necessary. Docker requires access to its socket; run the native script with sudo env PYTHON=/absolute/venv/bin/python when appropriate. The native script creates uniquely named disposable PostgreSQL16/pgvector and Redis containers on randomized loopback ports; no existing database is used. It sequences migrations, schema comparison, the full suite, populated foundation-preservation rollback and full downgrade/upgrade. Logs live under verification/ (ignored because runtime logs may contain private data).

The final isolated native runner passed 110 tests, zero failures/skips, including real OCR, visual exports and asynchronous DOCX jobs. Final evidence is recorded in RELEASE_ACCEPTANCE.md and docs/verification/. No GitHub-hosted check was run or counted as a pass.

The six-family tests use synthetic original CC0 resources and a deliberately synthetic AIProvider; they exercise real PostgreSQL, Redis Stream, RQ execution, indexing, research, persistence, reviews and PDF/DOCX parsing. They do not verify a live model, national curriculum validity or educator quality. Real AI uses the opt-in services.generation.smoke harness and independently provisioned credentials. Telegram requires a dedicated bot/chat and webhook secret. Live authorized-site testing must use an owned test site.

Do not run migration_drill.py against production; it rejects non-loopback databases and database names other than somaloom_test. It deliberately removes feature data on downgrade. Never run two suites or migration drills against the same database concurrently.

Security: .venv/bin/pip-audit; npm --prefix apps/web audit --omit=dev; Gitleaks v8.24.2 git /repo --redact --config=/repo/.gitleaks.toml --log-opts=origin/main..HEAD. The only allowlist is the exact synthetic/diagram test object key. Browser checks use Playwright/Chromium and axe against the real authenticated application, with production data excluded.
