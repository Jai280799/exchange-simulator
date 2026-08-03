# Message contracts

Status: **Baseline contract; strategy channel in flight (PR #28)**
Last updated: **2026-08-03**

## Rules

- Every topic has one expected schema registered in `MESSAGE_TYPES`.
- A publisher must declare the topic in its central `ComponentSpec`.
- A consumer must declare its subscription before topology finalization.
- Request and response topics are directional and must not be interchanged.
- Historical market events and simulated exchange events retain distinct
  provenance.

For the exact market-data dataclasses, ordering guarantees, bus behavior,
consumer loop, and dummy-publisher example, see the
[market-data interface](market-data-interface.md).

## Topic matrix

| Topic | Producer | Intended consumer | Schema | Visibility | Status |
|---|---|---|---|---|---|
| `StateTopic.MARKET_DATA` | Historical feed | Matching engine, platform, market-data consumers | `MarketDataSnapshot` | Public market observation | On `master` |
| `StateTopic.MARKET_TRADES` | Historical feed | Platform, strategies, future passive-fill/queue model | `MarketTradePrint` | Public historical observation | On `master` |
| `StateTopic.TRADES` | Matching engine | Platform, run recorder, and public simulated-trade consumers | `Trade` | Public simulated event | On `master` |
| `RequestTopic.CREATE_ORDER` | Trading platform | Matching engine | `CreateOrderRequest` | Trusted request | On `master` |
| `ResponseTopic.CREATE_ORDER` | Matching engine | Trading platform | `OrderResponse` | Correlated response | On `master` |
| `RequestTopic.CANCEL_ORDER` | Trading platform | Matching engine | `CancelOrderRequest` | Trusted request | On `master`; ownership enforced by the platform per [ADR 0006](decisions/0006-strategy-processes-and-intent-channel.md) |
| `ResponseTopic.CANCEL_ORDER` | Matching engine | Trading platform | `OrderResponse` | Correlated response | On `master` |
| `StateTopic.EXECUTION_REPORT` | Matching engine | Trading platform, which routes to the owner; trusted run recorder; dashboard | `ExecutionReport` | Trusted internal/private | In flight (PR #28); routing resolved by [ADR 0006](decisions/0006-strategy-processes-and-intent-channel.md) |
| `StateTopic.ORDERS` | Trading platform | Run recorder, dashboard | `Order` | Internal state | In flight (PR #28); producer assigned by [ADR 0006](decisions/0006-strategy-processes-and-intent-channel.md) |
| `RequestTopic.STRATEGY_INTENT` | Strategy processes | Trading platform | `StrategyIntent` | Untrusted request | In flight (PR #28), added by [ADR 0006](decisions/0006-strategy-processes-and-intent-channel.md) |
| `StateTopic.STRATEGY_UPDATE` | Trading platform | Strategy processes, dashboard | `StrategyUpdate` | Addressed broadcast | In flight (PR #28), added by [ADR 0006](decisions/0006-strategy-processes-and-intent-channel.md) |

## Schema expectations

### `MarketDataSnapshot`

Implemented contract:

- `instrument_id`
- `sequence`
- `timestamp`
- `bids`: best-first tuple of price/quantity levels
- `asks`: best-first tuple of price/quantity levels

The historical feed owns `sequence`. It is monotonic for that feed/instrument and
orders snapshots relative to historical trade prints.

### `MarketTradePrint`

Implemented contract:

- `instrument_id`
- `sequence`
- `timestamp`
- `price`
- `quantity`
- `cumulative_volume`

This is a historical observation reconstructed from the source data. It is not a
strategy execution and must not be published on `TRADES`.

### Simulated `Trade`

The `master` schema contains:

- `trade_id`
- `instrument_id`
- `side`
- `price`
- `quantity`
- `timestamp`

The event remains a simulated matching-engine output on `TRADES` and must not be
merged with `MarketTradePrint`.

### `CreateOrderRequest`

Current contract:

- `order_id`
- `strategy_id`
- `instrument_id`
- `side`
- `order_type`
- `quantity`
- optional `price`
- `timestamp`

Limit orders require a price and all quantities must be positive.

The MVP uses the source feedcodes `2603` and `2330` as canonical
`instrument_id` values across market-data messages, order requests, instrument
configuration, and matching-engine books. `config/instruments.yaml` supplies the
MIC, currency, tick size, and lot size for each ID. Request quantities must be a
multiple of the configured lot size, and any supplied price must be a multiple
of the configured tick size. For incoming aggressive orders, an optional impact
model may reject an otherwise visible market level when its adjusted execution
price would violate the order's limit; the default MVP runtime remains
no-impact. Snapshot-triggered passive fills continue to use the resting order's
price while that separate policy remains open.

### `CancelOrderRequest`

`master` uses only globally unique `order_id` plus `timestamp`.

The simplified form holds because the trading platform is the sole trusted
publisher and validates strategy ownership before forwarding. That trust boundary
is settled by [ADR 0006](decisions/0006-strategy-processes-and-intent-channel.md).

### `OrderResponse`

- `order_id`
- accepted or rejected status
- `timestamp`
- optional human-readable message

Responses must be published on `ResponseTopic`, never the corresponding
`RequestTopic`.

## Recording contract

The trusted internal run recorder uses these CSV mappings:

- `ORDERS` -> `orders.csv`;
- `TRADES` -> `simulated-trades.csv`;
- `EXECUTION_REPORT` -> `executions.csv`.

The recorder flushes after each row and drains messages already in its inbox
after shutdown is requested. The controller owns producer shutdown order, run
completion, and the run-specific output directory; it stops the feed before
draining consumers, per
[ADR 0007](decisions/0007-session-lifecycle-and-web-control.md). All three files
are written now that the platform produces `ORDERS`.

### `ExecutionReport`

The implemented contract represents a fill for one order and contains:

- `trade_id`;
- `order_id`;
- `instrument_id`;
- `side`;
- `price`;
- `quantity`;
- `timestamp`.

The platform routes it to the owning strategy through its platform-owned
order-to-strategy mapping. No recipient field was added to this schema.

### `StrategyIntent`

Strategy processes publish intent; only the trading platform turns it into an
order request. Fields:

- `strategy_id`, `instrument_id`, `action` (`SUBMIT` or `CANCEL`), `timestamp`;
- for `SUBMIT`: `side`, `order_type`, `quantity`, optional `price`;
- for `CANCEL`: `order_id`.

The platform assigns the `order_id`, rounds the price to the instrument tick
(down for buys, up for sells), truncates the quantity to whole lots, and rejects
a cancellation of an order the strategy does not own.

### `StrategyUpdate`

The platform-owned view returned to exactly one strategy:

- `strategy_id` — **the recipient**, not the sender;
- `timestamp`, `position`, `avg_cost`, `realized_pnl`, `unrealized_pnl`;
- `live_orders`;
- optional `response` and `execution` that triggered the update.

The topic is a broadcast. Every strategy receives every update and must discard
those whose `strategy_id` is not its own. See
[ADR 0006](decisions/0006-strategy-processes-and-intent-channel.md).

## Provenance and ordering

- Historical `sequence` orders messages emitted by the historical feed.
- Simulated engine events require their own deterministic ordering policy; they
  must not reuse historical sequence numbers as if both streams shared one global
  clock.
- Consumers subscribing to both trade topics must preserve the source topic when
  storing or displaying events.
- Wall-clock generation time and historical event time are different concepts and
  should be named or documented accordingly.
