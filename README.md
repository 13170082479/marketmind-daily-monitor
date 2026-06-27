# MarketMind Daily Monitor

A standalone daily market monitor that builds a Chinese market brief and pushes it to a Feishu custom bot webhook.

## Recommended Deployment

Use GitHub Actions as the primary scheduler. Your computer can stay off.

## What it monitors
- DXY
- US10Y and US02Y
- Nasdaq 100 futures
- Gold
- BTC ETF flows from Farside Investors
- BTC 4H / 1H / 15m structure using EMA20 / EMA50 / EMA100
- Feishu interactive card push

## Setup

1. Create a GitHub repository and push this project to GitHub.
2. Go to `Settings -> Secrets and variables -> Actions`.
3. Add the secrets listed below.
4. Confirm `.github/workflows/market-brief.yml` exists in the repo.
5. Open the `Actions` tab and use `Run workflow` to test.
6. After the test succeeds, the scheduled cron runs will handle the daily pushes automatically.

## GitHub Secrets

Required:
- `FEISHU_WEBHOOK_URL`

Optional, used if you want extra signing or future data-provider expansion:
- `FEISHU_SECRET`
- `MARKET_API_KEY`
- `BINANCE_API_KEY`
- `BINANCE_API_SECRET`

## Schedule

The workflow runs in UTC and maps to Beijing time like this:

- 09:00 CST = `0 1 * * *`
- 15:00 CST = `0 7 * * *`
- 21:30 CST = `30 13 * * *`
- 22:30 CST = `30 14 * * *`

## Cloud entry script

The cloud-safe entry point is:

```bash
python scripts/send_market_brief.py
```

It does one thing only:
- fetch latest data
- build the Feishu card
- send the card
- exit

## Manual Test in GitHub Actions

1. Open the repository on GitHub.
2. Go to `Actions`.
3. Select `Market Brief`.
4. Click `Run workflow`.
5. Watch the job logs.

## How to verify success

- The job should finish with a green check.
- The Feishu group should receive the interactive card.
- The last step log should show the send result.

## Where to check logs if it fails

- GitHub repository `Actions` tab
- The failed workflow run
- The `Send market brief` step output

## Local backup

Local Windows scheduling is still available as a backup, but it is no longer the primary deployment path.

If you still want to test locally:

```bash
pip install -e .
python -m marketmind_api.scripts.run_daily_market_monitor --print-only
python scripts/send_market_brief.py
```

## Environment

This project still supports local `.env` files for backup testing, but cloud runs should use GitHub Secrets.
