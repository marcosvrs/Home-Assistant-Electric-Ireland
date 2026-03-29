# Home Assistant Electric Ireland Integration

[![Open Integration](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=barreeeiroo&repository=Home-Assistant-Electric-Ireland&category=integration)

Home Assistant integration with **Electric Ireland insights**.

It is capable of:

* Reporting **consumed energy** in kWh.
* Reporting **usage cost** in EUR (see the FAQ below for more details on this).

It will also aggregate the report data into statistical buckets, so they can be fed into the Energy Dashboard. Data
is imported as external statistics directly into the recorder — no sensor entities are needed for energy or cost data.

![](https://i.imgur.com/6ew3JIf.png)

## FAQs

### How does it work?

It scrapes the Insights page that Electric Ireland provides. It will first mimic a user login interaction,
navigate to the Insights page for the configured account, and then call the MeterInsight API to fetch hourly usage data.

As this data is also fed from ESB ([Electrical Supply Board](https://esb.ie)), it is not in real time. They publish
data with 1-3 days delay; this integration takes care of that and will fetch every hour and ingest data. On first
install, it performs a 30-day backfill; subsequent runs look back 7 days to pick up any newly published data.

### Why not fetching from ESB directly?

I have Electric Ireland, and ESB has a captcha in their login. I just didn't want to bother to investigate how to
bypass it.

### Why not applying the 30% Off DD discount?

This is tariff-dependant. The Electric Ireland API reports cost as per tariff price (24h, smart, etc.), so in case some
tariff does not offer the 30% Off Direct Debit, this integration will apply a transformation incorrect for the user.

So, in summary: Cost reports gross usage cost with VAT, without discount but also without standing charge or levy.

### Why does the individual reported device sometimes exceed the reported usage in Electric Ireland?

I don't have a clear answer to this. I have noticed this in some buckets, but there it is an issue in how the metrics
are reported into buckets. It is an issue either in ESB / Electric Ireland reporting, that they report the intervals
incorrectly; or it is the device meters that they may do the same.

In either case, I would not expect the total amount to differ: it is just a matter of consumption/cost being reported
into the wrong hour. If you take the previous and after, the total should be the same.

## Technical Details

### Statistics

This integration imports external statistics directly into the HA recorder — no sensor entities are needed for the Energy Dashboard.

* **Electric Ireland Consumption** (`electric_ireland_insights:{account_number}_consumption`): hourly consumption in kWh. Use this in the Energy Dashboard as your grid consumption source.
* **Electric Ireland Cost** (`electric_ireland_insights:{account_number}_cost`): hourly cost in EUR (gross usage cost with VAT, without discounts or standing charge).

Both statistics are importable in the Energy Dashboard under **Settings → Energy → Grid consumption**.

### Diagnostic Entities

Two diagnostic sensor entities are created for monitoring the integration's health:

* **Last Import Time**: Timestamp of the last successful data import
* **Data Freshness**: How many days old the latest available data is (typically 1-3 days due to ESB reporting delay)

These appear in **Settings → Devices & services** under the integration's device.

### Data Retrieval Flow

1. Open an `aiohttp` session against the Electric Ireland website, and:
    1. Create a GET request to retrieve the cookies and the login state token.
    2. Do a POST request to login into Electric Ireland.
    3. Scrape the dashboard to find the `div` with the target Account Number.
    4. Navigate to the Insights page for that Account Number to obtain the meter IDs (partner, contract, premise).
2. Using the same session, call the MeterInsight API sequentially:
    1. For each day in the lookback window, request `/MeterInsight/{partner}/{contract}/{premise}/hourly-usage`.
    2. Each response contains 24 hourly datapoints with consumption (kWh) and cost (EUR) per tariff bucket.
    3. The active tariff bucket (flatRate, offPeak, midPeak, or onPeak) is extracted for each hour.
3. Import the collected datapoints as external statistics via `async_add_external_statistics`, maintaining cumulative sum continuity with any existing recorded data.

### Schedule

Every hour:

* Performs the login flow mentioned above to establish a session.
* On **first install**: fetches up to 30 days of historical data (backfill).
* On **subsequent runs**: fetches the last 7 days to pick up any newly published meter readings.
* Requests are made **sequentially** (one day at a time) to avoid rate limiting.
* Both consumption and cost are returned in the same response, with 24 hourly datapoints per day.
* Data is timestamped at the end of each hourly interval (e.g., `00:59:59` for the midnight hour) and normalized to the hour start for statistics alignment.

## Breaking Changes in v0.3.0

This is a **major architectural change**. If you are upgrading from v0.2.x:

1. **New statistic IDs**: Statistics are now imported as external statistics with IDs like `electric_ireland_insights:{account_number}_consumption`. The old entity-based statistics (`sensor.electric_ireland_consumption_*`) will no longer be updated.

2. **Energy Dashboard reconfiguration required**: You must re-configure your Energy Dashboard to use the new statistic IDs. Go to **Settings → Energy → Grid consumption** and select the new `electric_ireland_insights` statistics.

3. **Old statistics not migrated**: Historical data from v0.2.x will remain in your database but will not be carried over to the new statistic IDs. The integration will re-import up to 30 days of history on first startup.

4. **`homeassistant-historical-sensor` dependency removed**: The alpha library dependency has been removed. No action required — HA will uninstall it automatically.

## Acknowledgements

* [Opower integration](https://github.com/home-assistant/core/tree/dev/homeassistant/components/opower): served as the architectural reference for the external statistics and coordinator pattern used in v0.3.0.

