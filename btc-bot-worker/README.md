# BTC BOT background worker

This process remains running independently of a browser. It streams authenticated BRTI, collects Kalshi BTC 15-minute rounds and order books, and submits fresh snapshots to the private BTC BOT cloud paper engine. It has no production-order write capability. The persistent journal and trading decisions live in the Site's D1 database, so a worker restart does not erase positions or permit duplicate round entries.

## Activation requirements

1. Connect a cloud provider supporting a continuous background worker (Render blueprint supplied). Confirm the paid service price before creation. Do not use a sleeping web service or an interactive terminal as 24/7 hosting.
2. Provide a Kalshi production API key and private key via the provider's secret environment settings. Verify BRTI availability for the account. Never paste keys into source or the dashboard.
3. Configure the Site service credential in `BTC_BOT_SITE_TOKEN`, and the matching dedicated `BTC_BOT_WORKER_SECRET` in the provider. These are supplied through the authorized Sites setup workflow; no secrets ship in this repository.
4. Start exactly one worker. The server lease prevents concurrent snapshots from different instances from creating duplicate entries.
5. Arm paper mode in the Site or BTC BOT plugin. Verify a fresh worker heartbeat, actual BRTI data, an active market, fresh order book, and at least 20 contiguous one-minute BRTI bars. History can take approximately 20–30 minutes to warm up when historical access is unavailable.

Worker checkpoints are delivered approximately once per second plus request latency. Order-book snapshots are polled about once per second; round discovery every five seconds. BRTI is streamed over WebSocket. Reconnect, missing-data, target, timing, lease, and paper-budget checks are mandatory. No guarantee of zero latency or uninterrupted upstream availability.

For a supported Python 3.12+ environment:

```sh
python -m pip install -r requirements.txt
python -m btc_worker.main
```

Run from this `runner` directory with secret environment variables configured. `render.yaml` is a deployment template; its presence does not mean a service is deployed. The app currently remains inactive until credentials and a background host are connected.

## Paper model and fills

The model is explicitly experimental and uncalibrated. All price features use BRTI. The Kalshi book replaces the earlier Coinbase imbalance factor; the trade-flow factor is zero until separately implemented and validated. Scores are not probabilities and cannot establish expected-value edge.

Each round permits at most one paper entry attempt. Entry intent is saved before a simulated one-second delay. A later fresh ask must remain at or below the limit with enough displayed size; otherwise the intent is cancelled. Paper positions are held to official settlement. Reported P&L includes the configurable fee estimate (default $0.03 per contract), not a claim about exact venue fees or attainable fills. Daily loss budget includes unsettled maximum loss and resets at 00:00 UTC. Existing positions settle while new entries are paused.

## Kalshi demo smoke test

Demo credentials are separate from production. A dry run prints a single-contract IOC request without sending it:

```sh
python -m btc_worker.demo --ticker ACTUAL_KXBTC15M_DEMO_TICKER --outcome yes --limit 0.10
```

Use a real open demo ticker starting with KXBTC15M. To submit to the hardcoded demo host only, supply `KALSHI_DEMO_API_KEY_ID`, `KALSHI_DEMO_PRIVATE_KEY`, and append `--submit --journal /persistent/path/demo.sqlite3`. Confirm the demo ticker exists first; demo liquidity can differ from production.

The harness persists the client order ID before POST, never retries an uncertain submission, and reads back acknowledged orders. Uncertain attempts block new submissions until manually reconciled against demo account orders. This is an execution smoke test, not an automated demo trading strategy. Acknowledgment is not a fill guarantee.

## Tests

```sh
python -m unittest discover -s tests -v
```
