# ADR 0008: Execution realism defaults — queue turnover on, impact penalty off

Status: **Accepted**
Date: **2026-08-06**

Relates to [ADR 0002](0002-no-impact-two-book-mvp.md), which established the
two-book MVP with no impact model. This record settles what the two realism
extensions do by default now that both are implemented.

## Decision

- `queue_turnover` defaults to **on**. A resting order records the external
  volume displayed at its price and fills only after historical trade prints have
  consumed that volume.
- `market_impact_ticks_per_level` defaults to **0**, so no synthetic slippage
  penalty is applied. `MarketDepthImpactModel` remains available per session.

Both are `SessionConfig` fields, reachable from the dashboard and the start
endpoint, and recorded in each run's `run-config.json`.

## Context

Both features were described as available before they were reachable. Queue
turnover was never merged, and the matching engine received a literal `None` for
its impact model, so `MarketDepthImpactModel` could not run outside tests.

While wiring them up, a double count surfaced. An aggressive order already walks
the book level by level and pays each level's own price, so the achieved average
is the exact depth-weighted price of the visible book. The tick penalty is zero
at the touch and grows with depth — precisely where the walk is already charging
more. Enabling both would charge twice for one effect.

Queue turnover has no such overlap. It constrains the passive side, which the
snapshot-touch model treated optimistically: standing at a price was previously
enough to trade at it.

## Consequences

- Passive fills depend on queue position. Measured on an identical 20,000-snapshot
  slice, turnover suppressed 30% of the snapshot-touch quantity (53,090 lots down
  to 37,010) and re-added 18,455 lots through the tape, for a small net increase
  and roughly three times as many, much smaller, partial fills. It changes *which*
  fills happen; it is not a blanket haircut.
- Depth consumption stays exactly priced, with no calibrated parameter to defend.
- The penalty keeps one honest use: pricing liquidity beyond the five visible
  levels, which the book walk cannot observe.
- The aggressor side of a print is inferred from the prevailing touch rather than
  carried on `MarketTradePrint`, so the message contract is unchanged. Prints
  strictly inside the spread are unclassifiable and are ignored.

## Alternatives rejected

- **Both on.** Double counts mechanical slippage, and the penalty is not
  calibrated, so it would degrade fidelity while appearing to add realism.
- **Delete `MarketDepthImpactModel`.** It is implemented and tested, and it
  remains the natural home for beyond-the-book slippage.
- **Turnover off by default.** It would leave the advanced requirement present but
  inert, which is the situation this record exists to end.

## Limitations

- Queue position is approximated from displayed volume; the external queue is not
  reconstructed.
- External cancels ahead of us are invisible in five-level aggregate data. A level
  shrinking without a print is treated as unchanged, which stays conservative.
- The penalty, when enabled, is linear in depth and ignores participation rate.
  It is a configurable slippage model, not an empirically calibrated one.

## Follow-up work

- Permanent impact — shifting subsequent snapshot prices by a decaying offset — is
  the model that would make trading affect the future price path. It is not
  implemented, and no current claim depends on it.
