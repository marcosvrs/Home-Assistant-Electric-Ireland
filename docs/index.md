---
title: Electric Ireland Insights
description: Instructions on how to integrate Electric Ireland energy data into Home Assistant.
ha_category:
  - Energy
ha_release: "2024.1"
ha_iot_class: Cloud Polling
ha_config_flow: true
ha_codeowners:
  - "@barreeeiroo"
ha_domain: electric_ireland_insights
ha_platforms:
  - diagnostics
  - sensor
ha_integration_type: service
ha_quality_scale: platinum
---

# Electric Ireland Insights

[Electric Ireland](https://www.electricireland.ie/) is an Irish electricity and gas supplier. This integration imports hourly energy consumption and cost data from the Electric Ireland Insights portal directly into the Home Assistant Energy Dashboard as external statistics.

## Prerequisites

- An active Electric Ireland account with **Insights access** enabled
- A **smart meter** installed at your premises (required for hourly data)

## Installation

1. Install via [HACS](https://hacs.xyz/) (search for "Electric Ireland Insights") or manually copy `custom_components/electric_ireland_insights/` to your HA config directory.
2. Restart Home Assistant.
3. Go to **Settings** → **Devices & services**.
4. Click **+ Add integration**.
5. Search for and select **Electric Ireland Insights**.
6. Follow the on-screen instructions to complete the setup.

During setup you will be asked for:

| Parameter | Description |
|-----------|-------------|
| **Username** | Your Electric Ireland portal email address |
| **Password** | Your Electric Ireland portal password |

After authenticating, the integration discovers all electricity accounts linked to your login. If only one account is found, it is selected automatically. If multiple accounts are found, a dropdown is shown for you to select which account to configure. Each config entry supports one account — add the integration again for additional accounts.

## Removal

1. Go to **Settings** → **Devices & services**.
2. Select the **Electric Ireland Insights** integration card.
3. Click the three-dot menu (**⋮**) and select **Delete**.

## Data update

The integration polls the Electric Ireland Insights API **every hour**.

- **First install**: imports up to **30 days** of historical data (backfill).
- **Subsequent runs**: imports the last **7 days** to pick up newly published readings.
- **Pre-flight optimization**: before fetching hourly data, the integration calls the `/bill-period` endpoint to discover which date ranges contain meter data. Hourly requests are then bounded to dates within known billing periods, reducing unnecessary API calls. If the pre-flight call fails, the integration falls back to the full lookback window.
- **Provider delay**: Electric Ireland publishes meter data with a **1-3 day delay** (data comes from ESB). The `Data Freshness` diagnostic sensor shows how old the latest available reading is.

## Statistics

This integration imports data as **external statistics** directly into the HA recorder — no sensor entities are needed for the Energy Dashboard.

### Grid consumption and cost (hourly resolution)

| Statistic ID | Description | Unit |
|---|---|---|
| `electric_ireland_insights:{account_number}_consumption` | Hourly electricity consumption | kWh |
| `electric_ireland_insights:{account_number}_cost` | Hourly electricity cost (gross, with VAT, no discounts or standing charge) | EUR |

Add these statistics to the Energy Dashboard under **Settings → Energy → Grid consumption**.

## Diagnostic entities

Two diagnostic sensor entities are created under the integration's device:

| Entity | Description |
|--------|-------------|
| **Last Import Time** | Timestamp of the last successful data import |
| **Data Freshness** | How many days old the latest available reading is (typically 1–3 days) |

These entities are **disabled by default** and can be enabled in **Settings → Devices & services**.

## Reconfiguration

To update your password or troubleshoot data import issues, use **Settings → Devices & services → Electric Ireland Insights → ⋮ → Reconfigure**.

| Option | Description |
|--------|-------------|
| **Password** | Re-enter your current password (required even if unchanged) |
| **Re-discover meter IDs** | Clears the cached meter identifiers (partner, contract, premise) and forces the integration to re-discover them from the Electric Ireland portal on the next refresh. Use this when data imports have stopped but your credentials are still valid — typically caused by Electric Ireland changing internal account identifiers after a meter swap or account migration. |

If the password has changed, cached meter IDs are cleared automatically — you don't need to check the re-discovery option.

## Automation example

Notify when data has not been updated for more than 5 days:

```yaml
automation:
  - alias: "Alert: Electric Ireland data stale"
    triggers:
      - trigger: numeric_state
        entity_id: sensor.electric_ireland_insights_data_freshness
        above: 5
    actions:
      - action: notify.mobile_app
        data:
          message: "Electric Ireland data is {{ states('sensor.electric_ireland_insights_data_freshness') }} days old."
```

## Known limitations

- **1-3 day data delay**: Hourly readings are published by ESB with a delay; this integration cannot fetch data faster than ESB publishes it.
- **Cost excludes discounts and standing charges**: The reported cost is the gross tariff cost with VAT. It does not include the 30% Off Direct Debit discount, standing charges, or levies.
- **Scraping dependency**: The integration authenticates via the Electric Ireland web portal. Changes to the portal's HTML structure may break the login flow until the integration is updated.
- **Single account per entry**: Each config entry supports one electricity account. To monitor multiple accounts, add the integration once per account.

## Troubleshooting

### Login failure / Invalid credentials

Verify your username and password by logging in at [youraccountonline.electricireland.ie](https://youraccountonline.electricireland.ie). If your password has changed, use **Reconfigure** to update it.

### Account not found

The integration automatically discovers electricity accounts linked to your login. If no accounts are found, ensure your login has an **electricity** account with Insights access enabled (gas-only accounts are not supported). You can verify by logging in at [youraccountonline.electricireland.ie](https://youraccountonline.electricireland.ie) and checking the Insights section.

### No data / Data freshness increasing

Electric Ireland publishes data with a 1–3 day delay. If freshness exceeds 5 days, check:
1. Your smart meter is functioning correctly.
2. The Electric Ireland Insights portal shows data at [youraccountonline.electricireland.ie](https://youraccountonline.electricireland.ie).
3. The integration logs for errors (**Settings → System → Logs**, filter by `electric_ireland_insights`).

### Re-authentication required

If the integration enters a re-authentication state, go to **Settings → Devices & services → Electric Ireland Insights** and follow the re-authentication flow to update your credentials.

### Debug logging

To help diagnose issues, enable debug logging for this integration:

1. Go to **Settings → Devices & services → Electric Ireland Insights → ⋮ → Enable debug logging**.
2. Reproduce the issue.
3. Go back and select **Disable debug logging** to download the log file.

Alternatively, add the following to your `configuration.yaml`:

```yaml
logger:
  logs:
    custom_components.electric_ireland_insights: debug
```
