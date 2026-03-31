from __future__ import annotations

import logging
from datetime import UTC, date, datetime, time

import aiohttp
from bs4 import BeautifulSoup, Tag

from .const import DOMAIN, TARIFF_BUCKET_MAP
from .exceptions import AccountNotFound, CachedIdsInvalid, CannotConnect, InvalidAuth
from .types import BillPeriod, ElectricIrelandDatapoint, MeterIds

LOGGER = logging.getLogger(DOMAIN)

BASE_URL = "https://youraccountonline.electricireland.ie"


class ElectricIrelandAPI:
    def __init__(self, username: str, password: str, account_number: str | None = None) -> None:
        self._username = username
        self._password = password
        self._account_number = account_number

    async def discover_accounts(self, session: aiohttp.ClientSession) -> list[dict[str, str]]:
        """Scrape the post-login page and return all electricity account numbers.

        Returns a list of dicts with keys: account_number, display_name.
        Raises CannotConnect on network errors, AccountNotFound if no accounts found.
        """
        timeout = aiohttp.ClientTimeout(total=30)

        try:
            # Step 1: fetch login page to get tokens
            async with session.get(f"{BASE_URL}/", timeout=timeout) as res1:
                res1.raise_for_status()
                html1 = await res1.text()
                rvt_cookie = res1.cookies.get("rvt")
                rvt = rvt_cookie.value if rvt_cookie else None

            soup1 = BeautifulSoup(html1, "html.parser")
            source_input = soup1.find("input", attrs={"name": "Source"})
            source_val = source_input.get("value") if isinstance(source_input, Tag) else None
            source = source_val if isinstance(source_val, str) else None

            if not rvt:
                rvt_input = soup1.find("input", attrs={"name": "rvt"})
                rvt_val = rvt_input.get("value") if isinstance(rvt_input, Tag) else None
                rvt = rvt_val if isinstance(rvt_val, str) else None

            if not source or not rvt:
                raise CannotConnect("Could not extract login tokens")

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

        except (CannotConnect, AccountNotFound):
            raise
        except aiohttp.ClientError as err:
            raise CannotConnect(str(err)) from err
        except TimeoutError as err:
            raise CannotConnect("Connection timed out") from err

        soup2 = BeautifulSoup(html2, "html.parser")
        account_divs = soup2.find_all("div", {"class": "my-accounts__item"})

        if not account_divs:
            raise AccountNotFound("No accounts found for this user")

        accounts: list[dict[str, str]] = []
        for account_div in account_divs:
            account_number_el = account_div.find("p", {"class": "account-number"})
            if not account_number_el:
                continue
            account_number = account_number_el.text.strip()

            # Only include electricity accounts
            is_elec = account_div.find_all("h2", {"class": "account-electricity-icon"})
            if len(is_elec) != 1:
                continue

            # Build display name from account number + any label
            label_el = account_div.find("h3", {"class": "account-label"})
            label = label_el.text.strip() if label_el else None
            display_name = f"{account_number}" + (f" ({label})" if label else "")

            accounts.append(
                {
                    "account_number": account_number,
                    "display_name": display_name,
                }
            )

        if not accounts:
            raise AccountNotFound("No electricity accounts found for this user")

        LOGGER.info("Discovered %d account(s)", len(accounts))
        return accounts

    async def validate_credentials(self, session: aiohttp.ClientSession) -> MeterIds:
        client = await self._login(session)
        return {
            "partner": client._partner,
            "contract": client._contract,
            "premise": client._premise,
        }

    async def authenticate(
        self,
        session: aiohttp.ClientSession,
        meter_ids: MeterIds | None = None,
    ) -> tuple[MeterIds, MeterIds | None]:
        """Authenticate and return meter IDs.

        Returns:
            tuple: (meter_ids_to_use, discovered_ids_or_none)
                - meter_ids_to_use: Always valid MeterIds for subsequent API calls
                - discovered_ids_or_none: None if cached IDs were used,
                  or the newly discovered MeterIds if full login was performed.
                  When not None, caller should persist these to config entry.
        """
        client = await self._login(session, cached_meter_ids=meter_ids)
        if meter_ids is not None:
            return (meter_ids, None)
        discovered_ids: MeterIds = {
            "partner": client._partner,
            "contract": client._contract,
            "premise": client._premise,
        }
        return (discovered_ids, discovered_ids)

    async def get_bill_periods(
        self,
        session: aiohttp.ClientSession,
        meter_ids: MeterIds,
    ) -> list[BillPeriod]:
        partner = meter_ids["partner"]
        contract = meter_ids["contract"]
        premise = meter_ids["premise"]
        url = f"{BASE_URL}/MeterInsight/{partner}/{contract}/{premise}/bill-period"
        timeout = aiohttp.ClientTimeout(total=30)

        try:
            async with session.get(url, timeout=timeout) as response:
                if response.status == 204:
                    return []
                response.raise_for_status()
                self._check_session_expired(response)
                data = await response.json()
        except CannotConnect:
            raise
        except aiohttp.ClientError as err:
            raise CannotConnect(str(err)) from err
        except TimeoutError as err:
            raise CannotConnect("Connection timed out") from err

        if not (data.get("isSuccess") or data.get("IsSuccess")):
            return []
        return data.get("data", [])

    async def get_hourly_usage(
        self,
        session: aiohttp.ClientSession,
        meter_ids: MeterIds,
        target_date: date,
    ) -> list[ElectricIrelandDatapoint]:
        client = MeterInsightClient(session, meter_ids)
        return await client.get_data(datetime.combine(target_date, time.min, tzinfo=UTC))

    def _check_session_expired(self, response: aiohttp.ClientResponse) -> None:
        content_type = response.headers.get("content-type", "")
        if "text/html" in content_type:
            raise CannotConnect("Session expired")

    async def _login(
        self,
        session: aiohttp.ClientSession,
        cached_meter_ids: MeterIds | None = None,
    ) -> MeterInsightClient:
        timeout = aiohttp.ClientTimeout(total=30)

        try:
            LOGGER.debug("Getting Source Token...")
            async with session.get(f"{BASE_URL}/", timeout=timeout) as res1:
                res1.raise_for_status()
                html1 = await res1.text()
                rvt_cookie = res1.cookies.get("rvt")
                rvt = rvt_cookie.value if rvt_cookie else None

            soup1 = BeautifulSoup(html1, "html.parser")
            source_input = soup1.find("input", attrs={"name": "Source"})
            source_val = source_input.get("value") if isinstance(source_input, Tag) else None
            source = source_val if isinstance(source_val, str) else None

            if not rvt:
                rvt_input = soup1.find("input", attrs={"name": "rvt"})
                rvt_val = rvt_input.get("value") if isinstance(rvt_input, Tag) else None
                rvt = rvt_val if isinstance(rvt_val, str) else None

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
                account_number_el = account_div.find("p", {"class": "account-number"})
                if not account_number_el:
                    continue
                account_number = account_number_el.text.strip()
                if account_number != self._account_number:
                    LOGGER.debug("Skipping account %s as it is not target", account_number)
                    continue

                is_elec_divs = account_div.find_all("h2", {"class": "account-electricity-icon"})
                if len(is_elec_divs) != 1:
                    LOGGER.info("Found account %s but is not Electricity", account_number)
                    continue

                target_account = account_div
                break

            if not target_account:
                raise AccountNotFound(f"Account {self._account_number} not found")

            LOGGER.debug("Navigating to Insights page...")
            event_form = target_account.find("form", {"action": "/Accounts/OnEvent"})
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

            if cached_meter_ids is not None:
                LOGGER.debug(
                    "Using cached meter IDs: partner=%s, contract=%s, premise=%s",
                    cached_meter_ids.get("partner"),
                    cached_meter_ids.get("contract"),
                    cached_meter_ids.get("premise"),
                )
                return MeterInsightClient(session, cached_meter_ids)

            soup3 = BeautifulSoup(html3, "html.parser")
            model_data = soup3.find("div", {"id": "modelData"})

            if not model_data:
                raise InvalidAuth("Login succeeded but insights page not accessible")

            assert isinstance(model_data, Tag)

            partner = model_data.get("data-partner")
            contract = model_data.get("data-contract")
            premise = model_data.get("data-premise")

            if not all([partner, contract, premise]):
                raise InvalidAuth("Login succeeded but insights page not accessible")

            assert isinstance(partner, str)
            assert isinstance(contract, str)
            assert isinstance(premise, str)

            LOGGER.info(
                "Found meter IDs: partner=%s, contract=%s, premise=%s",
                partner,
                contract,
                premise,
            )
            return MeterInsightClient(session, {"partner": partner, "contract": contract, "premise": premise})

        except (InvalidAuth, CannotConnect, AccountNotFound):
            raise
        except aiohttp.ClientError as err:
            raise CannotConnect(str(err)) from err
        except TimeoutError as err:
            raise CannotConnect("Connection timed out") from err


class MeterInsightClient:
    def __init__(self, session: aiohttp.ClientSession, meter_ids: MeterIds) -> None:
        self._session = session
        self._partner = meter_ids["partner"]
        self._contract = meter_ids["contract"]
        self._premise = meter_ids["premise"]

    async def get_data(self, target_date: datetime) -> list[ElectricIrelandDatapoint]:
        date_str = target_date.strftime("%Y-%m-%d")
        LOGGER.debug("Getting hourly data for %s...", date_str)

        url = f"{BASE_URL}/MeterInsight/{self._partner}/{self._contract}/{self._premise}/hourly-usage"
        timeout = aiohttp.ClientTimeout(total=30)

        try:
            async with self._session.get(url, params={"date": date_str}, timeout=timeout) as response:
                if response.status in (401, 403, 404):
                    raise CachedIdsInvalid(f"API returned {response.status}")

                if response.status == 204:
                    LOGGER.debug("No data available for %s (HTTP 204)", date_str)
                    return []

                response.raise_for_status()

                content_type = response.headers.get("content-type", "")
                if "application/json" not in content_type:
                    body = await response.text()
                    LOGGER.error(
                        "Expected JSON but got %s. Response: %s",
                        content_type,
                        body[:500],
                    )
                    raise CachedIdsInvalid("Non-JSON response from MeterInsight API — session may be expired")

                try:
                    data = await response.json()
                except Exception as err:
                    body = await response.text()
                    LOGGER.error("Failed to parse JSON: %s. Response: %s", err, body[:500])
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

            active_key = next(
                (key for key in usage_tariff_keys if dp.get(key) is not None),
                None,
            )

            if active_key is not None:
                usage_entry = dp[active_key]
                datapoints.append(
                    {
                        "consumption": usage_entry.get("consumption"),
                        "cost": usage_entry.get("cost"),
                        "intervalEnd": interval_end,
                        "tariff_bucket": TARIFF_BUCKET_MAP.get(active_key, active_key),
                    }
                )

        return datapoints
