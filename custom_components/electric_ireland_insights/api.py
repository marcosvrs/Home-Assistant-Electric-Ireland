import logging
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, UTC

import requests
from bs4 import BeautifulSoup
from requests import RequestException

from .const import DOMAIN, LOOKUP_DAYS, PARALLEL_DAYS


LOGGER = logging.getLogger(DOMAIN)

BASE_URL = "https://youraccountonline.electricireland.ie"

CACHE_TTL_SECONDS = 300


class ElectricIrelandScraper:
    def __init__(self, username, password, account_number):
        self.__scraper = None

        self.__username = username
        self.__password = password
        self.__account_number = account_number

        self.__cached_datapoints: list[dict] | None = None
        self.__cache_timestamp: float = 0

    def fetch_day_range(self) -> list[dict] | None:
        now = time.monotonic()
        if self.__cached_datapoints is not None and (now - self.__cache_timestamp) < CACHE_TTL_SECONDS:
            LOGGER.debug("Using cached datapoints")
            return self.__cached_datapoints

        self.__refresh_credentials()
        scraper = self.__scraper
        if not scraper:
            return None

        yesterday = datetime(
            year=datetime.now(UTC).year,
            month=datetime.now(UTC).month,
            day=datetime.now(UTC).day,
            tzinfo=UTC,
        ) - timedelta(days=1)

        all_datapoints = []
        executor_futures = []

        with ThreadPoolExecutor(max_workers=PARALLEL_DAYS) as executor:
            current_date = yesterday - timedelta(days=LOOKUP_DAYS)
            while current_date <= yesterday:
                LOGGER.debug(f"Submitting {current_date}")
                future = executor.submit(scraper.get_data, current_date)
                executor_futures.append(future)
                current_date += timedelta(days=1)

        LOGGER.info("Finished launching jobs")

        for future in executor_futures:
            try:
                all_datapoints.extend(future.result())
            except Exception as err:
                LOGGER.error(f"Failed to get data: {err}")

        self.__cached_datapoints = all_datapoints
        self.__cache_timestamp = time.monotonic()

        return all_datapoints

    def __refresh_credentials(self):
        LOGGER.info("Trying to refresh credentials...")
        session = requests.Session()

        meter_ids = self.__login_and_get_meter_ids(session)
        if not meter_ids:
            return

        self.__scraper = MeterInsightScraper(session, meter_ids)

    def __login_and_get_meter_ids(self, session):
        LOGGER.debug("Getting Source Token...")
        res1 = session.get(f"{BASE_URL}/")
        try:
            res1.raise_for_status()
        except RequestException as err:
            LOGGER.error(f"Failed to Get Source Token: {err}")
            return None

        soup1 = BeautifulSoup(res1.text, "html.parser")
        source_input = soup1.find('input', attrs={'name': 'Source'})
        source = source_input.get('value') if source_input else None
        rvt = session.cookies.get_dict().get("rvt")

        if not source:
            LOGGER.error("Could not retrieve Source")
            return None
        if not rvt:
            LOGGER.error("Could not find rvt cookie")
            return None

        LOGGER.debug("Performing Login...")
        res2 = session.post(
            f"{BASE_URL}/",
            data={
                "LoginFormData.UserName": self.__username,
                "LoginFormData.Password": self.__password,
                "rvt": rvt,
                "Source": source,
                "PotText": "",
                "__EiTokPotText": "",
                "ReturnUrl": "",
                "AccountNumber": "",
            },
        )
        try:
            res2.raise_for_status()
        except RequestException as err:
            LOGGER.error(f"Failed to Perform Login: {err}")
            return None

        soup2 = BeautifulSoup(res2.text, "html.parser")
        account_divs = soup2.find_all("div", {"class": "my-accounts__item"})
        target_account = None
        for account_div in account_divs:
            account_number_el = account_div.find("p", {"class": "account-number"})
            if not account_number_el:
                continue
            account_number = account_number_el.text
            if account_number != self.__account_number:
                LOGGER.debug(f"Skipping account {account_number} as it is not target")
                continue

            is_elec_divs = account_div.find_all("h2", {"class": "account-electricity-icon"})
            if len(is_elec_divs) != 1:
                LOGGER.info(f"Found account {account_number} but is not Electricity")
                continue

            target_account = account_div
            break

        if not target_account:
            LOGGER.warning("Failed to find Target Account; please verify it is the correct one")
            return None

        LOGGER.debug("Navigating to Insights page...")
        event_form = target_account.find("form", {"action": "/Accounts/OnEvent"})
        req3 = {"triggers_event": "AccountSelection.ToInsights"}
        for form_input in event_form.find_all("input"):
            req3[form_input.get("name")] = form_input.get("value")

        res3 = session.post(
            f"{BASE_URL}/Accounts/OnEvent",
            data=req3,
        )
        try:
            res3.raise_for_status()
        except RequestException as err:
            LOGGER.error(f"Failed to Navigate to Insights: {err}")
            return None

        soup3 = BeautifulSoup(res3.text, "html.parser")
        model_data = soup3.find("div", {"id": "modelData"})

        if not model_data:
            LOGGER.error("Failed to find modelData div on Insights page")
            return None

        partner = model_data.get("data-partner")
        contract = model_data.get("data-contract")
        premise = model_data.get("data-premise")

        if not all([partner, contract, premise]):
            LOGGER.error(f"Missing meter IDs: partner={partner}, contract={contract}, premise={premise}")
            return None

        LOGGER.info(f"Found meter IDs: partner={partner}, contract={contract}, premise={premise}")
        return {"partner": partner, "contract": contract, "premise": premise}


class MeterInsightScraper:

    def __init__(self, session, meter_ids):
        self.__session = session
        self.__partner = meter_ids["partner"]
        self.__contract = meter_ids["contract"]
        self.__premise = meter_ids["premise"]

    def get_data(self, target_date, is_granular=False):
        date_str = target_date.strftime("%Y-%m-%d")
        LOGGER.debug(f"Getting hourly data for {date_str}...")

        url = f"{BASE_URL}/MeterInsight/{self.__partner}/{self.__contract}/{self.__premise}/hourly-usage"

        try:
            response = self.__session.get(url, params={"date": date_str})
            response.raise_for_status()
        except RequestException as err:
            LOGGER.error(f"Failed to get hourly usage data: {err}")
            return []

        content_type = response.headers.get('content-type', '')
        if 'application/json' not in content_type:
            LOGGER.error(f"Expected JSON but got {content_type}. Response: {response.text[:500]}")
            return []

        try:
            data = response.json()
        except Exception as err:
            LOGGER.error(f"Failed to parse JSON: {err}. Response: {response.text[:500]}")
            return []

        if not data.get("isSuccess"):
            LOGGER.error(f"API returned error: {data.get('message')}")
            return []

        raw_datapoints = data.get("data", [])
        LOGGER.debug(f"Found {len(raw_datapoints)} hourly datapoints for {date_str}")

        datapoints = []
        usage_tariff_keys = ("flatRate", "offPeak", "midPeak", "onPeak")

        for dp in raw_datapoints:
            end_date_str = dp.get("endDate")

            if not end_date_str:
                continue

            try:
                end_dt = datetime.fromisoformat(end_date_str.replace("Z", "+00:00"))
                interval_end = int(end_dt.timestamp())
            except (ValueError, AttributeError) as err:
                LOGGER.warning(f"Failed to parse date {end_date_str}: {err}")
                continue

            usage_entry = next(
                (dp[key] for key in usage_tariff_keys if dp.get(key) is not None),
                None
            )

            if usage_entry is not None:
                datapoints.append({
                    "consumption": usage_entry.get("consumption"),
                    "cost"       : usage_entry.get("cost"),
                    "intervalEnd": interval_end,
                })

        return datapoints
