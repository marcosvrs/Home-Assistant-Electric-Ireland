import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest
from aioresponses import aioresponses as aioresponses_mock

_HA_STUBS = [
    "homeassistant",
    "homeassistant.config_entries",
    "homeassistant.core",
    "homeassistant.helpers",
    "homeassistant.helpers.typing",
]
for _mod_name in _HA_STUBS:
    sys.modules.setdefault(_mod_name, MagicMock())

from custom_components.electric_ireland_insights.api import (  # noqa: E402
    ElectricIrelandAPI,
    MeterInsightClient,
)
from custom_components.electric_ireland_insights.exceptions import (  # noqa: E402
    AccountNotFound,
    CannotConnect,
    InvalidAuth,
)

BASE_URL = "https://youraccountonline.electricireland.ie"

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "sample_hourly_response.json"
SAMPLE_RESPONSE = json.loads(FIXTURE_PATH.read_text())


def _make_mock_client(
    partner: str = "P1", contract: str = "C1", premise: str = "PR1"
) -> MagicMock:
    client = MagicMock(spec=MeterInsightClient)
    client._partner = partner
    client._contract = contract
    client._premise = premise
    return client


def _make_day_data(base_ts: int = 1774224000) -> list[dict]:
    return [
        {"consumption": 0.5, "cost": 0.1, "intervalEnd": base_ts + i * 3600}
        for i in range(24)
    ]


@pytest.mark.asyncio
async def test_validate_credentials_success() -> None:
    api = ElectricIrelandAPI("user@test.com", "password", "951785073")
    mock_client = _make_mock_client("PARTNER1", "CONTRACT1", "PREMISE1")

    with patch.object(api, "_login", new_callable=AsyncMock, return_value=mock_client):
        async with aiohttp.ClientSession() as session:
            result = await api.validate_credentials(session)

    assert result == {
        "partner": "PARTNER1",
        "contract": "CONTRACT1",
        "premise": "PREMISE1",
    }


@pytest.mark.asyncio
async def test_validate_credentials_raises_invalid_auth() -> None:
    api = ElectricIrelandAPI("user@test.com", "badpass", "951785073")

    with patch.object(
        api, "_login", new_callable=AsyncMock, side_effect=InvalidAuth("bad creds")
    ):
        async with aiohttp.ClientSession() as session:
            with pytest.raises(InvalidAuth, match="bad creds"):
                await api.validate_credentials(session)


@pytest.mark.asyncio
async def test_validate_credentials_raises_cannot_connect() -> None:
    api = ElectricIrelandAPI("user@test.com", "password", "951785073")

    with patch.object(
        api, "_login", new_callable=AsyncMock, side_effect=CannotConnect("timeout")
    ):
        async with aiohttp.ClientSession() as session:
            with pytest.raises(CannotConnect, match="timeout"):
                await api.validate_credentials(session)


@pytest.mark.asyncio
async def test_validate_credentials_raises_account_not_found() -> None:
    api = ElectricIrelandAPI("user@test.com", "password", "000000000")

    with patch.object(
        api,
        "_login",
        new_callable=AsyncMock,
        side_effect=AccountNotFound("not found"),
    ):
        async with aiohttp.ClientSession() as session:
            with pytest.raises(AccountNotFound, match="not found"):
                await api.validate_credentials(session)


@pytest.mark.asyncio
async def test_fetch_day_range_success() -> None:
    api = ElectricIrelandAPI("user@test.com", "password", "951785073")
    mock_client = _make_mock_client()
    mock_client.get_data = AsyncMock(return_value=_make_day_data())

    with patch.object(api, "_login", new_callable=AsyncMock, return_value=mock_client):
        async with aiohttp.ClientSession() as session:
            result, discovered_ids = await api.fetch_day_range(session, lookback_days=3)

    assert len(result) == 72
    assert mock_client.get_data.call_count == 3


@pytest.mark.asyncio
async def test_fetch_day_range_partial_failure() -> None:
    api = ElectricIrelandAPI("user@test.com", "password", "951785073")
    mock_client = _make_mock_client()

    mock_client.get_data = AsyncMock(
        side_effect=[
            _make_day_data(1774224000),
            Exception("server error"),
            _make_day_data(1774396800),
        ]
    )

    with patch.object(api, "_login", new_callable=AsyncMock, return_value=mock_client):
        async with aiohttp.ClientSession() as session:
            result, discovered_ids = await api.fetch_day_range(session, lookback_days=3)

    assert len(result) == 48
    assert mock_client.get_data.call_count == 3


@pytest.mark.asyncio
async def test_meter_insight_client_parses_response() -> None:
    meter_ids = {"partner": "P1", "contract": "C1", "premise": "PR1"}

    with aioresponses_mock() as m:
        url = f"{BASE_URL}/MeterInsight/P1/C1/PR1/hourly-usage?date=2026-03-23"
        m.get(
            url,
            payload=SAMPLE_RESPONSE,
            content_type="application/json",
        )

        async with aiohttp.ClientSession() as real_session:
            client = MeterInsightClient(real_session, meter_ids)
            target_date = datetime(2026, 3, 23, tzinfo=UTC)
            result = await client.get_data(target_date)

    assert len(result) == 24
    for dp in result:
        assert "consumption" in dp
        assert "cost" in dp
        assert "intervalEnd" in dp
        assert isinstance(dp["intervalEnd"], int)
        assert isinstance(dp["consumption"], float)
        assert isinstance(dp["cost"], float)
