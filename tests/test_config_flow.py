"""Tests for the Electric Ireland config flow."""
import pytest
from unittest.mock import AsyncMock, patch
from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResultType

from custom_components.electric_ireland_insights.const import DOMAIN
from custom_components.electric_ireland_insights.exceptions import (
    InvalidAuth,
    CannotConnect,
    AccountNotFound,
)


async def test_user_flow_success(hass, mock_config_entry):
    """Test successful user flow creates a config entry."""
    with patch(
        "custom_components.electric_ireland_insights.config_flow.ElectricIrelandAPI"
    ) as mock_api_class, patch(
        "custom_components.electric_ireland_insights.config_flow.async_create_clientsession"
    ):
        mock_api_instance = AsyncMock()
        mock_api_instance.validate_credentials = AsyncMock(
            return_value={"partner": "p1", "contract": "c1", "premise": "pr1"}
        )
        mock_api_class.return_value = mock_api_instance

        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        assert result["type"] == FlowResultType.FORM
        assert result["step_id"] == "user"

        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                "username": "test@test.com",
                "password": "testpass",
                "account_number": "951785073",
            },
        )
        assert result2["type"] == FlowResultType.CREATE_ENTRY
        assert result2["data"]["account_number"] == "951785073"


async def test_user_flow_invalid_auth(hass):
    """Test user flow shows error on invalid auth."""
    with patch(
        "custom_components.electric_ireland_insights.config_flow.ElectricIrelandAPI"
    ) as mock_api_class, patch(
        "custom_components.electric_ireland_insights.config_flow.async_create_clientsession"
    ):
        mock_api_instance = AsyncMock()
        mock_api_instance.validate_credentials = AsyncMock(side_effect=InvalidAuth)
        mock_api_class.return_value = mock_api_instance

        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {"username": "bad@test.com", "password": "wrong", "account_number": "123"},
        )
        assert result2["type"] == FlowResultType.FORM
        assert result2["errors"]["base"] == "invalid_auth"


async def test_user_flow_cannot_connect(hass):
    """Test user flow shows error on connection failure."""
    with patch(
        "custom_components.electric_ireland_insights.config_flow.ElectricIrelandAPI"
    ) as mock_api_class, patch(
        "custom_components.electric_ireland_insights.config_flow.async_create_clientsession"
    ):
        mock_api_instance = AsyncMock()
        mock_api_instance.validate_credentials = AsyncMock(side_effect=CannotConnect)
        mock_api_class.return_value = mock_api_instance

        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {"username": "test@test.com", "password": "pass", "account_number": "123"},
        )
        assert result2["type"] == FlowResultType.FORM
        assert result2["errors"]["base"] == "cannot_connect"


async def test_user_flow_account_not_found(hass):
    """Test user flow shows error when account not found."""
    with patch(
        "custom_components.electric_ireland_insights.config_flow.ElectricIrelandAPI"
    ) as mock_api_class, patch(
        "custom_components.electric_ireland_insights.config_flow.async_create_clientsession"
    ):
        mock_api_instance = AsyncMock()
        mock_api_instance.validate_credentials = AsyncMock(side_effect=AccountNotFound)
        mock_api_class.return_value = mock_api_instance

        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {"username": "test@test.com", "password": "pass", "account_number": "999"},
        )
        assert result2["type"] == FlowResultType.FORM
        assert result2["errors"]["base"] == "account_not_found"


async def test_user_flow_duplicate_account(hass, mock_config_entry):
    """Test that configuring the same account twice aborts."""
    mock_config_entry.add_to_hass(hass)

    with patch(
        "custom_components.electric_ireland_insights.config_flow.ElectricIrelandAPI"
    ) as mock_api_class, patch(
        "custom_components.electric_ireland_insights.config_flow.async_create_clientsession"
    ):
        mock_api_instance = AsyncMock()
        mock_api_instance.validate_credentials = AsyncMock(
            return_value={"partner": "p1", "contract": "c1", "premise": "pr1"}
        )
        mock_api_class.return_value = mock_api_instance

        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                "username": "test@test.com",
                "password": "testpass",
                "account_number": "951785073",
            },
        )
        assert result2["type"] == FlowResultType.ABORT
        assert result2["reason"] == "already_configured"


async def test_reauth_flow_success(hass, mock_config_entry):
    """Test reauth flow updates credentials successfully."""
    mock_config_entry.add_to_hass(hass)

    with patch(
        "custom_components.electric_ireland_insights.config_flow.ElectricIrelandAPI"
    ) as mock_api_class, patch(
        "custom_components.electric_ireland_insights.config_flow.async_create_clientsession"
    ):
        mock_api_instance = AsyncMock()
        mock_api_instance.validate_credentials = AsyncMock(
            return_value={"partner": "p1", "contract": "c1", "premise": "pr1"}
        )
        mock_api_class.return_value = mock_api_instance

        result = await mock_config_entry.start_reauth_flow(hass)
        assert result["type"] == FlowResultType.FORM
        assert result["step_id"] == "reauth_confirm"

        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {"password": "newpassword"},
        )
        assert result2["type"] == FlowResultType.ABORT
        assert result2["reason"] == "reauth_successful"


async def test_reauth_flow_invalid_auth(hass, mock_config_entry):
    """Test reauth flow shows error on invalid password."""
    mock_config_entry.add_to_hass(hass)

    with patch(
        "custom_components.electric_ireland_insights.config_flow.ElectricIrelandAPI"
    ) as mock_api_class, patch(
        "custom_components.electric_ireland_insights.config_flow.async_create_clientsession"
    ):
        mock_api_instance = AsyncMock()
        mock_api_instance.validate_credentials = AsyncMock(side_effect=InvalidAuth)
        mock_api_class.return_value = mock_api_instance

        result = await mock_config_entry.start_reauth_flow(hass)
        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {"password": "wrongpassword"},
        )
        assert result2["type"] == FlowResultType.FORM
        assert result2["errors"]["base"] == "invalid_auth"
