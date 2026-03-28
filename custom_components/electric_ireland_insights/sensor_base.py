import asyncio
import logging
import statistics
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, UTC
from typing import List

from homeassistant.components.recorder.models import StatisticData, StatisticMetaData
from homeassistant.components.recorder.statistics import StatisticMeanType, StatisticsRow
from homeassistant.components.sensor import SensorDeviceClass, SensorEntity

from homeassistant_historical_sensor import (
    HistoricalSensor,
    HistoricalState,
    PollUpdateMixin,
    group_by_interval,
)
from homeassistant.helpers.event import async_track_time_interval

from .api import ElectricIrelandScraper
from .const import DOMAIN, LOOKUP_DAYS, PARALLEL_DAYS


LOGGER = logging.getLogger(DOMAIN)


class Sensor(PollUpdateMixin, HistoricalSensor, SensorEntity):

    def __init__(self, device_id: str, ei_api: ElectricIrelandScraper, name: str, metric: str, measurement_unit: str,
                 device_class: SensorDeviceClass):
        super().__init__()

        self._attr_has_entity_name = True
        self._attr_name = f"Electric Ireland {name}"

        self._attr_unique_id = f"{DOMAIN}_{metric}_{device_id}"
        self._attr_entity_id = f"{DOMAIN}_{metric}_{device_id}"

        self._attr_entity_registry_enabled_default = True

        self._attr_native_unit_of_measurement = measurement_unit
        self._attr_device_class = device_class

        self._api: ElectricIrelandScraper = ei_api
        self._metric = metric

    async def async_added_to_hass(self) -> None:
        # Skip PollUpdateMixin.async_added_to_hass which blocks startup by
        # awaiting the first data fetch. Instead call HistoricalSensor's version
        # directly, schedule the initial fetch as a background task, and set up
        # the periodic timer ourselves.
        await HistoricalSensor.async_added_to_hass(self)

        self.hass.async_create_task(
            self._async_historical_handle_update()
        )

        self._remove_time_tracker_fn = async_track_time_interval(
            self.hass,
            self._async_historical_handle_update,
            self.UPDATE_INTERVAL,
        )

    async def async_update_historical(self):
        # Important: You must provide timestamps as UTC unix timestamps

        loop = asyncio.get_running_loop()

        datapoints = await loop.run_in_executor(None, self._api.fetch_day_range)
        if datapoints is None:
            LOGGER.error("Failed to fetch data - login may have failed")
            return

        hist_states: List[HistoricalState] = []
        for datapoint in datapoints:
            state = datapoint.get(self._metric)
            interval_end = datapoint.get("intervalEnd")
            hist_states.append(HistoricalState(
                state=state,
                timestamp=interval_end,
            ))

        hist_states.sort(key=lambda d: d.timestamp)

        valid_datapoints: List[HistoricalState] = []
        null_datapoints: List[HistoricalState] = []
        invalid_datapoints: List[HistoricalState] = []
        for hist_state in hist_states:
            if hist_state.state is None:
                null_datapoints.append(hist_state)
                continue
            if not isinstance(hist_state.state, (int, float,)):
                invalid_datapoints.append(hist_state)
                continue
            valid_datapoints.append(hist_state)

        if null_datapoints:
            min_ts = datetime.fromtimestamp(null_datapoints[0].timestamp, tz=UTC)
            max_ts = datetime.fromtimestamp(null_datapoints[-1].timestamp, tz=UTC)
            LOGGER.info(f"Found {len(null_datapoints)} null datapoints, ranging from {min_ts} to {max_ts}")

        if invalid_datapoints:
            LOGGER.warning(f"Found {len(invalid_datapoints)} invalid datapoints!")

        if not valid_datapoints:
            LOGGER.error("Found no valid datapoints!")
        else:
            min_ts = datetime.fromtimestamp(valid_datapoints[0].timestamp, tz=UTC)
            max_ts = datetime.fromtimestamp(valid_datapoints[-1].timestamp, tz=UTC)
            LOGGER.info(f"Found {len(valid_datapoints)} valid datapoints, ranging from {min_ts} to {max_ts}")

        self._attr_historical_states = [d for d in hist_states if d.state]

    def get_statistic_metadata(self) -> StatisticMetaData:
        meta = super().get_statistic_metadata()
        meta["has_sum"] = True
        meta["mean_type"] = StatisticMeanType.ARITHMETIC

        return meta

    async def async_calculate_statistic_data(
            self, hist_states: list[HistoricalState], *, latest: StatisticsRow | None = None
    ) -> list[StatisticData]:
        accumulated = latest["sum"] if latest else 0

        ret = []
        for block_ts, collection_it in group_by_interval(hist_states):
            collection = list(collection_it)
            mean = statistics.mean([x.state for x in collection])
            partial_sum = sum([x.state for x in collection])
            accumulated = accumulated + partial_sum

            ret.append(
                StatisticData(
                    start=datetime.fromtimestamp(block_ts, tz=UTC),
                    state=partial_sum,
                    mean=mean,
                    sum=accumulated,
                )
            )

        return ret
