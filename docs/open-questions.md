# Open architecture questions

Status: **Open**
Last updated: **2026-08-07**

These questions are intentionally unresolved. Temporary behavior in a pull
request does not settle them.

## Decision queue

| Priority | Question | Why it matters | Suggested owner | Needed before |
|---|---|---|---|---|
| ~~1~~ | ~~How is the best executable price selected across strategy and historical liquidity?~~ | **Resolved**: global best price, with internal liquidity preferred on a tie. | Jai + team | — |
| ~~2~~ | ~~Where are cancellation ownership and execution-report routing enforced?~~ | **Resolved** by [ADR 0006](decisions/0006-strategy-processes-and-intent-channel.md): enforced in the trading platform. | Alex + Jai | — |
| ~~3~~ | ~~What price fills a resting strategy order when a later snapshot touches/crosses it?~~ | **Resolved**: at the resting order's own price, gated by queue position ([ADR 0008](decisions/0008-execution-realism-defaults.md)). | Jai + team | — |
| ~~4~~ | ~~How is end-of-stream and shutdown coordinated?~~ | **Resolved** by [ADR 0007](decisions/0007-session-lifecycle-and-web-control.md): feed process exit is end of stream; drain on quiet counters. | Integration owner | — |
| ~~5~~ | ~~What replay pace and dataset should the demo use?~~ | **Resolved**: chosen per session in the dashboard; 500 rows per second is the readable default. | Hyungmin + team | — |
| 6 | How are multiple instruments scheduled? | Determines whether feeds run independently or merge onto one event timeline. | Hyungmin | Multi-instrument milestone |
| 7 | Is a reconstructed single-book/market-impact model in scope? | Higher realism, but substantial heuristic complexity and demo risk. | Team/professor | Post-MVP planning |

## Q1: liquidity-source priority — RESOLVED

**Resolution:** global best price. Each iteration compares the best internal
price with the best historical price and takes whichever is better for the
incoming order, preferring internal liquidity when the two are equal, so our own
resting orders are never skipped in favour of identically priced history.

Example:

- strategy ask: 105
- historical best ask: 100
- incoming buy limit: 110

Options:

1. **Global best price:** execute against 100 before 105. This follows best-price
   priority across both sources.
2. **Participant first:** execute against the strategy ask before historical
   liquidity. This is simpler and matches the merged matching-engine flow, but
   can give a worse execution despite better displayed liquidity.

Recommended next step: decide the policy and add a two-source example as an
acceptance test. Do not hide the decision inside method call order.

## Q2: trusted gateway and private routing — RESOLVED

Settled by [ADR 0006](decisions/0006-strategy-processes-and-intent-channel.md).
The proposed simple model below was adopted as written, with one addition:
strategies run as separate processes and reach the platform over
`RequestTopic.STRATEGY_INTENT` rather than calling it directly.

Proposed simple model:

- only the trading platform may publish create/cancel requests;
- the platform validates that a strategy owns an order before cancellation;
- the matching engine may cancel by globally unique `order_id`;
- execution reports return to the platform;
- the platform maps `order_id` to the owning strategy.

If strategies can publish directly, requests and reports need explicit recipient
identity and enforcement in the matching layer.

Recommended next step: Alex and Jai confirm the simple model and document the
platform's order-to-strategy mapping.

## Q3: resting-order fill price — RESOLVED

**Resolution:** option 1, at the resting order's own price — a limit order fills
at the price it posted, so no phantom price improvement appears. Option 3's
concern is addressed separately by queue turnover, which requires historical
prints to consume the volume ahead of the order before it fills. See
[ADR 0008](decisions/0008-execution-realism-defaults.md).

Under the snapshot-touch approximation, a bid resting at 100 may be crossed by a
later historical ask of 99.

Options:

1. Fill at the resting order's price, 100.
2. Fill at the snapshot price, 99, granting price improvement.
3. Do not infer a fill from a snapshot alone; require a historical trade print.

The current two-book MVP can choose option 1 or 2. Option 3 belongs to a
trade-driven passive-fill model and requires additional queue assumptions.

## Q4: completion and shutdown coordination — RESOLVED

Settled by [ADR 0007](decisions/0007-session-lifecycle-and-web-control.md). The
feed process exiting is end of stream; the controller then waits for message
counters to stop moving before requesting shutdown. The recorder's interim
quiet-inbox rule described below is now the second half of that protocol rather
than a local workaround. The remaining gap is an explicit recorder completion
acknowledgement.

Clean shutdown is required by
[ADR 0005](decisions/0005-one-command-demo-runtime.md), but the historical feed
is finite while consumers wait on queues. Define:

- the component that detects replay completion;
- whether completion is a bus message, sentinel, or controller event;
- how all consumers drain pending messages;
- how processes acknowledge shutdown;
- timeout and failure behavior;
- when artifact writers flush and close.

The run recorder uses an interim local rule: after shutdown is requested,
it consumes queued messages until its inbox is quiet for one receive timeout and
then closes its sinks. This does not resolve system-wide completion. The
controller must still define when producers are finished, whether a quiet inbox
is sufficient or an explicit sentinel is required, and how recorder completion
is acknowledged.

## Q5: replay clock

Options:

- full-speed deterministic replay;
- fixed-interval replay;
- wall-clock pacing using historical time deltas;
- configurable speed multiplier;
- controller-owned simulated clock.

Full-speed replay is on `master`, and configurable fixed-interval replay is
implemented in this change. The interval changes wall-clock publication timing
without changing source timestamps or historical ordering.

Fixed-interval replay is now the demo mechanism, chosen per session in the
dashboard rather than fixed in code; 500 source rows per second is readable while
presenting, and the feed can be paused between rows without ending the session.

Two clock points are settled. Every timestamp in the order path comes from the
replay clock: the engine stamps responses with the latest snapshot timestamp,
never earlier than the request being answered, so operator wall-clock time cannot
leak into `orders.csv`. What remains open is byte-reproducible replay — trade
identifiers are random UUIDs, so two runs over the same input are equivalent but
not identical. A historical-delta or speed-multiplier mode is still unbuilt and
is not needed by any current claim.

The operational acceptance criteria and rehearsal steps are in the
[demo runbook](demo-runbook.md).

## Decision template

When resolving a question, create a decision record containing:

```text
Status:
Decision:
Context:
Consequences:
Alternatives rejected:
Follow-up work:
```

Then update `architecture.md`, `message-contracts.md`, and the relevant issue.
