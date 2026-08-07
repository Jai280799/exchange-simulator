# Exchange Simulator

An event-driven exchange simulator built for MAFS 5360 Group 1. It replays real
tick data, matches strategy orders against the replayed book with price-time
priority, and writes inspectable results — as eight cooperating processes on a
typed message bus.

**Group members:** LIM, Hyungmin (leader) · JITENDRA JAIN, Jai · KONG, Lington

---

## Quick start

Four commands and a browser, on a clean machine.

```bash
git clone https://github.com/Jai280799/exchange-simulator.git
cd exchange-simulator

python3 -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -e . -r test_requirements.txt

mkdir -p var && cp /path/to/2603_md_202108_202108.csv.gz var/

python -m exchange_simulator
```

Then open **<http://127.0.0.1:8000>**, pick a data file, and press **Start**.

Two details decide whether this works first time:

- **Install with `pip install -e .`**, not just `pip install -r requirements.txt`.
  Components run in separate processes started with `spawn`; each one re-imports
  the package, so it has to be importable rather than merely on the path.
- **Market data lives in `var/`.** The dashboard lists whatever `.csv` or
  `.csv.gz` files it finds there. The directory is gitignored, so the files never
  travel with the repository.

Requires **Python 3.12 or newer**.

---

## Using the dashboard

The header carries every control:

| Control | Meaning |
|---|---|
| **data** | Which file in `var/` to replay. Choosing one fills in the instrument and a date the file actually contains. |
| **instrument** | Must match the data. Each instrument has its own tick and lot size, so a mismatch prices orders wrongly. |
| **date** | One trading day. Leave it blank to replay every day in the file. |
| **rows/sec** | Replay pace in source rows per second. `500` is comfortable to narrate; `0` means as fast as the bus allows. |
| **impact ticks/level** | Extra slippage per depth level, in ticks. `0` by default — see [execution realism](#execution-realism). |
| **queue turnover** | Passive orders queue behind displayed volume. On by default. |
| **Start / Pause / Stop** | Pause holds the feed between rows; the session stays alive and resumes from the same row. |

Three tabs: **Live** (candles with traded volume, the order book ladder, the
trade tape, strategy P&L and blotters), **Session** (counters, component health,
strategy selection, run configuration), and **Log** (the running session's log,
with a filter — try `queue turnover`).

### Outputs

Every run writes to `runs/<run-id>/`:

| File | Contents |
|---|---|
| `orders.csv` | Every order the trading platform accepted, with status changes |
| `simulated-trades.csv` | Trades produced by **our** orders — never historical prints |
| `executions.csv` | Per-order execution reports |
| `summary.json` | Final state, counters, and per-strategy position and P&L |
| `run-config.json` | Exactly what was configured, so a run can be reproduced |
| `system.log` | Every component process, one file |

---

## Configuration

Settings come from `SessionConfig` and can be sent to the start endpoint. The
dashboard exposes the common ones; anything else can be posted directly:

```bash
curl -X POST http://127.0.0.1:8000/api/session/start \
  -H 'Content-Type: application/json' \
  -d '{"date": "2021-08-02", "replay_interval_seconds": 0.002,
       "queue_turnover": true, "market_impact_ticks_per_level": 0}'
```

Environment variables:

| Variable | Default | Purpose |
|---|---|---|
| `EXCHANGE_SIMULATOR_HOST` | `127.0.0.1` | Interface to bind |
| `EXCHANGE_SIMULATOR_PORT` | `8000` | Port to bind |
| `EXCHANGE_SIMULATOR_USER` | `admin` | Dashboard username |
| `EXCHANGE_SIMULATOR_PASSWORD` | *(unset)* | Dashboard password. **Unset means no authentication**, which is fine on loopback and not fine on any reachable interface. |

Instruments are declared in `config/instruments.yaml` — tick size and lot size
per instrument, which the engine enforces on every order.

### Execution realism

Two settings control how faithful execution is. Both are per session.

- **`queue_turnover`** (default **on**) — a resting order records the volume
  displayed at its price and joins the back of the queue. Historical trade prints
  consume that volume before reaching us, so a snapshot touching our price is not
  enough to fill a queued order. Cancelling the last order at a price forfeits
  the position, as on a real book.
- **`market_impact_ticks_per_level`** (default **0**) — depth consumption is
  already priced exactly, because an aggressive order walks the book level by
  level and pays each level's own price. A penalty on top would charge twice for
  the same effect. Raise it only to price liquidity beyond the five visible
  levels. See [ADR 0008](docs/decisions/0008-execution-realism-defaults.md).

---

## Development

```bash
pytest                      # the full suite, including real multi-process runs
pytest tests/test_queue_turnover.py -v
```

Two scripts explain the passive-fill model better than prose:

```bash
python scripts/queue_position_walkthrough.py       # queue position, event by event
python scripts/queue_turnover_effect.py 20000      # the same tape, with and without turnover
```

### Layout

```
src/exchange_simulator/
├── market_data_replay/   feed: gzip/CSV rows -> snapshots and reconstructed trades
├── matching_engine/      order book, price-time priority, queue turnover, impact
├── trading_platform/     trusted gateway: intents -> orders, portfolios, P&L
├── strategies/           four demonstration strategies, one process each
├── messaging/            typed topic bus over multiprocessing queues
├── recording/            CSV recorder process
├── system_controller/    lifecycle, supervision, dashboard
└── schemas/              shared message contracts
```

Architecture, message contracts, and the accepted decision records live in
[`docs/`](docs/README.md). Start with [`docs/architecture.md`](docs/architecture.md).

---

## Troubleshooting

| Symptom | Cause and fix |
|---|---|
| `ModuleNotFoundError: exchange_simulator` in child processes | The package is not installed. Run `pip install -e .`. |
| `No market-data file found under var/` | Put a `.csv` or `.csv.gz` file in `var/`. |
| Session ends immediately, few rows replayed | The `date` is not in the file. Pick the file again to refill the date, or clear it to replay everything. |
| `409 Conflict` on start | A session is already running. Stop it first — one session at a time. |
| `Address already in use` | Another instance holds the port. Set `EXCHANGE_SIMULATOR_PORT`. |
| Dashboard reachable but empty | Nothing has been started yet; press **Start**. |
| Orders rejected for tick or lot size | The instrument does not match the data file. Both come from the file's name, so re-pick the file. |
