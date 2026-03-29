from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta

import aiohttp
from bs4 import BeautifulSoup, Tag

from .const import DOMAIN
from .exceptions import AccountNotFound, CachedIdsInvalid, CannotConnect, InvalidAuth
from .types import ElectricIrelandDatapoint, MeterIds

LOGGER = logging.getLogger(DOMAIN)

BASE_URL = "https://youraccountonline.electricireland.ie"


class ElectricIrelandAPI:

    def __init__(self, username: str, password: str, account_number: str) -> None:
        self._username = username
        self._password = password
        self._account_number = account_number

    async def validate_credentials(self, session: aiohttp.ClientSession) -> MeterIds:
        client = await self._login(session)
        return {
            "partner": client._partner,
            "contract": client._contract,
            "premise": client._premise,
        }

    async def fetch_day_range(
        self,
        session: aiohttp.ClientSession,
        lookback_days: int,
        meter_ids: MeterIds | None = None,
    ) -> tuple[list[ElectricIrelandDatapoint], MeterIds | None]:
        discovered_ids: MeterIds | None = None

        if meter_ids is not None:
            LOGGER.debug("Using cached meter IDs — skipping HTML discovery")
            try:
                client = await self._login_cached(session, meter_ids)
            except CachedIdsInvalid as err:
                LOGGER.warning(
                    "Cached IDs failed (%s), falling back to full login", err
                )
                client = await self._login(session)
                discovered_ids = {
                    "partner": client._partner,
                    "contract": client._contract,
                    "premise": client._premise,
                }
        else:
            LOGGER.info("Discovering meter IDs via full login")
            client = await self._login(session)
            discovered_ids = {
                "partner": client._partner,
                "contract": client._contract,
                "premise": client._premise,
            }

        now = datetime.now(UTC)
        yesterday = datetime(now.year, now.month, now.day, tzinfo=UTC) - timedelta(
            days=1
        )

        all_datapoints: list[ElectricIrelandDatapoint] = []
        for i in range(lookback_days, 0, -1):
            target_date = yesterday - timedelta(days=i - 1)
            try:
                day_data = await client.get_data(target_date)
                all_datapoints.extend(day_data)
            except Exception as err:
                LOGGER.warning("Failed to get data for %s: %s", target_date, err)
                continue

        return all_datapoints, discovered_ids

    async def _login_cached(
        self, session: aiohttp.ClientSession, meter_ids: MeterIds
    ) -> MeterInsightClient:
        timeout = aiohttp.ClientTimeout(total=30)

        try:
            async with session.get(f"{BASE_URL}/", timeout=timeout) as res1:
                res1.raise_for_status()
                html1 = await res1.text()
                rvt = res1.cookies.get("rvt")
                if rvt:
                    rvt = rvt.value

            soup1 = BeautifulSoup(html1, "html.parser")
            source_input = soup1.find("input", attrs={"name": "Source"})
            source_val = source_input.get("value") if isinstance(source_input, Tag) else None
            source = source_val if isinstance(source_val, str) else None

            if not source or not rvt:
                raise CachedIdsInvalid(
                    "Could not extract login tokens during cached login"
                )

            async with session.post(
                f"{BASE_URL}/",
                data={
                    "LoginFormData.UserName": self._username,
                    "LoginFormData.Password": self._password,
                    "rvt": rvt,
                    "Source": source,
                    "PotText": "",
                    "__EiTokPotText": "",
                    "ReturnUrl": "",
                    "AccountNumber": "",
                },
                timeout=timeout,
            ) as res2:
                res2.raise_for_status()

            req3 = {
                "triggers_event": "AccountSelection.ToInsights",
                "AccountId": meter_ids.get("partner", ""),
            }
            async with session.post(
                f"{BASE_URL}/Accounts/OnEvent",
                data=req3,
                timeout=timeout,
            ) as res3:
                html3 = await res3.text()
                if "modelData" not in html3:
                    LOGGER.warning(
                        "Cached IDs may be stale — OnEvent didn't return insights page"
                    )

            LOGGER.debug(
                "Cached login: partner=%s, contract=%s, premise=%s",
                meter_ids.get("partner"),
                meter_ids.get("contract"),
                meter_ids.get("premise"),
            )
            return MeterInsightClient(session, meter_ids)

        except (CachedIdsInvalid, InvalidAuth):
            raise
        except aiohttp.ClientError as err:
            raise CachedIdsInvalid(
                f"Network error during cached login: {err}"
            ) from err
        except asyncio.TimeoutError:
            raise CachedIdsInvalid("Timeout during cached login")

    async def _login(self, session: aiohttp.ClientSession) -> MeterInsightClient:
        timeout = aiohttp.ClientTimeout(total=30)

        try:
            LOGGER.debug("Getting Source Token...")
            async with session.get(
                f"{BASE_URL}/", timeout=timeout
            ) as res1:
                res1.raise_for_status()
                html1 = await res1.text()
                rvt = res1.cookies.get("rvt")
                if rvt:
                    rvt = rvt.value

            soup1 = BeautifulSoup(html1, "html.parser")
            source_input = soup1.find("input", attrs={"name": "Source"})
            source_val = source_input.get("value") if isinstance(source_input, Tag) else None
            source = source_val if isinstance(source_val, str) else None

            if not source or not rvt:
                raise CannotConnect("Could not extract login tokens")

            LOGGER.debug("Performing Login...")
            async with session.post(
                f"{BASE_URL}/",
                data={
                    "LoginFormData.UserName": self._username,
                    "LoginFormData.Password": self._password,
                    "rvt": rvt,
                    "Source": source,
                    "PotText": "",
                    "__EiTokPotText": "",
                    "ReturnUrl": "",
                    "AccountNumber": "",
                },
                timeout=timeout,
            ) as res2:
                res2.raise_for_status()
                html2 = await res2.text()

            soup2 = BeautifulSoup(html2, "html.parser")
            account_divs = soup2.find_all("div", {"class": "my-accounts__item"})
            target_account = None
            for account_div in account_divs:
                account_number_el = account_div.find(
                    "p", {"class": "account-number"}
                )
                if not account_number_el:
                    continue
                account_number = account_number_el.text
                if account_number != self._account_number:
                    LOGGER.debug(
                        "Skipping account %s as it is not target", account_number
                    )
                    continue

                is_elec_divs = account_div.find_all(
                    "h2", {"class": "account-electricity-icon"}
                )
                if len(is_elec_divs) != 1:
                    LOGGER.info(
                        "Found account %s but is not Electricity", account_number
                    )
                    continue

                target_account = account_div
                break

            if not target_account:
                raise AccountNotFound(
                    f"Account {self._account_number} not found"
                )

            LOGGER.debug("Navigating to Insights page...")
            event_form = target_account.find(
                "form", {"action": "/Accounts/OnEvent"}
            )
            req3: dict[str, str] = {
                "triggers_event": "AccountSelection.ToInsights",
            }
            for form_input in event_form.find_all("input"):
                req3[form_input.get("name")] = form_input.get("value")

            async with session.post(
                f"{BASE_URL}/Accounts/OnEvent",
                data=req3,
                timeout=timeout,
            ) as res3:
                res3.raise_for_status()
                html3 = await res3.text()

            soup3 = BeautifulSoup(html3, "html.parser")
            model_data = soup3.find("div", {"id": "modelData"})

            if not model_data:
                raise InvalidAuth(
                    "Login succeeded but insights page not accessible"
                )

            assert isinstance(model_data, Tag)

            partner = model_data.get("data-partner")
            contract = model_data.get("data-contract")
            premise = model_data.get("data-premise")

            if not all([partner, contract, premise]):
                raise InvalidAuth(
                    "Login succeeded but insights page not accessible"
                )

            assert isinstance(partner, str)
            assert isinstance(contract, str)
            assert isinstance(premise, str)

            LOGGER.info(
                "Found meter IDs: partner=%s, contract=%s, premise=%s",
                partner,
                contract,
                premise,
            )
            return MeterInsightClient(
                session, {"partner": partner, "contract": contract, "premise": premise}
            )

        except (InvalidAuth, CannotConnect, AccountNotFound):
            raise
        except aiohttp.ClientError as err:
            raise CannotConnect(str(err)) from err
        except asyncio.TimeoutError:
            raise CannotConnect("Connection timed out")


class MeterInsightClient:

    def __init__(self, session: aiohttp.ClientSession, meter_ids: MeterIds) -> None:
        self._session = session
        self._partner = meter_ids["partner"]
        self._contract = meter_ids["contract"]
        self._premise = meter_ids["premise"]

    async def get_data(self, target_date: datetime) -> list[ElectricIrelandDatapoint]:
        date_str = target_date.strftime("%Y-%m-%d")
        LOGGER.debug("Getting hourly data for %s...", date_str)

        url = (
            f"{BASE_URL}/MeterInsight/"
            f"{self._partner}/{self._contract}/{self._premise}/hourly-usage"
        )
        timeout = aiohttp.ClientTimeout(total=30)

        try:
            async with self._session.get(
                url, params={"date": date_str}, timeout=timeout
            ) as response:
                if response.status in (401, 403, 404):
                    raise CachedIdsInvalid(f"API returned {response.status}")

                response.raise_for_status()

                content_type = response.headers.get("content-type", "")
                if "application/json" not in content_type:
                    body = await response.text()
                    LOGGER.error(
                        "Expected JSON but got %s. Response: %s",
                        content_type,
                        body[:500],
                    )
                    raise CachedIdsInvalid(
                        "Non-JSON response from MeterInsight API — session may be expired"
                    )

                try:
                    data = await response.json()
                except Exception as err:
                    body = await response.text()
                    LOGGER.error(
                        "Failed to parse JSON: %s. Response: %s", err, body[:500]
                    )
                    return []

        except CachedIdsInvalid:
            raise
        except aiohttp.ClientError as err:
            LOGGER.error("Failed to get hourly usage data: %s", err)
            return []

        if not data.get("isSuccess"):
            LOGGER.error("API returned error: %s", data.get("message"))
            return []

        raw_datapoints = data.get("data", [])
        LOGGER.debug("Found %d hourly datapoints for %s", len(raw_datapoints), date_str)

        datapoints: list[ElectricIrelandDatapoint] = []
        usage_tariff_keys = ("flatRate", "offPeak", "midPeak", "onPeak")

        for dp in raw_datapoints:
            end_date_str = dp.get("endDate")

            if not end_date_str:
                continue

            try:
                end_dt = datetime.fromisoformat(end_date_str.replace("Z", "+00:00"))
                interval_end = int(end_dt.timestamp())
            except (ValueError, AttributeError) as err:
                LOGGER.warning("Failed to parse date %s: %s", end_date_str, err)
                continue

            usage_entry = next(
                (dp[key] for key in usage_tariff_keys if dp.get(key) is not None),
                None,
            )

            if usage_entry is not None:
                datapoints.append(
                    {
                        "consumption": usage_entry.get("consumption"),
                        "cost": usage_entry.get("cost"),
                        "intervalEnd": interval_end,
                    }
                )

        return datapoints
