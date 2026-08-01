# Message contracts

Status: **Baseline contract; integration remains incomplete**
Last updated: **2026-08-01**

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
| `StateTopic.TRADES` | Matching engine | Platform, run recorder, and public simulated-trade consumers | `Trade` | Public simulated event | On `master`; recorder subscription in PR #22 |
| `RequestTopic.CREATE_ORDER` | Trading platform | Matching engine | `CreateOrderRequest` | Trusted request | On `master` |
| `ResponseTopic.CREATE_ORDER` | Matching engine | Trading platform | `OrderResponse` | Correlated response | On `master` |
| `RequestTopic.CANCEL_ORDER` | Trading platform | Matching engine | `CancelOrderRequest` | Trusted request | On `master`; ownership fields under review |
| `ResponseTopic.CANCEL_ORDER` | Matching engine | Trading platform | `OrderResponse` | Correlated response | On `master` |
| `StateTopic.EXECUTION_REPORT` | Matching engine | Trading platform, which routes to the owner; trusted run recorder | `ExecutionReport` | Trusted internal/private | On `master`; recorder subscription in PR #22; routing decision open |
| `StateTopic.ORDERS` | Not yet assigned | Platform/order-state consumers and run recorder | `Order` | Internal state | Reserved on `master`; recorder subscription in PR #22; producer ownership open |

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

### `CancelOrderRequest`

`master` uses only globally unique `order_id` plus `timestamp`.

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

## Recording contract

PR #22 introduces a trusted internal run recorder with these CSV mappings:

- `ORDERS` -> `orders.csv`;
- `TRADES` -> `simulated-trades.csv`;
- `EXECUTION_REPORT` -> `executions.csv`.

The recorder flushes after each row and drains messages already in its inbox
after shutdown is requested. The controller still owns producer shutdown order,
run completion, and the run-specific output directory. `orders.csv` remains
unavailable until the open `ORDERS` producer decision is resolved.

### `ExecutionReport`

The implemented contract represents a fill for one order and contains:

- `trade_id`;
- `order_id`;
- `instrument_id`;
- `side`;
- `price`;
- `quantity`;
- `timestamp`.

The platform must be able to route it to exactly the owning strategy, either
through a future explicit recipient field or a platform-owned order-to-strategy
mapping.

## Provenance and ordering

- Historical `sequence` orders messages emitted by the historical feed.
- Simulated engine events require their own deterministic ordering policy; they
  must not reuse historical sequence numbers as if both streams shared one global
  clock.
- Consumers subscribing to both trade topics must preserve the source topic when
  storing or displaying events.
- Wall-clock generation time and historical event time are different concepts and
  should be named or documented accordingly.
