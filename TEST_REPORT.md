# ZILL release acceptance record

**Run date:** 2026-11-17 (Asia/Riyadh)

## Verified locally

- `python tests/test_api.py` — passed, **70 API checks**. Includes authenticated role/scope authorization, consent/revocation, assignments, alert lifecycle, JSON 404/405 and structured errors, hostile origin rejection, CSRF and logout/session behavior, plus safe database-failure response.
- `python tests/test_wasmer_package.py` — passed, **2 local volume-path/restart runs**. This is a local smoke test, not a remote Wasmer Edge deployment.
- `python tests/test_release_bundle.py` — passed against the ZIP built during the test, extracted into a temporary directory with a fresh database, and served from that extracted directory. Includes API-backed demo credentials and real Chromium journeys.
- Chromium acceptance — **97 checks passed**, including login/session flows and responsive overflow checks at 1920×1080, 1440×900, 1366×768, 1024×768, 768×1024, 390×844, and 360×800 across the public pages and role dashboards.
- Release ZIP CRC and required-root-file checks passed; generated DB, `.env`, and local credentials are excluded.

## Not verified / limitation

The deployed Wasmer hostname and deployment account are not accessible from this workspace. A prior fetch of the reported host returned `400 Unknown hostname`, while the supplied screenshot indicated an application 500. There are no Wasmer runtime logs or deploy credentials here. Therefore **the remote Wasmer 500 is not claimed fixed**. The package contains a Python entrypoint and deployment configuration, but those do not prove a successful remote deployment. After deployment, verify that `/api/health` and `/api/demo/accounts?role=SUPERVISOR` return JSON with HTTP 200 on the exact published host.
