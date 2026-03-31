import json
import sys
from datetime import UTC, date, datetime
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
    CachedIdsInvalid,
    CannotConnect,
    InvalidAuth,
)

BASE_URL = "https://youraccountonline.electricireland.ie"

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "sample_hourly_response.json"
SAMPLE_RESPONSE = json.loads(FIXTURE_PATH.read_text())


def _make_mock_client(partner: str = "P1", contract: str = "C1", premise: str = "PR1") -> MagicMock:
    client = MagicMock(spec=MeterInsightClient)
    client._partner = partner
    client._contract = contract
    client._premise = premise
    return client


def _make_day_data(base_ts: int = 1774224000) -> list[dict]:
    return [{"consumption": 0.5, "cost": 0.1, "intervalEnd": base_ts + i * 3600} for i in range(24)]


@pytest.mark.asyncio
async def test_validate_credentials_success() -> None:
    api = ElectricIrelandAPI("user@test.com", "password", "951785073")
    mock_client = _make_mock_client("PARTNER1", "CONTRACT1", "PREMISE1")

    with patch.object(api, "_login", new_callable=AsyncMock, return_value=mock_client):
        result = await api.validate_credentials(MagicMock())

    assert result == {
        "partner": "PARTNER1",
        "contract": "CONTRACT1",
        "premise": "PREMISE1",
    }


@pytest.mark.asyncio
async def test_validate_credentials_raises_invalid_auth() -> None:
    api = ElectricIrelandAPI("user@test.com", "badpass", "951785073")

    with (
        patch.object(api, "_login", new_callable=AsyncMock, side_effect=InvalidAuth("bad creds")),
        pytest.raises(InvalidAuth, match="bad creds"),
    ):
        await api.validate_credentials(MagicMock())


@pytest.mark.asyncio
async def test_validate_credentials_raises_cannot_connect() -> None:
    api = ElectricIrelandAPI("user@test.com", "password", "951785073")

    with (
        patch.object(api, "_login", new_callable=AsyncMock, side_effect=CannotConnect("timeout")),
        pytest.raises(CannotConnect, match="timeout"),
    ):
        await api.validate_credentials(MagicMock())


@pytest.mark.asyncio
async def test_validate_credentials_raises_account_not_found() -> None:
    api = ElectricIrelandAPI("user@test.com", "password", "000000000")

    with (
        patch.object(
            api,
            "_login",
            new_callable=AsyncMock,
            side_effect=AccountNotFound("not found"),
        ),
        pytest.raises(AccountNotFound, match="not found"),
    ):
        await api.validate_credentials(MagicMock())


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


# ---------------------------------------------------------------------------
# HTML fixtures for _login / _login_cached tests
# ---------------------------------------------------------------------------

_LOGIN_PAGE_HTML = '<html><body><input name="Source" value="src_val"/></body></html>'
_LOGIN_PAGE_NO_SOURCE = "<html><body><p>no source here</p></body></html>"
_DASHBOARD_HTML = """<html><body>
<div class="my-accounts__item">
  <p class="account-number">951785073</p>
  <h2 class="account-electricity-icon"></h2>
  <form action="/Accounts/OnEvent">
    <input name="triggers_event" value="AccountSelection.ToInsights"/>
    <input name="AccountId" value="PARTNER1"/>
    <input name="ContractId" value="CONTRACT1"/>
    <input name="PremiseId" value="PREMISE1"/>
  </form>
</div>
</body></html>"""
_DASHBOARD_WRONG_ACCOUNT_HTML = """<html><body>
<div class="my-accounts__item">
  <p class="account-number">999999999</p>
  <h2 class="account-electricity-icon"></h2>
</div>
</body></html>"""
_INSIGHTS_HTML = """<html><body>
<div id="modelData" data-partner="PARTNER1" data-contract="CONTRACT1" data-premise="PREMISE1"></div>
</body></html>"""
_INSIGHTS_NO_MODEL_DATA_HTML = "<html><body><p>login page</p></body></html>"
_INSIGHTS_EMPTY_IDS_HTML = """<html><body>
<div id="modelData" data-partner="" data-contract="" data-premise=""></div>
</body></html>"""


# ---------------------------------------------------------------------------
# _login tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_login_success() -> None:
    api = ElectricIrelandAPI("user@test.com", "pass123", "951785073")
    with aioresponses_mock() as m:
        m.get(f"{BASE_URL}/", status=200, body=_LOGIN_PAGE_HTML, headers={"Set-Cookie": "rvt=rvttoken123; Path=/"})
        m.post(f"{BASE_URL}/", status=200, body=_DASHBOARD_HTML)
        m.post(f"{BASE_URL}/Accounts/OnEvent", status=200, body=_INSIGHTS_HTML)
        async with aiohttp.ClientSession() as session:
            client = await api._login(session)
    assert client._partner == "PARTNER1"
    assert client._contract == "CONTRACT1"
    assert client._premise == "PREMISE1"


@pytest.mark.asyncio
async def test_login_missing_source_token() -> None:
    api = ElectricIrelandAPI("user@test.com", "pass123", "951785073")
    with aioresponses_mock() as m:
        m.get(f"{BASE_URL}/", status=200, body=_LOGIN_PAGE_NO_SOURCE, headers={"Set-Cookie": "rvt=rvttoken123; Path=/"})
        async with aiohttp.ClientSession() as session:
            with pytest.raises(CannotConnect):
                await api._login(session)


@pytest.mark.asyncio
async def test_login_missing_rvt_cookie() -> None:
    api = ElectricIrelandAPI("user@test.com", "pass123", "951785073")
    with aioresponses_mock() as m:
        m.get(f"{BASE_URL}/", status=200, body=_LOGIN_PAGE_HTML)
        async with aiohttp.ClientSession() as session:
            with pytest.raises(CannotConnect):
                await api._login(session)


@pytest.mark.asyncio
async def test_login_account_not_found() -> None:
    api = ElectricIrelandAPI("user@test.com", "pass123", "951785073")
    with aioresponses_mock() as m:
        m.get(f"{BASE_URL}/", status=200, body=_LOGIN_PAGE_HTML, headers={"Set-Cookie": "rvt=rvttoken123; Path=/"})
        m.post(f"{BASE_URL}/", status=200, body=_DASHBOARD_WRONG_ACCOUNT_HTML)
        async with aiohttp.ClientSession() as session:
            with pytest.raises(AccountNotFound):
                await api._login(session)


@pytest.mark.asyncio
async def test_login_no_model_data() -> None:
    api = ElectricIrelandAPI("user@test.com", "pass123", "951785073")
    with aioresponses_mock() as m:
        m.get(f"{BASE_URL}/", status=200, body=_LOGIN_PAGE_HTML, headers={"Set-Cookie": "rvt=rvttoken123; Path=/"})
        m.post(f"{BASE_URL}/", status=200, body=_DASHBOARD_HTML)
        m.post(f"{BASE_URL}/Accounts/OnEvent", status=200, body=_INSIGHTS_NO_MODEL_DATA_HTML)
        async with aiohttp.ClientSession() as session:
            with pytest.raises(InvalidAuth):
                await api._login(session)


@pytest.mark.asyncio
async def test_login_missing_meter_ids() -> None:
    api = ElectricIrelandAPI("user@test.com", "pass123", "951785073")
    with aioresponses_mock() as m:
        m.get(f"{BASE_URL}/", status=200, body=_LOGIN_PAGE_HTML, headers={"Set-Cookie": "rvt=rvttoken123; Path=/"})
        m.post(f"{BASE_URL}/", status=200, body=_DASHBOARD_HTML)
        m.post(f"{BASE_URL}/Accounts/OnEvent", status=200, body=_INSIGHTS_EMPTY_IDS_HTML)
        async with aiohttp.ClientSession() as session:
            with pytest.raises(InvalidAuth):
                await api._login(session)


@pytest.mark.asyncio
async def test_login_client_error() -> None:
    api = ElectricIrelandAPI("user@test.com", "pass123", "951785073")
    with aioresponses_mock() as m:
        m.get(f"{BASE_URL}/", exception=aiohttp.ClientError("network error"))
        async with aiohttp.ClientSession() as session:
            with pytest.raises(CannotConnect):
                await api._login(session)


@pytest.mark.asyncio
async def test_login_timeout() -> None:
    api = ElectricIrelandAPI("user@test.com", "pass123", "951785073")
    with aioresponses_mock() as m:
        m.get(f"{BASE_URL}/", exception=TimeoutError())
        async with aiohttp.ClientSession() as session:
            with pytest.raises(CannotConnect):
                await api._login(session)


# ---------------------------------------------------------------------------
# _login with cached meter IDs
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_login_with_cached_ids_skips_insights_parsing() -> None:
    api = ElectricIrelandAPI("user@test.com", "pass123", "951785073")
    cached_ids = {"partner": "P1", "contract": "C1", "premise": "PR1"}
    with aioresponses_mock() as m:
        m.get(f"{BASE_URL}/", status=200, body=_LOGIN_PAGE_HTML, headers={"Set-Cookie": "rvt=rvttoken123; Path=/"})
        m.post(f"{BASE_URL}/", status=200, body=_DASHBOARD_HTML)
        m.post(f"{BASE_URL}/Accounts/OnEvent", status=200, body=_INSIGHTS_HTML)
        async with aiohttp.ClientSession() as session:
            client = await api._login(session, cached_meter_ids=cached_ids)
    assert client._partner == "P1"
    assert client._contract == "C1"
    assert client._premise == "PR1"


@pytest.mark.asyncio
async def test_login_without_cached_ids_discovers_from_insights() -> None:
    api = ElectricIrelandAPI("user@test.com", "pass123", "951785073")
    with aioresponses_mock() as m:
        m.get(f"{BASE_URL}/", status=200, body=_LOGIN_PAGE_HTML, headers={"Set-Cookie": "rvt=rvttoken123; Path=/"})
        m.post(f"{BASE_URL}/", status=200, body=_DASHBOARD_HTML)
        m.post(f"{BASE_URL}/Accounts/OnEvent", status=200, body=_INSIGHTS_HTML)
        async with aiohttp.ClientSession() as session:
            client = await api._login(session)
    assert client._partner == "PARTNER1"
    assert client._contract == "CONTRACT1"
    assert client._premise == "PREMISE1"


# ---------------------------------------------------------------------------
# discover_accounts tests
# ---------------------------------------------------------------------------

_DASHBOARD_MULTI_ACCOUNT_HTML = """<html><body>
<div class="my-accounts__item">
  <p class="account-number">111111111</p>
  <h2 class="account-electricity-icon"></h2>
</div>
<div class="my-accounts__item">
  <p class="account-number">222222222</p>
  <h2 class="account-electricity-icon"></h2>
  <h3 class="account-label">Office</h3>
</div>
</body></html>"""

_DASHBOARD_GAS_ONLY_HTML = """<html><body>
<div class="my-accounts__item">
  <p class="account-number">333333333</p>
  <h2 class="account-gas-icon"></h2>
</div>
</body></html>"""

_DASHBOARD_NO_ACCOUNTS_HTML = "<html><body><p>Welcome</p></body></html>"


@pytest.mark.asyncio
async def test_discover_accounts_single() -> None:
    api = ElectricIrelandAPI("user@test.com", "pass123")
    with aioresponses_mock() as m:
        m.get(f"{BASE_URL}/", status=200, body=_LOGIN_PAGE_HTML, headers={"Set-Cookie": "rvt=rvttoken123; Path=/"})
        m.post(f"{BASE_URL}/", status=200, body=_DASHBOARD_HTML)
        async with aiohttp.ClientSession() as session:
            accounts = await api.discover_accounts(session)
    assert len(accounts) == 1
    assert accounts[0]["account_number"] == "951785073"


@pytest.mark.asyncio
async def test_discover_accounts_multiple() -> None:
    api = ElectricIrelandAPI("user@test.com", "pass123")
    with aioresponses_mock() as m:
        m.get(f"{BASE_URL}/", status=200, body=_LOGIN_PAGE_HTML, headers={"Set-Cookie": "rvt=rvttoken123; Path=/"})
        m.post(f"{BASE_URL}/", status=200, body=_DASHBOARD_MULTI_ACCOUNT_HTML)
        async with aiohttp.ClientSession() as session:
            accounts = await api.discover_accounts(session)
    assert len(accounts) == 2
    assert accounts[0]["account_number"] == "111111111"
    assert accounts[1]["account_number"] == "222222222"
    assert "Office" in accounts[1]["display_name"]


@pytest.mark.asyncio
async def test_discover_accounts_no_accounts() -> None:
    api = ElectricIrelandAPI("user@test.com", "pass123")
    with aioresponses_mock() as m:
        m.get(f"{BASE_URL}/", status=200, body=_LOGIN_PAGE_HTML, headers={"Set-Cookie": "rvt=rvttoken123; Path=/"})
        m.post(f"{BASE_URL}/", status=200, body=_DASHBOARD_NO_ACCOUNTS_HTML)
        async with aiohttp.ClientSession() as session:
            with pytest.raises(AccountNotFound):
                await api.discover_accounts(session)


@pytest.mark.asyncio
async def test_discover_accounts_gas_only() -> None:
    api = ElectricIrelandAPI("user@test.com", "pass123")
    with aioresponses_mock() as m:
        m.get(f"{BASE_URL}/", status=200, body=_LOGIN_PAGE_HTML, headers={"Set-Cookie": "rvt=rvttoken123; Path=/"})
        m.post(f"{BASE_URL}/", status=200, body=_DASHBOARD_GAS_ONLY_HTML)
        async with aiohttp.ClientSession() as session:
            with pytest.raises(AccountNotFound):
                await api.discover_accounts(session)


@pytest.mark.asyncio
async def test_discover_accounts_missing_tokens() -> None:
    api = ElectricIrelandAPI("user@test.com", "pass123")
    with aioresponses_mock() as m:
        m.get(f"{BASE_URL}/", status=200, body=_LOGIN_PAGE_NO_SOURCE)
        async with aiohttp.ClientSession() as session:
            with pytest.raises(CannotConnect):
                await api.discover_accounts(session)


# ---------------------------------------------------------------------------
# get_data error path tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_data_401() -> None:

    meter_ids = {"partner": "P1", "contract": "C1", "premise": "PR1"}
    target_date = datetime(2026, 3, 23, tzinfo=UTC)
    url = f"{BASE_URL}/MeterInsight/P1/C1/PR1/hourly-usage?date=2026-03-23"
    with aioresponses_mock() as m:
        m.get(url, status=401)
        async with aiohttp.ClientSession() as session:
            client = MeterInsightClient(session, meter_ids)
            with pytest.raises(CachedIdsInvalid):
                await client.get_data(target_date)


@pytest.mark.asyncio
async def test_get_data_403() -> None:

    meter_ids = {"partner": "P1", "contract": "C1", "premise": "PR1"}
    target_date = datetime(2026, 3, 23, tzinfo=UTC)
    url = f"{BASE_URL}/MeterInsight/P1/C1/PR1/hourly-usage?date=2026-03-23"
    with aioresponses_mock() as m:
        m.get(url, status=403)
        async with aiohttp.ClientSession() as session:
            client = MeterInsightClient(session, meter_ids)
            with pytest.raises(CachedIdsInvalid):
                await client.get_data(target_date)


@pytest.mark.asyncio
async def test_get_data_non_json_response() -> None:

    meter_ids = {"partner": "P1", "contract": "C1", "premise": "PR1"}
    target_date = datetime(2026, 3, 23, tzinfo=UTC)
    url = f"{BASE_URL}/MeterInsight/P1/C1/PR1/hourly-usage?date=2026-03-23"
    with aioresponses_mock() as m:
        m.get(url, status=200, body="<html>Login page</html>", content_type="text/html")
        async with aiohttp.ClientSession() as session:
            client = MeterInsightClient(session, meter_ids)
            with pytest.raises(CachedIdsInvalid):
                await client.get_data(target_date)


@pytest.mark.asyncio
async def test_get_data_is_success_false() -> None:
    meter_ids = {"partner": "P1", "contract": "C1", "premise": "PR1"}
    target_date = datetime(2026, 3, 23, tzinfo=UTC)
    url = f"{BASE_URL}/MeterInsight/P1/C1/PR1/hourly-usage?date=2026-03-23"
    with aioresponses_mock() as m:
        m.get(url, payload={"isSuccess": False, "message": "Error", "data": []}, content_type="application/json")
        async with aiohttp.ClientSession() as session:
            client = MeterInsightClient(session, meter_ids)
            result = await client.get_data(target_date)
    assert result == []


@pytest.mark.asyncio
async def test_get_data_missing_end_date() -> None:
    meter_ids = {"partner": "P1", "contract": "C1", "premise": "PR1"}
    target_date = datetime(2026, 3, 23, tzinfo=UTC)
    url = f"{BASE_URL}/MeterInsight/P1/C1/PR1/hourly-usage?date=2026-03-23"
    payload = {"isSuccess": True, "data": [{"flatRate": {"consumption": 0.5, "cost": 0.1}}]}
    with aioresponses_mock() as m:
        m.get(url, payload=payload, content_type="application/json")
        async with aiohttp.ClientSession() as session:
            client = MeterInsightClient(session, meter_ids)
            result = await client.get_data(target_date)
    assert result == []


@pytest.mark.asyncio
async def test_get_data_invalid_date_string() -> None:
    meter_ids = {"partner": "P1", "contract": "C1", "premise": "PR1"}
    target_date = datetime(2026, 3, 23, tzinfo=UTC)
    url = f"{BASE_URL}/MeterInsight/P1/C1/PR1/hourly-usage?date=2026-03-23"
    payload = {"isSuccess": True, "data": [{"endDate": "not-a-date", "flatRate": {"consumption": 0.5, "cost": 0.1}}]}
    with aioresponses_mock() as m:
        m.get(url, payload=payload, content_type="application/json")
        async with aiohttp.ClientSession() as session:
            client = MeterInsightClient(session, meter_ids)
            result = await client.get_data(target_date)
    assert result == []


@pytest.mark.asyncio
async def test_get_data_client_error() -> None:
    meter_ids = {"partner": "P1", "contract": "C1", "premise": "PR1"}
    target_date = datetime(2026, 3, 23, tzinfo=UTC)
    url = f"{BASE_URL}/MeterInsight/P1/C1/PR1/hourly-usage?date=2026-03-23"
    with aioresponses_mock() as m:
        m.get(url, exception=aiohttp.ClientError("network error"))
        async with aiohttp.ClientSession() as session:
            client = MeterInsightClient(session, meter_ids)
            result = await client.get_data(target_date)
    assert result == []


@pytest.mark.asyncio
async def test_discover_accounts_wraps_aiohttp_client_error() -> None:
    """aiohttp.ClientError in discover_accounts must become CannotConnect."""
    api = ElectricIrelandAPI("user@test.com", "password")

    with aioresponses_mock() as m:
        m.get(f"{BASE_URL}/", exception=aiohttp.ClientError("network down"))
        async with aiohttp.ClientSession() as session:
            with pytest.raises(CannotConnect):
                await api.discover_accounts(session)


@pytest.mark.asyncio
async def test_discover_accounts_wraps_timeout() -> None:
    """asyncio.TimeoutError in discover_accounts must become CannotConnect."""

    api = ElectricIrelandAPI("user@test.com", "password")

    with aioresponses_mock() as m:
        m.get(f"{BASE_URL}/", exception=TimeoutError())
        async with aiohttp.ClientSession() as session:
            with pytest.raises(CannotConnect):
                await api.discover_accounts(session)


# ---------------------------------------------------------------------------
# get_data 204 test (missing coverage)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_data_204_returns_empty_list() -> None:
    """HTTP 204 from hourly-usage endpoint returns empty list."""
    meter_ids = {"partner": "P1", "contract": "C1", "premise": "PR1"}
    target_date = datetime(2026, 3, 23, tzinfo=UTC)
    url = f"{BASE_URL}/MeterInsight/P1/C1/PR1/hourly-usage?date=2026-03-23"
    with aioresponses_mock() as m:
        m.get(url, status=204)
        async with aiohttp.ClientSession() as session:
            client = MeterInsightClient(session, meter_ids)
            result = await client.get_data(target_date)
    assert result == []


# ---------------------------------------------------------------------------
# authenticate tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_authenticate_with_cached_ids() -> None:
    """authenticate() with cached IDs returns (cached_ids, None)."""
    api = ElectricIrelandAPI("user@test.com", "pass123", "951785073")
    cached_ids = {"partner": "P1", "contract": "C1", "premise": "PR1"}
    with aioresponses_mock() as m:
        m.get(
            f"{BASE_URL}/",
            status=200,
            body=_LOGIN_PAGE_HTML,
            headers={"Set-Cookie": "rvt=rvttoken123; Path=/"},
        )
        m.post(f"{BASE_URL}/", status=200, body=_DASHBOARD_HTML)
        m.post(f"{BASE_URL}/Accounts/OnEvent", status=200, body=_INSIGHTS_HTML)
        async with aiohttp.ClientSession() as session:
            result = await api.authenticate(session, meter_ids=cached_ids)
    assert result == (cached_ids, None)


@pytest.mark.asyncio
async def test_authenticate_full_discovery() -> None:
    """authenticate() without cached IDs returns (discovered, discovered)."""
    api = ElectricIrelandAPI("user@test.com", "pass123", "951785073")
    expected_ids = {
        "partner": "PARTNER1",
        "contract": "CONTRACT1",
        "premise": "PREMISE1",
    }
    with aioresponses_mock() as m:
        m.get(
            f"{BASE_URL}/",
            status=200,
            body=_LOGIN_PAGE_HTML,
            headers={"Set-Cookie": "rvt=rvttoken123; Path=/"},
        )
        m.post(f"{BASE_URL}/", status=200, body=_DASHBOARD_HTML)
        m.post(f"{BASE_URL}/Accounts/OnEvent", status=200, body=_INSIGHTS_HTML)
        async with aiohttp.ClientSession() as session:
            result = await api.authenticate(session, meter_ids=None)
    assert result == (expected_ids, expected_ids)


# ---------------------------------------------------------------------------
# get_bill_periods tests
# ---------------------------------------------------------------------------

_BILL_PERIOD_RESPONSE = {
    "subStatusCode": "SUCCESS",
    "isSuccess": True,
    "message": "Successfully executed query for query BillPeriod",
    "data": [
        {
            "startDate": "2026-02-26T00:00:00Z",
            "endDate": "2026-03-25T23:59:59Z",
            "current": False,
            "hasAppliance": True,
        },
        {
            "startDate": "2026-03-26T00:00:00Z",
            "endDate": "2026-04-25T22:59:59Z",
            "current": True,
            "hasAppliance": False,
        },
    ],
}


@pytest.mark.asyncio
async def test_get_bill_periods_success() -> None:
    """Successful bill-period response returns list of BillPeriod dicts."""
    api = ElectricIrelandAPI("user@test.com", "pass123", "951785073")
    meter_ids = {"partner": "P1", "contract": "C1", "premise": "PR1"}
    url = f"{BASE_URL}/MeterInsight/P1/C1/PR1/bill-period"
    with aioresponses_mock() as m:
        m.get(url, payload=_BILL_PERIOD_RESPONSE, content_type="application/json")
        async with aiohttp.ClientSession() as session:
            result = await api.get_bill_periods(session, meter_ids)
    assert len(result) == 2
    assert result[0]["startDate"] == "2026-02-26T00:00:00Z"
    assert result[1]["current"] is True


@pytest.mark.asyncio
async def test_get_bill_periods_204() -> None:
    """HTTP 204 from bill-period endpoint returns empty list."""
    api = ElectricIrelandAPI("user@test.com", "pass123", "951785073")
    meter_ids = {"partner": "P1", "contract": "C1", "premise": "PR1"}
    url = f"{BASE_URL}/MeterInsight/P1/C1/PR1/bill-period"
    with aioresponses_mock() as m:
        m.get(url, status=204)
        async with aiohttp.ClientSession() as session:
            result = await api.get_bill_periods(session, meter_ids)
    assert result == []


@pytest.mark.asyncio
async def test_get_bill_periods_session_expired() -> None:
    """200 + text/html response raises CannotConnect (session expired)."""
    api = ElectricIrelandAPI("user@test.com", "pass123", "951785073")
    meter_ids = {"partner": "P1", "contract": "C1", "premise": "PR1"}
    url = f"{BASE_URL}/MeterInsight/P1/C1/PR1/bill-period"
    with aioresponses_mock() as m:
        m.get(
            url,
            status=200,
            body="<html>Login Page</html>",
            content_type="text/html",
        )
        async with aiohttp.ClientSession() as session:
            with pytest.raises(CannotConnect, match="Session expired"):
                await api.get_bill_periods(session, meter_ids)


@pytest.mark.asyncio
async def test_get_bill_periods_client_error() -> None:
    """aiohttp.ClientError raises CannotConnect."""
    api = ElectricIrelandAPI("user@test.com", "pass123", "951785073")
    meter_ids = {"partner": "P1", "contract": "C1", "premise": "PR1"}
    url = f"{BASE_URL}/MeterInsight/P1/C1/PR1/bill-period"
    with aioresponses_mock() as m:
        m.get(url, exception=aiohttp.ClientError("network error"))
        async with aiohttp.ClientSession() as session:
            with pytest.raises(CannotConnect):
                await api.get_bill_periods(session, meter_ids)


# ---------------------------------------------------------------------------
# get_hourly_usage tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_hourly_usage_delegates_to_get_data() -> None:
    """get_hourly_usage delegates to MeterInsightClient.get_data."""
    api = ElectricIrelandAPI("user@test.com", "pass123", "951785073")
    meter_ids = {"partner": "P1", "contract": "C1", "premise": "PR1"}
    url = f"{BASE_URL}/MeterInsight/P1/C1/PR1/hourly-usage?date=2026-03-23"
    with aioresponses_mock() as m:
        m.get(url, payload=SAMPLE_RESPONSE, content_type="application/json")
        async with aiohttp.ClientSession() as session:
            result = await api.get_hourly_usage(session, meter_ids, date(2026, 3, 23))
    assert len(result) == 24
    for dp in result:
        assert "consumption" in dp
        assert "cost" in dp
        assert "intervalEnd" in dp
