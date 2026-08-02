# ADR 0006: One process per strategy behind an intent channel

Status: **Accepted**
Date: **2026-08-03**

## Decision

Each strategy runs in its own process. Strategies never publish create or cancel
requests. They publish `RequestTopic.STRATEGY_INTENT`, and the trading platform
translates an accepted intent into `RequestTopic.CREATE_ORDER` or
`RequestTopic.CANCEL_ORDER`.

The platform returns `StateTopic.STRATEGY_UPDATE`, carrying the recipient's
`strategy_id`, position, average cost, realized and unrealized PnL, live orders,
and the triggering response or execution.

This resolves [Q2](../open-questions.md) in favour of the trusted-gateway model
that question proposed.

## Context

The matching engine trusts whatever arrives on the request topics. If strategies
published there directly, ownership enforcement would have to move into the
matching layer, and every strategy would need to be trusted.

Separate strategy processes match the component diagram and let a slow strategy
block only itself. But the bus had no strategy-to-platform channel, so one had to
be added.

## Consequences

- The platform is the only component that may publish order requests, and it
  validates that a strategy owns an order before forwarding a cancellation.
- The platform owns the `order_id -> strategy_id` mapping and all portfolio
  accounting, so the recorder and dashboard see one authoritative PnL.
- The platform becomes the `StateTopic.ORDERS` producer, which makes
  `orders.csv` writable for the first time.
- `STRATEGY_UPDATE` is a broadcast topic. Every strategy process receives every
  update and must discard those addressed elsewhere. Strategy state is therefore
  private by convention, not by transport. The boundary that is enforced is the
  one that matters: a strategy cannot reach the matching engine.
- Each strategy process receives its own copy of every market-data message.

## Alternatives rejected

- **Strategies hosted inside the platform process.** Needs no new topics and no
  broadcast, but abandons process isolation and diverges from the architecture
  diagram.
- **Per-strategy topics.** Would give true private routing, but `StateTopic` is a
  fixed `StrEnum`; parameterised topics are a larger change to the messaging
  layer than this milestone justifies.

## Follow-up work

- Revisit private routing if untrusted strategies are ever introduced.
- Consider a platform-owned market-data projection so strategies stop each
  paying for a full snapshot fan-out.
