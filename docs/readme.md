# Vertex Stability Update Summary (2026-04-15)

## Scope
This document summarizes all additions and modifications made in the latest Vertex stability cycle, plus the standard rollout steps that were executed.

## Goals
- Rotate credentials immediately on first 429.
- Prevent runtime startup failure when all credentials are temporarily exhausted.
- Keep provider credential pool active even after `/model` session override.
- Ensure daily-use runtime is synced with tested code.

## Code Changes

### 1) Immediate 429 Rotation
- File: `run_agent.py`
- Change:
  - In `_recover_with_credential_pool`, first 429 now rotates immediately.
  - Removed previous behavior where first 429 only retried current credential.
- Result:
  - Faster failover under rate limiting.

### 2) Exhausted-Pool Runtime Fallback
- File: `agent/credential_pool.py`
- Added:
  - `select_with_exhausted_fallback()`
  - `_select_exhausted_fallback_unlocked(...)`
- Updated behavior:
  - If all credentials are exhausted, fallback still selects one credential instead of returning no key.
  - Fallback selection follows configured pool strategy (`random`, `round_robin`, `least_used`, `fill_first`).
  - Rotation path avoids selecting the same exhausted credential when alternatives exist.

### 3) Runtime Provider Resolution Guard
- File: `hermes_cli/runtime_provider.py`
- Change:
  - When `pool.select()` returns `None`, runtime now attempts exhausted fallback selection.
- Result:
  - Prevents startup-time "no API key found" when every entry is in cooldown.

### 4) Session Override Keeps Pool Routing
- File: `gateway/run.py`
- Added:
  - `_load_provider_credential_pool(provider)` helper.
- Updated:
  - Session override state now stores and propagates `credential_pool`.
  - Fast-path and background-path agent creation hydrate provider-scoped pool if missing.
- Result:
  - `/model` override no longer disables credential rotation.

### 5) Test Updates
- Files:
  - `tests/run_agent/test_run_agent.py`
  - `tests/agent/test_credential_pool_routing.py`
  - `tests/hermes_cli/test_runtime_provider_resolution.py`
  - `tests/agent/test_credential_pool.py`
  - `tests/gateway/test_session_model_override_routing.py`
- Added/updated coverage for:
  - Immediate rotation on first 429.
  - Exhausted fallback in runtime resolution.
  - Strategy-respecting exhausted fallback.
  - Session override credential-pool hydration.
  - Stable codex reset-timestamp test fixture source (`device_code`).

## Operational Fixes Applied in Daily Runtime
- Synced missing module `agent/models/vertex_ai.py`.
- Restored valid Vertex keys in `/root/.hermes/auth.json` (replaced placeholder `k1`/`k2`).
- Synced tested `run_agent.py` into daily repo.
- Restarted gateway service after sync.

## Standard Rollout Steps Executed
1. Validate changes in test repo.
2. Run targeted regression tests.
3. Commit and push to remote branch.
4. Sync tested runtime files back to daily-use repo.
5. Restart gateway service and verify active state.

## Verification
- Targeted test run:
  - `354 passed`
- Runtime checks after key restore:
  - Vertex pool entries resolve with real key lengths (non-placeholder).
- Gateway status:
  - Service active after final restart.

## New Commit in This Final Stabilization Step
- `cf4b8b5e` - `fix(gateway): keep credential pool on session overrides`

## Notes
- Existing root `README.md` was not modified.
- This document is intentionally placed at `docs/readme.md` to avoid naming conflict.
