# TESTS

## OVERVIEW

8 test files, ~2,500 lines, 97.85% coverage. Uses `pytest-homeassistant-custom-component` for HA test harness, `aioresponses` for HTTP mocking. All tests are async (`asyncio_mode = "auto"`).

## STRUCTURE

```
tests/
├── conftest.py                     # Shared fixtures: mock_config_entry, mock_api, mock_setup_entry
├── test_api.py                     # API client tests (37 tests, 648 lines)
├── test_coordinator.py             # Coordinator + statistics tests (22 tests, 915 lines)
├── test_config_flow.py             # Config flow tests (21 tests, 617 lines)
├── test_sensor.py                  # Diagnostic sensor tests (9 tests, 139 lines)
├── test_init.py                    # Setup/unload/migration tests (4 tests, 112 lines)
├── test_diagnostics.py             # Diagnostics redaction tests (4 tests, 87 lines)
├── fixtures/
│   └── sample_hourly_response.json # 24 hourly datapoints with consumption/cost
└── __init__.py                     # Empty
```

## MOCKING STRATEGY (MINIMAL — EXTERNAL BOUNDARIES ONLY)

| What to Mock | How | Why |
|-------------|-----|-----|
| HTTP requests | `aioresponses` (`.get()`, `.post()`) | External boundary: Electric Ireland website |
| Config entries | `MockConfigEntry` from `pytest_homeassistant_custom_component.common` | HA internal: entry lifecycle |
| Recorder | `recorder_mock` fixture | HA internal: statistics storage |
| Time | `freezegun` / `async_fire_time_changed` | Deterministic time-dependent tests |
| API client class | `unittest.mock.AsyncMock` + `patch` | Isolate coordinator from API |

**NEVER mock**: HTML parsing, statistics calculation, config flow validation logic, coordinator update logic, entity value computation.

## FIXTURE PATTERNS

### conftest.py Fixtures

- **`mock_config_entry`**: Creates `MockConfigEntry` with domain, version=2, test credentials, and meter IDs. Unique ID set to account number.
- **`mock_api`**: Patches `ElectricIrelandAPI` with `AsyncMock` returning test data. Used for coordinator and init tests.
- **`mock_setup_entry`**: Patches `async_setup_entry` to skip full integration setup during config flow tests.

### JSON Fixtures

- **`fixtures/sample_hourly_response.json`**: Realistic API response with 24 hourly entries, each containing consumption (kWh), cost (EUR), and tariff bucket data.

## TEST-BY-TEST GUIDE

| File | Tests | What It Validates |
|------|-------|-------------------|
| `test_api.py` | 37 | Login flow (CSRF extraction, POST, redirects), account discovery (scraping account divs), hourly data fetch (JSON parsing, tariff selection), error handling (auth failure, connection error, missing accounts, stale cached IDs) |
| `test_coordinator.py` | 22 | First refresh (30-day backfill), subsequent refresh (7-day lookback), statistics import (cumulative sums, overlap detection), auth failure → `ConfigEntryAuthFailed`, connection failure → `UpdateFailed`, meter ID caching, state logging transitions |
| `test_config_flow.py` | 21 | User step (happy path, invalid auth, connection error, unknown error), account selection (single/multiple accounts), reauth flow (success, failure), reconfigure flow (password change, meter ID rediscovery), unique ID abort |
| `test_sensor.py` | 9 | Entity creation, native_value correctness, unique_id format, device_info structure, entity_category = DIAGNOSTIC, disabled_by_default = True |
| `test_init.py` | 4 | Setup success, unload success, v1→v2 migration, setup failure handling |
| `test_diagnostics.py` | 4 | Diagnostics data structure, credential redaction, meter ID redaction, coordinator data inclusion |

## CONVENTIONS

- **Naming**: `test_{module}.py` mirrors integration module names.
- **Async**: All test functions are async by default (`asyncio_mode = "auto"` in pyproject.toml). No `@pytest.mark.asyncio` needed.
- **Fixtures**: Shared fixtures in `conftest.py`. Test-specific fixtures inline in test files.
- **Assertions**: Direct `assert` statements. Use `pytest.raises` for expected exceptions.
- **Statistics verification**: Use `get_instance(hass).async_add_executor_job(statistics_during_period, ...)` to verify recorder state.
- **Coverage**: `--cov-fail-under=95` enforced in CI. `types.py` is excluded (TypedDict-only file).

## TDD WORKFLOW (MANDATORY)

Every code change follows this cycle:

1. **RED**: Write a failing test that captures expected behavior
2. **GREEN**: Write minimal code to pass the test
3. **REFACTOR**: Clean up, tests must stay green
4. **VERIFY**: `pytest tests/ --cov-fail-under=95 -q && mypy --strict`

## ANTI-PATTERNS

- **NEVER** mock internal logic (HTML parsing, stat calculation, coordinator update flow).
- **NEVER** skip coverage checks — CI enforces >=95%.
- **NEVER** use `@pytest.mark.asyncio` — `asyncio_mode = "auto"` handles it.
- **NEVER** create real network connections in tests — always `aioresponses`.
- **NEVER** delete or weaken tests to make CI pass — fix the code.
