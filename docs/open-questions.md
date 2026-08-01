# Open architecture questions

Status: **Open**
Last updated: **2026-08-01**

These questions are intentionally unresolved. Temporary behavior in a pull
request does not settle them.

## Decision queue

| Priority | Question | Why it matters | Suggested owner | Needed before |
|---|---|---|---|---|
| 1 | How is the best executable price selected across strategy and historical liquidity? | Determines the matching abstraction and whether participant-first execution may give a worse price. | Jai + team | Final matching behavior |
| 2 | Where are cancellation ownership and execution-report routing enforced? | Defines the platform/engine trust boundary and public schemas Alex builds against. | Alex + Jai | Platform integration |
| 3 | What price fills a resting strategy order when a later snapshot touches/crosses it? | Changes P&L and passive-fill realism. | Jai + team | Passive-fill tests |
| 4 | How is end-of-stream and shutdown coordinated? | Clean shutdown is required, but the mechanism remains open. | Integration owner | Demo entry point |
| 5 | What replay pace and dataset should the demo use? | The system must stay observable throughout the presentation without overwhelming consumers. | Hyungmin + team | Full demo rehearsal |
| 6 | How are multiple instruments scheduled? | Determines whether feeds run independently or merge onto one event timeline. | Hyungmin | Multi-instrument milestone |
| 7 | Is a reconstructed single-book/market-impact model in scope? | Higher realism, but substantial heuristic complexity and demo risk. | Team/professor | Post-MVP planning |

## Q1: liquidity-source priority

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

## Q2: trusted gateway and private routing

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

## Q3: resting-order fill price

Under the snapshot-touch approximation, a bid resting at 100 may be crossed by a
later historical ask of 99.

Options:

1. Fill at the resting order's price, 100.
2. Fill at the snapshot price, 99, granting price improvement.
3. Do not infer a fill from a snapshot alone; require a historical trade print.

The current two-book MVP can choose option 1 or 2. Option 3 belongs to a
trade-driven passive-fill model and requires additional queue assumptions.

## Q4: completion and shutdown coordination

Clean shutdown is required by
[ADR 0005](decisions/0005-one-command-demo-runtime.md), but the historical feed
is finite while consumers wait on queues. Define:

- the component that detects replay completion;
- whether completion is a bus message, sentinel, or controller event;
- how all consumers drain pending messages;
- how processes acknowledge shutdown;
- timeout and failure behavior;
- when artifact writers flush and close.

PR #22 gives the run recorder an interim local rule: after shutdown is requested,
it consumes queued messages until its inbox is quiet for one receive timeout and
then closes its sinks. This does not resolve system-wide completion. The
controller must still define when producers are finished, whether a quiet inbox
is sufficient or an explicit sentinel is required, and how recorder completion
is acknowledged.

## Q5: replay clock

Options:

- full-speed deterministic replay;
- wall-clock pacing using historical time deltas;
- configurable speed multiplier;
- controller-owned simulated clock.

Configurable pacing is required by
[ADR 0005](decisions/0005-one-command-demo-runtime.md). The remaining decision is
which mode, multiplier, and dataset should be the presentation default. It
should produce useful activity for the expected presentation duration without
changing the ordering promised by the replay.

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
