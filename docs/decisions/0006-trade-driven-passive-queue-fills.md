# ADR 0006: Use trade-driven passive queue fills

Status: **Accepted**
Date: **2026-07-31**

## Decision

Use historical trade prints to advance passive strategy orders at the same
price:

- a new resting strategy order joins behind the quantity displayed at its price
  in the latest historical snapshot;
- if the first snapshot arrives after an order, that snapshot seeds the order's
  external queue position;
- a historical print consumes external queue ahead before filling strategy
  orders FIFO at that exact price;
- sell-aggressor prints turn over resting bids and buy-aggressor prints turn over
  resting asks;
- a print with unknown aggressor side does not change strategy queue position;
- same-row trade prints are processed before the row's post-event snapshot;
- a snapshot that strictly crosses a resting order may still fill it under the
  existing two-book approximation, but an equal-price snapshot alone does not
  bypass external queue ahead.

## Context

Five-level snapshots do not expose individual external orders, cancellations,
or true queue position. Filling every strategy order as soon as a later snapshot
touches its price is optimistic. The historical feed can reconstruct trade
quantity from cumulative volume and conservatively infer aggressor side from the
previous book, falling back to the current row when necessary.

This policy improves passive-fill behavior without reconstructing or mutating a
single historical order book. Historical snapshots and prints remain fixed
ground truth, while simulated executions remain a separate output stream.

## Consequences

- Passive fills depend on inferred historical turnover and remain an
  approximation.
- Queue turnover is deliberately exact-price; a print does not infer consumption
  at unreported better prices.
- Unknown aggressor side produces no queue fill rather than a speculative one.
- The feed must emit a row's trade before its post-event snapshot and pacing must
  preserve the row as one adjacent event group.
- Simulated fills continue on `TRADES`; historical prints remain on
  `MARKET_TRADES`.

## Alternatives rejected

- Fill on every equal-price snapshot: too optimistic because displayed quantity
  may still be ahead of the strategy order.
- Reconstruct a complete order-by-order historical book: unsupported by the
  five-level source data and outside the MVP scope.
- Mutate future historical snapshots after simulated fills: invents a market
  trajectory not present in the source data.

## Follow-up work

- Keep feed row grouping and replay pacing compatible with trade-before-snapshot
  ordering.
- Revisit exact-price turnover and aggressor inference only with stronger source
  data or an explicitly versioned simulation model.
