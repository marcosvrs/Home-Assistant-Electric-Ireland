"""Coordinator for Electric Ireland Insights."""
from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Literal

import aiohttp

from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.models import StatisticData, StatisticMetaData
from homeassistant.components.recorder.statistics import (
    StatisticMeanType,
    async_add_external_statistics,
    get_last_statistics,
    statistics_during_period,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfEnergy
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.aiohttp_client import async_create_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util.dt import utcnow
from homeassistant.util.unit_conversion import EnergyConverter

from .api import ElectricIrelandAPI
from .const import DOMAIN, INITIAL_LOOKBACK_DAYS, LOOKUP_DAYS, SCAN_INTERVAL
from .exceptions import CannotConnect, InvalidAuth
from .types import CoordinatorData, ElectricIrelandDatapoint, MeterIds

_LOGGER = logging.getLogger(__name__)


class ElectricIrelandCoordinator(DataUpdateCoordinator[CoordinatorData]):  # type: ignore[misc]  # DataUpdateCoordinator generic: HA typing incomplete
    """Coordinator to fetch EI data and import external statistics."""

    def __init__(self, hass: HomeAssistant, config_entry: ConfigEntry) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=SCAN_INTERVAL,
            always_update=True,
        )
        self.config_entry = config_entry
        self._account = config_entry.data["account_number"]
        self._api = ElectricIrelandAPI(
            config_entry.data["username"],
            config_entry.data["password"],
            self._account,
        )
        self._last_update_success = True
        self._has_imported_before = False

    async def _async_update_data(self) -> CoordinatorData:
        session = async_create_clientsession(
            self.hass, cookie_jar=aiohttp.CookieJar()
        )
        was_successful = self._last_update_success

        def _mark_success(result: CoordinatorData) -> CoordinatorData:
            self._last_update_success = True
            if not was_successful:
                _LOGGER.info("Connection restored — data import resumed")
            return result

        try:
            stat_id = f"{DOMAIN}:{self._account}_consumption"
            existing = await self.hass.async_add_executor_job(
                get_last_statistics,
                self.hass,
                1,
                stat_id,
                True,
                {"sum"},
            )
            lookback = LOOKUP_DAYS if existing else INITIAL_LOOKBACK_DAYS

            if not self._has_imported_before:
                self._has_imported_before = bool(existing)

            entry_data = self.config_entry.data
            cached_ids: MeterIds | None = None
            if (
                entry_data.get("partner_id")
                and entry_data.get("contract_id")
                and entry_data.get("premise_id")
            ):
                cached_ids = {
                    "partner": entry_data["partner_id"],
                    "contract": entry_data["contract_id"],
                    "premise": entry_data["premise_id"],
                }

            datapoints, new_meter_ids = await self._api.fetch_day_range(
                session, lookback_days=lookback, meter_ids=cached_ids
            )

            if new_meter_ids is not None:
                new_data = {
                    **dict(self.config_entry.data),
                    "partner_id": new_meter_ids["partner"],
                    "contract_id": new_meter_ids["contract"],
                    "premise_id": new_meter_ids["premise"],
                }
                self.hass.config_entries.async_update_entry(
                    self.config_entry, data=new_data
                )
                _LOGGER.debug(
                    "Updated cached meter IDs: partner=%s",
                    new_meter_ids["partner"],
                )

            if not datapoints:
                if self._has_imported_before:
                    if self.data is not None:
                        return _mark_success(self.data)
                    return _mark_success({
                        "last_import": None,
                        "datapoint_count": 0,
                        "latest_data_timestamp": None,
                        "import_error": "No new data available",
                    })
                return _mark_success({
                    "last_import": utcnow(),
                    "datapoint_count": 0,
                    "latest_data_timestamp": None,
                    "import_error": None,
                })

            self._has_imported_before = True

            await self._insert_statistics(
                datapoints,
                "consumption",
                f"{DOMAIN}:{self._account}_consumption",
                UnitOfEnergy.KILO_WATT_HOUR,
                EnergyConverter.UNIT_CLASS,
            )
            await self._insert_statistics(
                datapoints,
                "cost",
                f"{DOMAIN}:{self._account}_cost",
                "EUR",
                None,
            )

            last_ts = max((dp["intervalEnd"] for dp in datapoints), default=None)
            return _mark_success({
                "last_import": utcnow(),
                "datapoint_count": len(datapoints),
                "latest_data_timestamp": (
                    datetime.fromtimestamp(last_ts, tz=UTC) if last_ts else None
                ),
                "import_error": None,
            })

        except InvalidAuth as err:
            self._last_update_success = False
            raise ConfigEntryAuthFailed from err
        except CannotConnect as err:
            if was_successful:
                _LOGGER.warning(
                    "Connection lost — data import paused: %s",
                    err,
                )
            self._last_update_success = False
            raise UpdateFailed(f"Connection error: {err}") from err
        except (ConfigEntryAuthFailed, UpdateFailed):
            self._last_update_success = False
            raise
        except Exception as err:
            self._last_update_success = False
            _LOGGER.exception("Unexpected error during update")
            raise UpdateFailed(f"Unexpected error: {err}") from err

    async def _insert_statistics(
        self,
        datapoints: list[ElectricIrelandDatapoint],
        metric: Literal["consumption", "cost"],
        statistic_id: str,
        unit: str,
        unit_class: str | None,
    ) -> None:
        filtered = []
        for dp in datapoints:
            value = dp.get(metric)
            if value is None:
                continue
            interval_end = dp["intervalEnd"]
            start = datetime.fromtimestamp(interval_end, tz=UTC).replace(
                minute=0, second=0, microsecond=0
            )
            filtered.append((start, float(value)))

        if not filtered:
            return

        filtered.sort(key=lambda x: x[0])
        overlap_start = filtered[0][0]
        overlap_end = filtered[-1][0] + timedelta(hours=1)

        existing_before = await get_instance(self.hass).async_add_executor_job(
            statistics_during_period,
            self.hass,
            overlap_start - timedelta(hours=1),
            overlap_start,
            {statistic_id},
            "hour",
            None,
            {"sum"},
        )

        base_sum = 0.0
        if existing_before and statistic_id in existing_before:
            rows = existing_before[statistic_id]
            if rows:
                base_sum = rows[-1].get("sum") or 0.0

        statistics: list[StatisticData] = []
        current_sum = base_sum
        for start, value in filtered:
            current_sum += value
            statistics.append(
                StatisticData(
                    start=start,
                    state=value,
                    sum=current_sum,
                )
            )

        metadata = StatisticMetaData(
            mean_type=StatisticMeanType.NONE,
            has_sum=True,
            name=f"Electric Ireland {'Consumption' if metric == 'consumption' else 'Cost'} ({self._account})",
            source=DOMAIN,
            statistic_id=statistic_id,
            unit_class=unit_class,
            unit_of_measurement=unit,
        )

        async_add_external_statistics(self.hass, metadata, statistics)
