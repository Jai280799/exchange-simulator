# ADR 0002: Use a no-impact two-book MVP

Status: **Accepted**
Date: **2026-07-21**

## Decision

Use a two-book, no-impact model for the MVP:

- historical five-level snapshots remain fixed ground truth;
- strategy orders are maintained separately by the matching engine;
- simulated strategy trades do not modify future historical snapshots.

## Context

Historical snapshots were produced by real orders and trades that occurred
without the simulated strategy. Once a simulated order is added, there is no
reliable way to predict how real participants would have changed their later
behavior.

Reconstructing a single historical order book from five-level snapshots is
heuristic and materially increases delivery risk before the demo.

## Consequences

- Replay remains deterministic and faithful to the supplied dataset.
- The same displayed historical liquidity may reappear on a later snapshot even
  after simulated consumption.
- Market impact is intentionally omitted from the baseline.
- Historical and simulated trades must preserve separate provenance.
- Passive fills require an explicit approximation. This follow-up was resolved
  by [ADR 0006](0006-trade-driven-passive-queue-fills.md).

## Alternatives rejected

- Mutating later historical snapshots after simulated trades: produces an
  internally invented trajectory without enough source data.
- Reconstructed single book for the MVP: potentially higher realism, but relies
  on inferred add/cancel/trade events and uncertain queue position.

## Follow-up work

- Document the chosen cross-book price-priority rule.
- Apply the passive-fill and queue policy accepted in
  [ADR 0006](0006-trade-driven-passive-queue-fills.md).
- Revisit single-book reconstruction only as a post-MVP experiment.
