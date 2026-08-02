# ADR 0003: Separate historical and simulated trade streams

Status: **Accepted**
Date: **2026-07-22**

## Decision

Publish historical and simulated trades on separate topics:

- `StateTopic.MARKET_TRADES` carries historical `MarketTradePrint` events from
  the replay feed.
- `StateTopic.TRADES` carries simulated trades produced by the matching engine.
- Private execution reports use a separate routing path.

## Context

Both events describe price and quantity, but they belong to different realities.
Historical prints are fixed observations from the source trading day. Simulated
trades are generated when strategy orders match inside the simulator.

Combining both schemas on one topic would require disabling type validation or
adding source discrimination to every consumer. It would also make the historical
tape appear to contain simulated events.

## Consequences

- Consumers can subscribe to one or both streams deliberately.
- Per-topic message-type validation remains enabled.
- Storage and analytics retain event provenance.
- The two streams do not share a global sequence without an explicit simulation
  clock.

## Alternatives rejected

- One topic carrying two message classes: weakens the bus contract and forces
  consumer-side type branching.
- One normalized public-trade schema for the MVP: possible later, but still
  requires provenance and creates unnecessary cross-component scope now.
- Dropping historical prints: removes information needed by future
  trade-driven/queue models and strategies.

## Follow-up work

- Keep the merged matching engine and recorder aligned on `TRADES` for simulated
  trades; do not record historical `MARKET_TRADES` as simulated output.
- Define execution-report routing separately from public trade publication.
