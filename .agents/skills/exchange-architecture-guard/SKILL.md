---
name: exchange-architecture-guard
description: Check exchange-simulator changes against accepted architecture decisions, message contracts, component ownership, and explicitly open questions. Use when planning, implementing, explaining, or reviewing changes to schemas, messaging topics, ComponentSpec topology, the system controller, historical replay, matching, the trading platform, strategy integration, lifecycle, or cross-component behavior.
---

# Exchange Architecture Guard

Use the repository's canonical documents to prevent temporary code or unstated
assumptions from silently becoming architecture.

## Load the source of truth

From the repository root, read:

1. `docs/README.md`
2. `docs/architecture.md`
3. `docs/message-contracts.md`
4. `docs/open-questions.md`

Then read only the decision records in `docs/decisions/` relevant to the change.
Do not copy their contents into the skill or assume current code supersedes them.

If these files are absent, report that the architecture pack is unavailable and
infer only what can be proven from code and current task context.

## Classify the change

Determine whether the task affects:

- one component's internal behavior;
- a message schema or topic;
- a producer/consumer relationship;
- topology, lifecycle, or process ownership;
- historical-versus-simulated provenance; or
- an item explicitly listed as open.

For cross-component changes, trace this chain before editing:

```text
producer -> topic -> schema -> consumer -> owner
```

List every affected component and contract.

## Apply decision status

- **Accepted:** implement consistently. If the requested change contradicts it,
  identify the conflict and the decision record before changing code.
- **Proposed:** treat it as guidance, not authority.
- **Open:** do not infer a permanent policy from temporary code. Present the
  decision and consequences, and obtain direction when it materially changes the
  result.
- **In flight:** distinguish intended contract from what is currently on
  `master`; check the relevant branch or PR when needed.

Never resolve an open design question merely by preserving whichever behavior was
implemented first.

## Enforce project invariants

Check that:

- historical snapshots and historical prints remain fixed ground truth;
- simulated trades do not enter the historical trade stream;
- one topic retains one validated message contract;
- request and response topics are not interchanged;
- the complete topology remains centrally auditable;
- component behavior does not absorb controller/platform responsibilities;
- historical time, simulated ordering, and wall-clock time are not conflated.

## Keep documentation synchronized

When an authorized implementation changes a cross-component contract:

1. Update `docs/architecture.md`.
2. Update `docs/message-contracts.md`.
3. Resolve the corresponding item in `docs/open-questions.md`.
4. Add or supersede an ADR when an accepted decision changes.

Do not rewrite an accepted ADR as if the earlier decision never existed.

## Report

Summarize:

- decisions applied;
- open questions encountered;
- producer/topic/schema/consumer impacts;
- documentation changed or still required; and
- assumptions that remain temporary.
