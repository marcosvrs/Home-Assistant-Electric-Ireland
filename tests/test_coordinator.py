"""Tests for the Electric Ireland coordinator."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.statistics import statistics_during_period
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import UpdateFailed
from pytest_homeassistant_custom_component.components.recorder.common import (
    async_wait_recording_done,
)

from custom_components.electric_ireland_insights.const import (
    DOMAIN,
    INITIAL_LOOKBACK_DAYS,
    LOOKUP_DAYS,
)
from custom_components.electric_ireland_insights.exceptions import (
    CannotConnect,
    InvalidAuth,
)

UTC = UTC
ACCOUNT = "951785073"
STAT_ID_CONSUMPTION = f"{DOMAIN}:{ACCOUNT}_consumption"
STAT_ID_COST = f"{DOMAIN}:{ACCOUNT}_cost"


def make_datapoints(n_days=1, base_ts=1774224000):
    """Create n_days * 24 hourly datapoints."""
    dps = []
    for day in range(n_days):
        for hour in range(24):
            ts = base_ts + day * 86400 + hour * 3600
            dps.append(
                {
                    "consumption": round(0.5 + hour * 0.1, 2),
                    "cost": round(0.1 + hour * 0.02, 2),
                    "intervalEnd": ts,
                }
            )
    return dps


# ---------------------------------------------------------------------------
# Test 1: First run uses 30-day lookback when no stats exist
# ---------------------------------------------------------------------------


async def test_first_run_imports_30_days(recorder_mock, hass, mock_config_entry):
    """Test first run uses 30-day lookback when no stats exist."""
    mock_config_entry.add_to_hass(hass)

    with (
        patch(
            "custom_components.electric_ireland_insights.coordinator.get_last_statistics",
            return_value={},
        ),
        patch("custom_components.electric_ireland_insights.coordinator.ElectricIrelandAPI") as mock_api_class,
        patch("custom_components.electric_ireland_insights.coordinator.async_create_clientsession"),
    ):
        mock_api_instance = AsyncMock()
        mock_api_instance.fetch_day_range = AsyncMock(return_value=(make_datapoints(30), None))
        mock_api_class.return_value = mock_api_instance

        from custom_components.electric_ireland_insights.coordinator import (
            ElectricIrelandCoordinator,
        )

        coordinator = ElectricIrelandCoordinator(hass, mock_config_entry)
        await coordinator._async_update_data()

        mock_api_instance.fetch_day_range.assert_called_once()
        call_kwargs = mock_api_instance.fetch_day_range.call_args
        assert call_kwargs.kwargs.get("lookback_days") == INITIAL_LOOKBACK_DAYS or (
            call_kwargs.args and call_kwargs.args[-1] == INITIAL_LOOKBACK_DAYS
        )


# ---------------------------------------------------------------------------
# Test 2: Subsequent run uses 7-day lookback when stats already exist
# ---------------------------------------------------------------------------


async def test_subsequent_run_imports_7_days(recorder_mock, hass, mock_config_entry):
    """Test subsequent run uses 7-day lookback when stats already exist."""
    mock_config_entry.add_to_hass(hass)

    with (
        patch(
            "custom_components.electric_ireland_insights.coordinator.get_last_statistics",
            return_value={STAT_ID_CONSUMPTION: [{"sum": 100.0}]},
        ),
        patch("custom_components.electric_ireland_insights.coordinator.ElectricIrelandAPI") as mock_api_class,
        patch("custom_components.electric_ireland_insights.coordinator.async_create_clientsession"),
    ):
        mock_api_instance = AsyncMock()
        mock_api_instance.fetch_day_range = AsyncMock(return_value=(make_datapoints(7), None))
        mock_api_class.return_value = mock_api_instance

        from custom_components.electric_ireland_insights.coordinator import (
            ElectricIrelandCoordinator,
        )

        coordinator = ElectricIrelandCoordinator(hass, mock_config_entry)
        await coordinator._async_update_data()

        mock_api_instance.fetch_day_range.assert_called_once()
        call_kwargs = mock_api_instance.fetch_day_range.call_args
        assert call_kwargs.kwargs.get("lookback_days") == LOOKUP_DAYS or (
            call_kwargs.args and call_kwargs.args[-1] == LOOKUP_DAYS
        )


# ---------------------------------------------------------------------------
# Test 3: Consumption statistics have correct sum and state values
# ---------------------------------------------------------------------------


async def test_consumption_statistics_correct(recorder_mock, hass, mock_config_entry):
    """Test consumption statistics are imported with correct sum/state values."""
    mock_config_entry.add_to_hass(hass)

    datapoints = make_datapoints(1)

    with (
        patch(
            "custom_components.electric_ireland_insights.coordinator.get_last_statistics",
            return_value={},
        ),
        patch("custom_components.electric_ireland_insights.coordinator.ElectricIrelandAPI") as mock_api_class,
        patch("custom_components.electric_ireland_insights.coordinator.async_create_clientsession"),
    ):
        mock_api_instance = AsyncMock()
        mock_api_instance.fetch_day_range = AsyncMock(return_value=(datapoints, None))
        mock_api_class.return_value = mock_api_instance

        from custom_components.electric_ireland_insights.coordinator import (
            ElectricIrelandCoordinator,
        )

        coordinator = ElectricIrelandCoordinator(hass, mock_config_entry)
        await coordinator._async_update_data()

    await async_wait_recording_done(hass)

    start = datetime(2026, 3, 23, 0, 0, tzinfo=UTC)
    end = datetime(2026, 3, 24, 0, 0, tzinfo=UTC)
    stats = await get_instance(hass).async_add_executor_job(
        statistics_during_period,
        hass,
        start,
        end,
        {STAT_ID_CONSUMPTION},
        "hour",
        None,
        {"sum", "state"},
    )
    assert STAT_ID_CONSUMPTION in stats
    assert len(stats[STAT_ID_CONSUMPTION]) == 24

    last_sum = stats[STAT_ID_CONSUMPTION][-1]["sum"]
    expected_total = sum(dp["consumption"] for dp in datapoints)
    assert abs(last_sum - expected_total) < 0.01


# ---------------------------------------------------------------------------
# Test 4: Cost statistics have correct values with EUR unit
# ---------------------------------------------------------------------------


async def test_cost_statistics_correct(recorder_mock, hass, mock_config_entry):
    """Test cost statistics are imported with correct sum/state and EUR unit."""
    mock_config_entry.add_to_hass(hass)

    datapoints = make_datapoints(1)

    with (
        patch(
            "custom_components.electric_ireland_insights.coordinator.get_last_statistics",
            return_value={},
        ),
        patch("custom_components.electric_ireland_insights.coordinator.ElectricIrelandAPI") as mock_api_class,
        patch("custom_components.electric_ireland_insights.coordinator.async_create_clientsession"),
    ):
        mock_api_instance = AsyncMock()
        mock_api_instance.fetch_day_range = AsyncMock(return_value=(datapoints, None))
        mock_api_class.return_value = mock_api_instance

        from custom_components.electric_ireland_insights.coordinator import (
            ElectricIrelandCoordinator,
        )

        coordinator = ElectricIrelandCoordinator(hass, mock_config_entry)
        await coordinator._async_update_data()

    await async_wait_recording_done(hass)

    start = datetime(2026, 3, 23, 0, 0, tzinfo=UTC)
    end = datetime(2026, 3, 24, 0, 0, tzinfo=UTC)
    stats = await get_instance(hass).async_add_executor_job(
        statistics_during_period,
        hass,
        start,
        end,
        {STAT_ID_COST},
        "hour",
        None,
        {"sum", "state"},
    )
    assert STAT_ID_COST in stats
    assert len(stats[STAT_ID_COST]) == 24

    last_sum = stats[STAT_ID_COST][-1]["sum"]
    expected_total = sum(dp["cost"] for dp in datapoints)
    assert abs(last_sum - expected_total) < 0.01


# ---------------------------------------------------------------------------
# Test 5: Statistic IDs follow the expected format
# ---------------------------------------------------------------------------


async def test_statistic_id_format(recorder_mock, hass, mock_config_entry):
    """Test statistic IDs match the expected domain:account_metric format."""
    mock_config_entry.add_to_hass(hass)

    with (
        patch(
            "custom_components.electric_ireland_insights.coordinator.get_last_statistics",
            return_value={},
        ),
        patch("custom_components.electric_ireland_insights.coordinator.ElectricIrelandAPI") as mock_api_class,
        patch("custom_components.electric_ireland_insights.coordinator.async_create_clientsession"),
    ):
        mock_api_instance = AsyncMock()
        mock_api_instance.fetch_day_range = AsyncMock(return_value=(make_datapoints(1), None))
        mock_api_class.return_value = mock_api_instance

        from custom_components.electric_ireland_insights.coordinator import (
            ElectricIrelandCoordinator,
        )

        coordinator = ElectricIrelandCoordinator(hass, mock_config_entry)
        await coordinator._async_update_data()

    await async_wait_recording_done(hass)

    start = datetime(2026, 3, 23, 0, 0, tzinfo=UTC)
    end = datetime(2026, 3, 24, 0, 0, tzinfo=UTC)
    stats = await get_instance(hass).async_add_executor_job(
        statistics_during_period,
        hass,
        start,
        end,
        {STAT_ID_CONSUMPTION},
        "hour",
        None,
        {"sum", "state"},
    )

    assert "electric_ireland_insights:951785073_consumption" in stats

    assert STAT_ID_CONSUMPTION.startswith(f"{DOMAIN}:")


# ---------------------------------------------------------------------------
# Test 6: Interval start is aligned to the hour (not the raw intervalEnd)
# ---------------------------------------------------------------------------


async def test_interval_start_alignment(recorder_mock, hass, mock_config_entry):
    """Test that interval start is aligned to hour boundary, not raw intervalEnd."""
    mock_config_entry.add_to_hass(hass)

    # intervalEnd=1774227599 is 2026-03-23T00:59:59Z — must align to hour start
    datapoints = [
        {
            "consumption": 0.5,
            "cost": 0.1,
            "intervalEnd": 1774227599,
        }
    ]

    with (
        patch(
            "custom_components.electric_ireland_insights.coordinator.get_last_statistics",
            return_value={},
        ),
        patch("custom_components.electric_ireland_insights.coordinator.ElectricIrelandAPI") as mock_api_class,
        patch("custom_components.electric_ireland_insights.coordinator.async_create_clientsession"),
    ):
        mock_api_instance = AsyncMock()
        mock_api_instance.fetch_day_range = AsyncMock(return_value=(datapoints, None))
        mock_api_class.return_value = mock_api_instance

        from custom_components.electric_ireland_insights.coordinator import (
            ElectricIrelandCoordinator,
        )

        coordinator = ElectricIrelandCoordinator(hass, mock_config_entry)
        await coordinator._async_update_data()

    await async_wait_recording_done(hass)

    start = datetime(2026, 3, 23, 0, 0, 0, tzinfo=UTC)
    end = datetime(2026, 3, 23, 1, 0, 0, tzinfo=UTC)
    stats = await get_instance(hass).async_add_executor_job(
        statistics_during_period,
        hass,
        start,
        end,
        {STAT_ID_CONSUMPTION},
        "hour",
        None,
        {"sum", "state"},
    )

    assert STAT_ID_CONSUMPTION in stats
    assert len(stats[STAT_ID_CONSUMPTION]) == 1
    stat_entry = stats[STAT_ID_CONSUMPTION][0]
    assert stat_entry["start"] == start.timestamp()


# ---------------------------------------------------------------------------
# Test 7: Sum continuity across multiple coordinator runs
# ---------------------------------------------------------------------------


async def test_sum_continuity_across_runs(recorder_mock, hass, mock_config_entry):
    """Test that cumulative sum continues from previous run, not restarting from 0."""
    mock_config_entry.add_to_hass(hass)

    first_run_data = make_datapoints(7, base_ts=1774224000)
    second_run_data = make_datapoints(7, base_ts=1774224000 + 7 * 86400)

    first_run_total = sum(dp["consumption"] for dp in first_run_data)

    with (
        patch(
            "custom_components.electric_ireland_insights.coordinator.get_last_statistics",
        ) as mock_get_last,
        patch("custom_components.electric_ireland_insights.coordinator.ElectricIrelandAPI") as mock_api_class,
        patch("custom_components.electric_ireland_insights.coordinator.async_create_clientsession"),
    ):
        mock_api_instance = AsyncMock()
        mock_api_class.return_value = mock_api_instance

        from custom_components.electric_ireland_insights.coordinator import (
            ElectricIrelandCoordinator,
        )

        mock_get_last.return_value = {}
        mock_api_instance.fetch_day_range = AsyncMock(return_value=(first_run_data, None))

        coordinator = ElectricIrelandCoordinator(hass, mock_config_entry)
        await coordinator._async_update_data()

        await get_instance(hass).async_add_executor_job(lambda: None)
        await hass.async_block_till_done()

        mock_get_last.return_value = {STAT_ID_CONSUMPTION: [{"sum": first_run_total}]}
        mock_api_instance.fetch_day_range = AsyncMock(return_value=(second_run_data, None))

        await coordinator._async_update_data()

        await get_instance(hass).async_add_executor_job(lambda: None)
        await hass.async_block_till_done()

    start = datetime(2026, 3, 23, 0, 0, tzinfo=UTC)
    end = datetime(2026, 4, 6, 0, 0, tzinfo=UTC)
    stats = await get_instance(hass).async_add_executor_job(
        statistics_during_period,
        hass,
        start,
        end,
        {STAT_ID_CONSUMPTION},
        "hour",
        None,
        {"sum"},
    )

    assert STAT_ID_CONSUMPTION in stats
    all_entries = stats[STAT_ID_CONSUMPTION]
    final_sum = all_entries[-1]["sum"]
    assert final_sum > first_run_total


# ---------------------------------------------------------------------------
# Test 8: InvalidAuth raises ConfigEntryAuthFailed
# ---------------------------------------------------------------------------


async def test_auth_error_raises_config_entry_auth_failed(hass, mock_config_entry):
    """Test that InvalidAuth from API raises ConfigEntryAuthFailed."""
    mock_config_entry.add_to_hass(hass)

    with (
        patch(
            "custom_components.electric_ireland_insights.coordinator.get_last_statistics",
            return_value={},
        ),
        patch("custom_components.electric_ireland_insights.coordinator.ElectricIrelandAPI") as mock_api_class,
        patch("custom_components.electric_ireland_insights.coordinator.async_create_clientsession"),
    ):
        mock_api_instance = AsyncMock()
        mock_api_instance.fetch_day_range = AsyncMock(side_effect=InvalidAuth("Invalid credentials"))
        mock_api_class.return_value = mock_api_instance

        from custom_components.electric_ireland_insights.coordinator import (
            ElectricIrelandCoordinator,
        )

        coordinator = ElectricIrelandCoordinator(hass, mock_config_entry)

        with pytest.raises(ConfigEntryAuthFailed):
            await coordinator._async_update_data()


# ---------------------------------------------------------------------------
# Test 9: CannotConnect raises UpdateFailed
# ---------------------------------------------------------------------------


async def test_connection_error_raises_update_failed(hass, mock_config_entry):
    """Test that CannotConnect from API raises UpdateFailed."""
    mock_config_entry.add_to_hass(hass)

    with (
        patch(
            "custom_components.electric_ireland_insights.coordinator.get_last_statistics",
            return_value={},
        ),
        patch("custom_components.electric_ireland_insights.coordinator.ElectricIrelandAPI") as mock_api_class,
        patch("custom_components.electric_ireland_insights.coordinator.async_create_clientsession"),
    ):
        mock_api_instance = AsyncMock()
        mock_api_instance.fetch_day_range = AsyncMock(side_effect=CannotConnect("Connection refused"))
        mock_api_class.return_value = mock_api_instance

        from custom_components.electric_ireland_insights.coordinator import (
            ElectricIrelandCoordinator,
        )

        coordinator = ElectricIrelandCoordinator(hass, mock_config_entry)

        with pytest.raises(UpdateFailed):
            await coordinator._async_update_data()


# ---------------------------------------------------------------------------
# Test 10: Empty data from API inserts no statistics
# ---------------------------------------------------------------------------


async def test_empty_data_no_statistics(recorder_mock, hass, mock_config_entry):
    """Test that empty API response inserts no statistics and raises no error."""
    mock_config_entry.add_to_hass(hass)

    with (
        patch(
            "custom_components.electric_ireland_insights.coordinator.get_last_statistics",
            return_value={},
        ),
        patch("custom_components.electric_ireland_insights.coordinator.ElectricIrelandAPI") as mock_api_class,
        patch("custom_components.electric_ireland_insights.coordinator.async_create_clientsession"),
    ):
        mock_api_instance = AsyncMock()
        mock_api_instance.fetch_day_range = AsyncMock(return_value=([], None))
        mock_api_class.return_value = mock_api_instance

        from custom_components.electric_ireland_insights.coordinator import (
            ElectricIrelandCoordinator,
        )

        coordinator = ElectricIrelandCoordinator(hass, mock_config_entry)
        await coordinator._async_update_data()

    await async_wait_recording_done(hass)

    start = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
    end = datetime(2026, 12, 31, 0, 0, tzinfo=UTC)
    stats = await get_instance(hass).async_add_executor_job(
        statistics_during_period,
        hass,
        start,
        end,
        {STAT_ID_CONSUMPTION},
        "hour",
        None,
        {"sum", "state"},
    )

    assert STAT_ID_CONSUMPTION not in stats or len(stats[STAT_ID_CONSUMPTION]) == 0


# ---------------------------------------------------------------------------
# Test 11: Coordinator fetches data even without entity listeners
# ---------------------------------------------------------------------------


async def test_imports_continue_without_entity_listeners(recorder_mock, hass, mock_config_entry):
    """Test that coordinator fetches data even when no entities are subscribed."""
    mock_config_entry.add_to_hass(hass)

    with (
        patch(
            "custom_components.electric_ireland_insights.coordinator.get_last_statistics",
            return_value={},
        ),
        patch("custom_components.electric_ireland_insights.coordinator.ElectricIrelandAPI") as mock_api_class,
        patch("custom_components.electric_ireland_insights.coordinator.async_create_clientsession"),
    ):
        mock_api_instance = AsyncMock()
        mock_api_instance.fetch_day_range = AsyncMock(return_value=(make_datapoints(1), None))
        mock_api_class.return_value = mock_api_instance

        from custom_components.electric_ireland_insights.coordinator import (
            ElectricIrelandCoordinator,
        )

        coordinator = ElectricIrelandCoordinator(hass, mock_config_entry)

        unsub = coordinator.async_add_listener(lambda: None)

        await coordinator.async_refresh()

        mock_api_instance.fetch_day_range.assert_called()

        unsub()


# ===========================================================================
# SCRAPE-ONCE + SILENT FAILURE TESTS (T5 RED PHASE)
# ===========================================================================


async def test_cached_ids_skip_html_discovery(recorder_mock, hass, mock_config_entry):
    """Test that cached meter IDs skip HTML discovery but still log in."""
    mock_config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        mock_config_entry,
        data={
            **dict(mock_config_entry.data),
            "partner_id": "P1",
            "contract_id": "C1",
            "premise_id": "PR1",
        },
    )

    with (
        patch(
            "custom_components.electric_ireland_insights.coordinator.get_last_statistics",
            return_value={},
        ),
        patch("custom_components.electric_ireland_insights.coordinator.ElectricIrelandAPI") as mock_api_class,
        patch("custom_components.electric_ireland_insights.coordinator.async_create_clientsession"),
    ):
        mock_api_instance = AsyncMock()
        mock_api_instance.fetch_day_range = AsyncMock(return_value=(make_datapoints(7), None))
        mock_api_class.return_value = mock_api_instance

        from custom_components.electric_ireland_insights.coordinator import (
            ElectricIrelandCoordinator,
        )

        coordinator = ElectricIrelandCoordinator(hass, mock_config_entry)
        await coordinator._async_update_data()

        call_kwargs = mock_api_instance.fetch_day_range.call_args
        assert call_kwargs.kwargs.get("meter_ids") is not None or (
            len(call_kwargs.args) >= 3 and call_kwargs.args[2] is not None
        ), "fetch_day_range should be called with cached meter_ids"


async def test_no_cached_ids_triggers_full_login(recorder_mock, hass, mock_config_entry):
    """Test that missing cached IDs trigger full login with HTML discovery."""
    mock_config_entry.add_to_hass(hass)

    with (
        patch(
            "custom_components.electric_ireland_insights.coordinator.get_last_statistics",
            return_value={},
        ),
        patch("custom_components.electric_ireland_insights.coordinator.ElectricIrelandAPI") as mock_api_class,
        patch("custom_components.electric_ireland_insights.coordinator.async_create_clientsession"),
    ):
        mock_api_instance = AsyncMock()
        mock_api_instance.fetch_day_range = AsyncMock(
            return_value=(make_datapoints(30), {"partner": "P1", "contract": "C1", "premise": "PR1"})
        )
        mock_api_class.return_value = mock_api_instance

        from custom_components.electric_ireland_insights.coordinator import (
            ElectricIrelandCoordinator,
        )

        coordinator = ElectricIrelandCoordinator(hass, mock_config_entry)
        await coordinator._async_update_data()

        call_kwargs = mock_api_instance.fetch_day_range.call_args
        passed_meter_ids = call_kwargs.kwargs.get("meter_ids")
        assert passed_meter_ids is None, "No cached IDs: fetch_day_range should be called with meter_ids=None"


async def test_cached_ids_fallback_to_full_login(recorder_mock, hass, mock_config_entry):
    """Test that cached ID failure falls back to full login within same cycle."""
    mock_config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        mock_config_entry,
        data={
            **dict(mock_config_entry.data),
            "partner_id": "STALE_P1",
            "contract_id": "STALE_C1",
            "premise_id": "STALE_PR1",
        },
    )

    with (
        patch(
            "custom_components.electric_ireland_insights.coordinator.get_last_statistics",
            return_value={},
        ),
        patch("custom_components.electric_ireland_insights.coordinator.ElectricIrelandAPI") as mock_api_class,
        patch("custom_components.electric_ireland_insights.coordinator.async_create_clientsession"),
    ):
        mock_api_instance = AsyncMock()
        mock_api_instance.fetch_day_range = AsyncMock(
            return_value=(make_datapoints(7), {"partner": "NEW_P1", "contract": "NEW_C1", "premise": "NEW_PR1"})
        )
        mock_api_class.return_value = mock_api_instance

        from custom_components.electric_ireland_insights.coordinator import (
            ElectricIrelandCoordinator,
        )

        coordinator = ElectricIrelandCoordinator(hass, mock_config_entry)
        await coordinator._async_update_data()

        assert hass.config_entries.async_get_entry(mock_config_entry.entry_id).data.get("partner_id") == "NEW_P1", (
            "New meter IDs from fallback should be stored in entry.data"
        )


async def test_fallback_updates_cached_ids(recorder_mock, hass, mock_config_entry):
    """Test that fallback discovery updates cached IDs in entry.data."""
    mock_config_entry.add_to_hass(hass)

    with (
        patch(
            "custom_components.electric_ireland_insights.coordinator.get_last_statistics",
            return_value={},
        ),
        patch("custom_components.electric_ireland_insights.coordinator.ElectricIrelandAPI") as mock_api_class,
        patch("custom_components.electric_ireland_insights.coordinator.async_create_clientsession"),
    ):
        mock_api_instance = AsyncMock()
        new_ids = {"partner": "P_NEW", "contract": "C_NEW", "premise": "PR_NEW"}
        mock_api_instance.fetch_day_range = AsyncMock(return_value=(make_datapoints(30), new_ids))
        mock_api_class.return_value = mock_api_instance

        from custom_components.electric_ireland_insights.coordinator import (
            ElectricIrelandCoordinator,
        )

        coordinator = ElectricIrelandCoordinator(hass, mock_config_entry)
        await coordinator._async_update_data()

        entry = hass.config_entries.async_get_entry(mock_config_entry.entry_id)
        assert entry.data.get("partner_id") == "P_NEW"
        assert entry.data.get("contract_id") == "C_NEW"
        assert entry.data.get("premise_id") == "PR_NEW"


async def test_api_redirect_clears_and_falls_back(recorder_mock, hass, mock_config_entry):
    """Test that a redirect-to-login response causes fallback to full login."""
    mock_config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        mock_config_entry,
        data={
            **dict(mock_config_entry.data),
            "partner_id": "P1",
            "contract_id": "C1",
            "premise_id": "PR1",
        },
    )

    with (
        patch(
            "custom_components.electric_ireland_insights.coordinator.get_last_statistics",
            return_value={},
        ),
        patch("custom_components.electric_ireland_insights.coordinator.ElectricIrelandAPI") as mock_api_class,
        patch("custom_components.electric_ireland_insights.coordinator.async_create_clientsession"),
    ):
        mock_api_instance = AsyncMock()
        mock_api_instance.fetch_day_range = AsyncMock(
            return_value=(make_datapoints(7), {"partner": "P2", "contract": "C2", "premise": "PR2"})
        )
        mock_api_class.return_value = mock_api_instance

        from custom_components.electric_ireland_insights.coordinator import (
            ElectricIrelandCoordinator,
        )

        coordinator = ElectricIrelandCoordinator(hass, mock_config_entry)
        result = await coordinator._async_update_data()
        assert result is not None


async def test_empty_data_subsequent_run_no_update(recorder_mock, hass, mock_config_entry):
    """Test that empty data on subsequent runs doesn't update last_import."""
    mock_config_entry.add_to_hass(hass)

    with (
        patch(
            "custom_components.electric_ireland_insights.coordinator.get_last_statistics",
            return_value={"some_stat": [{"sum": 100.0}]},
        ),
        patch("custom_components.electric_ireland_insights.coordinator.ElectricIrelandAPI") as mock_api_class,
        patch("custom_components.electric_ireland_insights.coordinator.async_create_clientsession"),
    ):
        mock_api_instance = AsyncMock()
        mock_api_instance.fetch_day_range = AsyncMock(return_value=([], None))
        mock_api_class.return_value = mock_api_instance

        from custom_components.electric_ireland_insights.coordinator import (
            ElectricIrelandCoordinator,
        )

        coordinator = ElectricIrelandCoordinator(hass, mock_config_entry)

        from datetime import UTC
        from datetime import datetime as dt

        coordinator.data = {
            "last_import": dt(2026, 3, 28, 12, 0, tzinfo=UTC),
            "datapoint_count": 24,
            "latest_data_timestamp": dt(2026, 3, 26, 0, 0, tzinfo=UTC),
            "import_error": None,
        }
        coordinator._has_imported_before = True

        result = await coordinator._async_update_data()

        assert result["last_import"] == dt(2026, 3, 28, 12, 0, tzinfo=UTC), (
            "Empty subsequent run should not update last_import"
        )


async def test_empty_data_restart_returns_synthetic(recorder_mock, hass, mock_config_entry):
    """Test empty data after restart returns synthetic stale dict when _has_imported_before is True."""
    mock_config_entry.add_to_hass(hass)

    with (
        patch(
            "custom_components.electric_ireland_insights.coordinator.get_last_statistics",
            return_value={"some_stat": [{"sum": 100.0}]},
        ),
        patch("custom_components.electric_ireland_insights.coordinator.ElectricIrelandAPI") as mock_api_class,
        patch("custom_components.electric_ireland_insights.coordinator.async_create_clientsession"),
    ):
        mock_api_instance = AsyncMock()
        mock_api_instance.fetch_day_range = AsyncMock(return_value=([], None))
        mock_api_class.return_value = mock_api_instance

        from custom_components.electric_ireland_insights.coordinator import (
            ElectricIrelandCoordinator,
        )

        coordinator = ElectricIrelandCoordinator(hass, mock_config_entry)
        assert coordinator.data is None

        result = await coordinator._async_update_data()

        assert result is not None
        assert result.get("last_import") is None
        assert result.get("datapoint_count") == 0
        assert result.get("import_error") is not None


async def test_connection_restored_logging(recorder_mock, hass, mock_config_entry):
    """Test that _last_update_success transitions from False to True on success."""
    mock_config_entry.add_to_hass(hass)

    with (
        patch(
            "custom_components.electric_ireland_insights.coordinator.get_last_statistics",
            return_value={},
        ),
        patch("custom_components.electric_ireland_insights.coordinator.ElectricIrelandAPI") as mock_api_class,
        patch("custom_components.electric_ireland_insights.coordinator.async_create_clientsession"),
    ):
        mock_api_instance = AsyncMock()
        mock_api_instance.fetch_day_range = AsyncMock(return_value=(make_datapoints(1), None))
        mock_api_class.return_value = mock_api_instance

        from custom_components.electric_ireland_insights.coordinator import ElectricIrelandCoordinator

        coordinator = ElectricIrelandCoordinator(hass, mock_config_entry)
        coordinator._last_update_success = False  # simulate prior failure

        with patch.object(coordinator, "_insert_statistics", new_callable=AsyncMock):
            result = await coordinator._async_update_data()

        assert coordinator._last_update_success is True
        assert result is not None


async def test_update_failed_reraise(recorder_mock, hass, mock_config_entry):
    """Test UpdateFailed from _insert_statistics is re-raised through except block."""
    from homeassistant.helpers.update_coordinator import UpdateFailed

    mock_config_entry.add_to_hass(hass)

    with (
        patch(
            "custom_components.electric_ireland_insights.coordinator.get_last_statistics",
            return_value={},
        ),
        patch("custom_components.electric_ireland_insights.coordinator.ElectricIrelandAPI") as mock_api_class,
        patch("custom_components.electric_ireland_insights.coordinator.async_create_clientsession"),
    ):
        mock_api_instance = AsyncMock()
        mock_api_instance.fetch_day_range = AsyncMock(return_value=(make_datapoints(1), None))
        mock_api_class.return_value = mock_api_instance

        from custom_components.electric_ireland_insights.coordinator import ElectricIrelandCoordinator

        coordinator = ElectricIrelandCoordinator(hass, mock_config_entry)

        with (
            patch.object(
                coordinator, "_insert_statistics", new_callable=AsyncMock, side_effect=UpdateFailed("insert failed")
            ),
            pytest.raises(UpdateFailed),
        ):
            await coordinator._async_update_data()

        assert coordinator._last_update_success is False


async def test_unexpected_exception_wrapped(recorder_mock, hass, mock_config_entry):
    """Test unexpected exception from fetch_day_range is wrapped in UpdateFailed."""
    from homeassistant.helpers.update_coordinator import UpdateFailed

    mock_config_entry.add_to_hass(hass)

    with (
        patch(
            "custom_components.electric_ireland_insights.coordinator.get_last_statistics",
            return_value={},
        ),
        patch("custom_components.electric_ireland_insights.coordinator.ElectricIrelandAPI") as mock_api_class,
        patch("custom_components.electric_ireland_insights.coordinator.async_create_clientsession"),
    ):
        mock_api_instance = AsyncMock()
        mock_api_instance.fetch_day_range = AsyncMock(side_effect=RuntimeError("unexpected boom"))
        mock_api_class.return_value = mock_api_instance

        from custom_components.electric_ireland_insights.coordinator import ElectricIrelandCoordinator

        coordinator = ElectricIrelandCoordinator(hass, mock_config_entry)

        with pytest.raises(UpdateFailed, match="unexpected boom"):
            await coordinator._async_update_data()

        assert coordinator._last_update_success is False


async def test_latest_timestamp_none_when_interval_zero(recorder_mock, hass, mock_config_entry):
    """Test latest_data_timestamp is None when all intervalEnd are 0 (falsy max)."""
    mock_config_entry.add_to_hass(hass)

    zero_ts_datapoints = [{"consumption": 0.5, "cost": 0.1, "intervalEnd": 0} for _ in range(3)]

    with (
        patch(
            "custom_components.electric_ireland_insights.coordinator.get_last_statistics",
            return_value={},
        ),
        patch("custom_components.electric_ireland_insights.coordinator.ElectricIrelandAPI") as mock_api_class,
        patch("custom_components.electric_ireland_insights.coordinator.async_create_clientsession"),
    ):
        mock_api_instance = AsyncMock()
        mock_api_instance.fetch_day_range = AsyncMock(return_value=(zero_ts_datapoints, None))
        mock_api_class.return_value = mock_api_instance

        from custom_components.electric_ireland_insights.coordinator import ElectricIrelandCoordinator

        coordinator = ElectricIrelandCoordinator(hass, mock_config_entry)

        with patch.object(coordinator, "_insert_statistics", new_callable=AsyncMock):
            result = await coordinator._async_update_data()

        assert result["latest_data_timestamp"] is None
