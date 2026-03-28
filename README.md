# Home Assistant Electric Ireland Integration

[![Open Integration](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=barreeeiroo&repository=Home-Assistant-Electric-Ireland&category=integration)

Home Assistant integration with **Electric Ireland insights**.

It is capable of:

* Reporting **consumed energy** in kWh.
* Reporting **usage cost** in EUR (see the FAQ below for more details on this).

It will also aggregate the report data into statistical buckets, so they can be fed into the Energy Dashboard.

![](https://i.imgur.com/6ew3JIf.png)

## FAQs

### How does it work?

It scrapes the Insights page that Electric Ireland provides. It will first mimic a user login interaction,
navigate to the Insights page for the configured account, and then call the MeterInsight API to fetch hourly usage data.

As this data is also fed from ESB ([Electrical Supply Board](https://esb.ie)), it is not in real time. They publish
data with 1-3 days delay; this integration takes care of that and will fetch every hour and ingest data dated back up
to 30 days. This job runs every hour, so whenever it gets published it should get fed into Home Assistant within 60
minutes.

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

### Sensors

* **Electric Ireland Consumption**: reports consumed data in kWh, in 60 minute intervals (24 datapoints per day).
* **Electric Ireland Cost**: reports the total cost charged in 60 minute intervals (without discounts and without
  standing charge, just the gross "usage" as per the contracted tariff).

### Data Retrieval Flow

1. Open a `requests` session against Electric Ireland website, and:
    1. Create a GET request to retrieve the cookies and the state.
    2. Do a POST request to login into Electric Ireland.
    3. Scrape the dashboard to try to find the `div` with the target Account Number.
    4. Navigate to the Insights page for that Account Number to obtain the meter IDs (partner, contract, premise).
2. Using the same session, call the MeterInsight API:
    1. For each day in the lookback window, request `/MeterInsight/{partner}/{contract}/{premise}/hourly-usage`.
    2. Each response contains 24 hourly datapoints with consumption (kWh) and cost (EUR) per tariff bucket.
    3. The active tariff bucket (flatRate, offPeak, midPeak, or onPeak) is extracted for each hour.

### Schedule

Every hour:

* Performs once the login flow mentioned above to establish a session.
* Launches requests for the 30th to 1st days before "now": if today is 20th January, then it will retrieve data
  for all days between the 21st of December and 19th of January.
* Both consumption and cost are returned in the same response, with 24 hourly datapoints per day.
* Data is timestamped at the end of each hourly interval (e.g., `00:59:59` for the midnight hour).

## Acknowledgements

* [Historical sensors for Home Assistant](https://github.com/ldotlopez/ha-historical-sensor): provided the library and
  skeleton to create the bare minimum working version.
