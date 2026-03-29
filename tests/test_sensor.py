# pyright: reportMissingImports=false
"""Tests for Electric Ireland diagnostic entities."""
from unittest.mock import MagicMock
from datetime import datetime, timezone

from homeassistant.const import EntityCategory

from custom_components.electric_ireland_insights.sensor import (
    ElectricIrelandDiagnosticSensor,
    DIAGNOSTIC_SENSORS,
)
from custom_components.electric_ireland_insights.coordinator import ElectricIrelandCoordinator


UTC = timezone.utc


async def test_diagnostic_entities_created(hass, enable_custom_integrations, mock_config_entry):
    mock_config_entry.add_to_hass(hass)
    assert len(DIAGNOSTIC_SENSORS) == 2
    keys = {d.key for d in DIAGNOSTIC_SENSORS}
    assert "last_import_time" in keys
    assert "data_freshness_days" in keys


async def test_entity_category_is_diagnostic(hass, enable_custom_integrations, mock_config_entry):
    for desc in DIAGNOSTIC_SENSORS:
        assert desc.entity_category == EntityCategory.DIAGNOSTIC


async def test_last_import_time_value(hass, enable_custom_integrations, mock_config_entry):
    mock_config_entry.add_to_hass(hass)
    mock_coordinator = MagicMock(spec=ElectricIrelandCoordinator)
    expected_ts = datetime(2026, 3, 23, 12, 0, 0, tzinfo=UTC)
    mock_coordinator.data = {
        "last_import": expected_ts,
        "datapoint_count": 24,
        "latest_data_timestamp": datetime(2026, 3, 23, 0, 0, 0, tzinfo=UTC),
        "import_error": None,
    }
    mock_coordinator.hass = hass
    mock_coordinator.config_entry = mock_config_entry

    last_import_desc = next(d for d in DIAGNOSTIC_SENSORS if d.key == "last_import_time")
    sensor = ElectricIrelandDiagnosticSensor(mock_coordinator, last_import_desc, "951785073")
    assert sensor.native_value == expected_ts


async def test_data_freshness_returns_none_when_no_timestamp(hass, enable_custom_integrations, mock_config_entry):
    mock_config_entry.add_to_hass(hass)
    mock_coordinator = MagicMock(spec=ElectricIrelandCoordinator)
    mock_coordinator.data = {
        "last_import": None,
        "datapoint_count": 0,
        "latest_data_timestamp": None,
        "import_error": None,
    }
    mock_coordinator.hass = hass
    mock_coordinator.config_entry = mock_config_entry

    freshness_desc = next(d for d in DIAGNOSTIC_SENSORS if d.key == "data_freshness_days")
    sensor = ElectricIrelandDiagnosticSensor(mock_coordinator, freshness_desc, "951785073")
    assert sensor.native_value is None


async def test_native_value_none_when_coordinator_data_none(hass, enable_custom_integrations, mock_config_entry):
    mock_config_entry.add_to_hass(hass)
    mock_coordinator = MagicMock(spec=ElectricIrelandCoordinator)
    mock_coordinator.data = None
    mock_coordinator.hass = hass
    mock_coordinator.config_entry = mock_config_entry

    last_import_desc = next(d for d in DIAGNOSTIC_SENSORS if d.key == "last_import_time")
    sensor = ElectricIrelandDiagnosticSensor(mock_coordinator, last_import_desc, "951785073")
    assert sensor.native_value is None


async def test_unique_id_format(hass, enable_custom_integrations, mock_config_entry):
    mock_config_entry.add_to_hass(hass)
    mock_coordinator = MagicMock(spec=ElectricIrelandCoordinator)
    mock_coordinator.data = {"last_import": None, "latest_data_timestamp": None, "import_error": None}
    mock_coordinator.hass = hass
    mock_coordinator.config_entry = mock_config_entry

    last_import_desc = next(d for d in DIAGNOSTIC_SENSORS if d.key == "last_import_time")
    sensor = ElectricIrelandDiagnosticSensor(mock_coordinator, last_import_desc, "951785073")
    assert sensor.unique_id == "electric_ireland_insights_951785073_last_import_time"


async def test_device_info_has_account(hass, enable_custom_integrations, mock_config_entry):
    mock_config_entry.add_to_hass(hass)
    mock_coordinator = MagicMock(spec=ElectricIrelandCoordinator)
    mock_coordinator.data = {"last_import": None, "latest_data_timestamp": None, "import_error": None}
    mock_coordinator.hass = hass
    mock_coordinator.config_entry = mock_config_entry

    last_import_desc = next(d for d in DIAGNOSTIC_SENSORS if d.key == "last_import_time")
    sensor = ElectricIrelandDiagnosticSensor(mock_coordinator, last_import_desc, "951785073")
    assert ("electric_ireland_insights", "951785073") in sensor.device_info["identifiers"]


async def test_has_entity_name_is_true(hass, enable_custom_integrations, mock_config_entry):
    mock_config_entry.add_to_hass(hass)
    mock_coordinator = MagicMock(spec=ElectricIrelandCoordinator)
    mock_coordinator.data = {"last_import": None, "latest_data_timestamp": None, "import_error": None}
    mock_coordinator.hass = hass
    mock_coordinator.config_entry = mock_config_entry

    last_import_desc = next(d for d in DIAGNOSTIC_SENSORS if d.key == "last_import_time")
    sensor = ElectricIrelandDiagnosticSensor(mock_coordinator, last_import_desc, "951785073")
    assert sensor._attr_has_entity_name is True
