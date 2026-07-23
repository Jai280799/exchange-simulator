# Message contracts

Status: **Baseline contract; some entries are in flight**
Last updated: **2026-07-23**

## Rules

- Every topic has one expected schema registered in `MESSAGE_TYPES`.
- A publisher must declare the topic in its central `ComponentSpec`.
- A consumer must declare its subscription before topology finalization.
- Request and response topics are directional and must not be interchanged.
- Historical market events and simulated exchange events retain distinct
  provenance.

## Topic matrix

| Topic | Producer | Intended consumer | Schema | Visibility | Status |
|---|---|---|---|---|---|
| `StateTopic.MARKET_DATA` | Historical feed | Matching engine, platform, market-data consumers | `MarketDataSnapshot` | Public market observation | On `master`; extended by PR #15 |
| `StateTopic.MARKET_TRADES` | Historical feed | Platform, strategies, future passive-fill/queue model | `MarketTradePrint` | Public historical observation | In flight in PR #15 |
| `StateTopic.TRADES` | Matching engine | Platform and public simulated-trade consumers | `Trade` or an explicitly renamed simulated-trade schema | Public simulated event | Topic exists on `master`; PR #14 must preserve it |
| `RequestTopic.CREATE_ORDER` | Trading platform | Matching engine | `CreateOrderRequest` | Trusted request | On `master` |
| `ResponseTopic.CREATE_ORDER` | Matching engine | Trading platform | `OrderResponse` | Correlated response | On `master` |
| `RequestTopic.CANCEL_ORDER` | Trading platform | Matching engine | `CancelOrderRequest` | Trusted request | On `master`; ownership fields under review |
| `ResponseTopic.CANCEL_ORDER` | Matching engine | Trading platform | `OrderResponse` | Correlated response | On `master` |
| `StateTopic.EXECUTION_REPORT` | Matching engine | Trading platform, which routes to the owner | `ExecutionReport` | Private after routing | Proposed in PR #14; routing decision open |
| `StateTopic.ORDERS` | Not yet assigned | Platform/order-state consumers | `Order` | Internal state | Reserved on `master`; ownership open |

## Schema expectations

### `MarketDataSnapshot`

In-flight PR #15 contract:

- `instrument_id`
- `sequence`
- `timestamp`
- `bids`: best-first tuple of price/quantity levels
- `asks`: best-first tuple of price/quantity levels

The historical feed owns `sequence`. It is monotonic for that feed/instrument and
orders snapshots relative to historical trade prints.

### `MarketTradePrint`

In-flight PR #15 contract:

- `instrument_id`
- `sequence`
- `timestamp`
- `price`
- `quantity`
- `cumulative_volume`

This is a historical observation reconstructed from the source data. It is not a
strategy execution and must not be published on `TRADES`.

### Simulated `Trade`

The `master` schema currently contains:

- `trade_id`
- `instrument_id`
- `buy_order_id`
- `sell_order_id`
- `price`
- `quantity`
- `timestamp`

PR #14 proposes a different shape and name. The final schema may change, but the
event must remain a simulated matching-engine output on `TRADES`. A rename must
make provenance clearer, not merge it with `MarketTradePrint`.

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

### `CancelOrderRequest`

`master` includes `order_id`, `strategy_id`, `instrument_id`, and `timestamp`.
PR #14 proposes using only globally unique `order_id` plus `timestamp`.

The simplified form is acceptable if the trading platform is the sole trusted
publisher and validates strategy ownership before forwarding. This trust boundary
is still **Open** and is tracked in `open-questions.md`.

### `OrderResponse`

- `order_id`
- accepted or rejected status
- `timestamp`
- optional human-readable message

Responses must be published on `ResponseTopic`, never the corresponding
`RequestTopic`.

### `ExecutionReport`

Proposed PR #14 contract represents a fill for one order. The platform must be
able to route it to exactly the owning strategy, either through `strategy_id` in
the message or a platform-owned order-to-strategy mapping.

## Provenance and ordering

- Historical `sequence` orders messages emitted by the historical feed.
- Simulated engine events require their own deterministic ordering policy; they
  must not reuse historical sequence numbers as if both streams shared one global
  clock.
- Consumers subscribing to both trade topics must preserve the source topic when
  storing or displaying events.
- Wall-clock generation time and historical event time are different concepts and
  should be named or documented accordingly.
