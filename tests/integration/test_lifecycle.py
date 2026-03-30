"""Full lifecycle, coordinator, multi-account, and migration tests.

Only fake: HTTP responses via aioresponses.
Real: async_setup_entry, coordinator, recorder statistics, sensor platform.
"""

from __future__ import annotations

from aioresponses import aioresponses
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.electric_ireland_insights.const import DOMAIN

from .conftest import (
    ACCOUNT_1,
    ACCOUNT_2,
    BASE_URL,
    CONTRACT,
    LOGIN_PAGE,
    LOGIN_PAGE_NO_SOURCE,
    PARTNER,
    PREMISE,
    acct_div,
    hourly_callback,
    insights_page,
    mock_ei_http,
    page,
)


def _entry(
    account: str = ACCOUNT_1,
    *,
    cached: bool = True,
    partner: str = PARTNER,
    contract: str = CONTRACT,
    premise: str = PREMISE,
    version: int = 2,
) -> MockConfigEntry:
    """Build a MockConfigEntry, optionally with cached meter IDs."""
    data: dict = {
        "username": "u@test.com",
        "password": "pass",
        "account_number": account,
    }
    if cached:
        data.update(partner_id=partner, contract_id=contract, premise_id=premise)
    return MockConfigEntry(
        domain=DOMAIN,
        data=data,
        unique_id=account,
        version=version,
    )


# ===================================================================
# Full lifecycle: setup → refresh → sensors → unload
# ===================================================================


async def test_full_setup_refresh_unload(
    recorder_mock,
    hass: HomeAssistant,
    enable_custom_integrations,
) -> None:
    entry = _entry()
    entry.add_to_hass(hass)
    db = page(acct_div(ACCOUNT_1))

    with aioresponses() as m:
        mock_ei_http(m, db, hourly_cb=hourly_callback)
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.state == ConfigEntryState.LOADED

    # Diagnostic sensors created (disabled by default, but registered)
    from homeassistant.helpers.entity_registry import async_get as er_async_get

    entity_reg = er_async_get(hass)
    entities = [e for e in entity_reg.entities.values() if e.platform == DOMAIN]
    assert len(entities) >= 2  # last_import_time + data_freshness_days

    # Clean unload
    await hass.config_entries.async_unload(entry.entry_id)
    assert entry.state == ConfigEntryState.NOT_LOADED


# ===================================================================
# Meter-ID discovery / caching
# ===================================================================


async def test_setup_discovers_and_stores_meter_ids(
    recorder_mock,
    hass: HomeAssistant,
    enable_custom_integrations,
) -> None:
    """No cached IDs → coordinator does full login → IDs stored in entry."""
    entry = _entry(cached=False)
    entry.add_to_hass(hass)
    db = page(acct_div(ACCOUNT_1))

    with aioresponses() as m:
        mock_ei_http(m, db, hourly_cb=hourly_callback)
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.state == ConfigEntryState.LOADED
    assert entry.data["partner_id"] == PARTNER
    assert entry.data["contract_id"] == CONTRACT
    assert entry.data["premise_id"] == PREMISE


async def test_setup_uses_cached_ids(
    recorder_mock,
    hass: HomeAssistant,
    enable_custom_integrations,
) -> None:
    """Cached IDs present → coordinator skips HTML account parsing."""
    entry = _entry(cached=True)
    entry.add_to_hass(hass)
    db = page(acct_div(ACCOUNT_1))

    with aioresponses() as m:
        mock_ei_http(m, db, hourly_cb=hourly_callback)
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.state == ConfigEntryState.LOADED
    # IDs unchanged — were already cached
    assert entry.data["partner_id"] == PARTNER


async def test_setup_cached_ids_fallback_to_full_login(
    recorder_mock,
    hass: HomeAssistant,
    enable_custom_integrations,
) -> None:
    """Cached IDs fail (no Source token) → fallback to full login → new IDs stored."""
    entry = _entry(cached=True, partner="OLD", contract="OLD", premise="OLD")
    entry.add_to_hass(hass)
    db = page(acct_div(ACCOUNT_1))

    with aioresponses() as m:
        # First GET / (cached login) → no Source → CachedIdsInvalid
        m.get(f"{BASE_URL}/", body=LOGIN_PAGE_NO_SOURCE, headers={"Set-Cookie": "rvt=tok1"})
        # All subsequent → normal login
        m.get(f"{BASE_URL}/", body=LOGIN_PAGE, repeat=True, headers={"Set-Cookie": "rvt=tok1"})
        m.post(f"{BASE_URL}/", body=db, repeat=True)
        m.post(f"{BASE_URL}/Accounts/OnEvent", body=insights_page(), repeat=True)

        import re as _re

        good_re = _re.compile(rf"{_re.escape(BASE_URL)}/MeterInsight/{PARTNER}/{CONTRACT}/{PREMISE}/hourly-usage")
        m.get(good_re, callback=hourly_callback, repeat=True)

        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.state == ConfigEntryState.LOADED
    # IDs updated to the real ones discovered via full login
    assert entry.data["partner_id"] == PARTNER
    assert entry.data["contract_id"] == CONTRACT


# ===================================================================
# Error handling during setup
# ===================================================================


async def test_setup_auth_failure(
    recorder_mock,
    hass: HomeAssistant,
    enable_custom_integrations,
) -> None:
    """InvalidAuth during coordinator refresh → entry in SETUP_ERROR."""
    entry = _entry(cached=False)
    entry.add_to_hass(hass)

    with aioresponses() as m:
        m.get(f"{BASE_URL}/", body=LOGIN_PAGE, repeat=True, headers={"Set-Cookie": "rvt=tok1"})
        m.post(f"{BASE_URL}/", body=page(acct_div(ACCOUNT_1)), repeat=True)
        # OnEvent returns no modelData → InvalidAuth → ConfigEntryAuthFailed
        m.post(f"{BASE_URL}/Accounts/OnEvent", body="<html><body>nope</body></html>", repeat=True)

        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.state == ConfigEntryState.SETUP_ERROR


async def test_setup_connection_failure_retries(
    recorder_mock,
    hass: HomeAssistant,
    enable_custom_integrations,
) -> None:
    """CannotConnect → entry in SETUP_RETRY."""
    entry = _entry(cached=False)
    entry.add_to_hass(hass)

    with aioresponses() as m:
        # No Source token → CannotConnect
        m.get(f"{BASE_URL}/", body="<html><body>down</body></html>", repeat=True, headers={"Set-Cookie": "rvt=tok1"})

        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.state == ConfigEntryState.SETUP_RETRY


# ===================================================================
# Multi-account
# ===================================================================


async def test_two_accounts_load_independently(
    recorder_mock,
    hass: HomeAssistant,
    enable_custom_integrations,
) -> None:
    P2, C2, PR2 = "RP2", "RC2", "RPR2"

    e1 = _entry(ACCOUNT_1)
    e1.add_to_hass(hass)

    db = page(acct_div(ACCOUNT_1), acct_div(ACCOUNT_2, partner=P2))

    with aioresponses() as m:
        mock_ei_http(m, db, hourly_cb=hourly_callback)
        import re

        url2 = re.compile(rf"{re.escape(BASE_URL)}/MeterInsight/{P2}/{C2}/{PR2}/hourly-usage")
        m.get(url2, callback=hourly_callback, repeat=True)
        m.post(f"{BASE_URL}/Accounts/OnEvent", body=insights_page(P2, C2, PR2), repeat=True)

        await hass.config_entries.async_setup(e1.entry_id)
        await hass.async_block_till_done()

        e2 = _entry(ACCOUNT_2, partner=P2, contract=C2, premise=PR2)
        e2.add_to_hass(hass)
        await hass.config_entries.async_setup(e2.entry_id)
        await hass.async_block_till_done()

    assert e1.state == ConfigEntryState.LOADED
    assert e2.state == ConfigEntryState.LOADED


async def test_unload_one_keeps_other(
    recorder_mock,
    hass: HomeAssistant,
    enable_custom_integrations,
) -> None:
    P2, C2, PR2 = "RP2", "RC2", "RPR2"

    e1 = _entry(ACCOUNT_1)
    e1.add_to_hass(hass)

    db = page(acct_div(ACCOUNT_1), acct_div(ACCOUNT_2, partner=P2))

    with aioresponses() as m:
        mock_ei_http(m, db, hourly_cb=hourly_callback)
        import re

        url2 = re.compile(rf"{re.escape(BASE_URL)}/MeterInsight/{P2}/{C2}/{PR2}/hourly-usage")
        m.get(url2, callback=hourly_callback, repeat=True)
        m.post(f"{BASE_URL}/Accounts/OnEvent", body=insights_page(P2, C2, PR2), repeat=True)

        await hass.config_entries.async_setup(e1.entry_id)
        await hass.async_block_till_done()

        e2 = _entry(ACCOUNT_2, partner=P2, contract=C2, premise=PR2)
        e2.add_to_hass(hass)
        await hass.config_entries.async_setup(e2.entry_id)
        await hass.async_block_till_done()

    await hass.config_entries.async_unload(e1.entry_id)
    assert e1.state == ConfigEntryState.NOT_LOADED
    assert e2.state == ConfigEntryState.LOADED


# ===================================================================
# Coordinator edge cases
# ===================================================================


async def test_empty_data_no_error(
    recorder_mock,
    hass: HomeAssistant,
    enable_custom_integrations,
) -> None:
    """All days return empty data → coordinator succeeds with 0 datapoints."""
    entry = _entry()
    entry.add_to_hass(hass)
    db = page(acct_div(ACCOUNT_1))

    with aioresponses() as m:
        mock_ei_http(m, db)  # hourly defaults to EMPTY_HOURLY
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.state == ConfigEntryState.LOADED
    coordinator = entry.runtime_data
    assert coordinator.data is not None
    assert coordinator.data["datapoint_count"] == 0


async def test_coordinator_populates_data_structure(
    recorder_mock,
    hass: HomeAssistant,
    enable_custom_integrations,
) -> None:
    entry = _entry()
    entry.add_to_hass(hass)
    db = page(acct_div(ACCOUNT_1))

    with aioresponses() as m:
        mock_ei_http(m, db, hourly_cb=hourly_callback)
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    data = entry.runtime_data.data
    assert "last_import" in data
    assert "datapoint_count" in data
    assert "latest_data_timestamp" in data
    assert "import_error" in data
    assert data["datapoint_count"] > 0
    assert data["last_import"] is not None
    assert data["latest_data_timestamp"] is not None


# ===================================================================
# Migration
# ===================================================================


async def test_v1_to_v2_migration(
    recorder_mock,
    hass: HomeAssistant,
    enable_custom_integrations,
) -> None:
    """V1 entry (no cached IDs) → migrated to V2 with null IDs, then setup works."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "username": "u@test.com",
            "password": "pass",
            "account_number": ACCOUNT_1,
        },
        unique_id=ACCOUNT_1,
        version=1,  # ← old version
    )
    entry.add_to_hass(hass)
    db = page(acct_div(ACCOUNT_1))

    with aioresponses() as m:
        mock_ei_http(m, db, hourly_cb=hourly_callback)
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    # Migrated to V2
    assert entry.version == 2
    # Setup succeeded after migration
    assert entry.state == ConfigEntryState.LOADED
    # Coordinator discovered IDs during setup
    assert entry.data["partner_id"] == PARTNER
