---
name: exchange-architecture-guard
description: Answer questions and check exchange-simulator work against both the documented architecture and the exact code implementation. Use when explaining or changing payload formats, transport protocols, schemas, topics, ComponentSpec topology, entry points, lifecycle, historical replay, matching, the trading platform, strategy integration, tests, or any cross-component behavior; also use when checking whether documentation and code have drifted.
---

# Exchange Architecture Guard

Keep intended contracts, implemented behavior, and review claims aligned. Never
let temporary code silently become architecture, and never describe a documented
target as already implemented.

## Load the contract

From the repository root, read:

1. `docs/README.md`
2. `docs/architecture.md`
3. `docs/message-contracts.md`
4. `docs/open-questions.md`

Read the task-specific document when relevant:

- market-data payload or transport: `docs/market-data-interface.md`;
- application entry point or presentation runtime: `docs/demo-runbook.md`.

Then read only the relevant decision records in `docs/decisions/`. Do not copy
their contents into the skill.

If these files are absent, report that the architecture pack is unavailable and
infer only what can be proven from code and current task context.

## Verify the implementation

Documentation defines intended contracts and records their status. Code and tests
show what the selected commit actually implements. Neither may silently stand in
for the other.

1. Resolve the exact branch or commit being discussed.
2. Locate the concrete schemas, topic registry, message-type registry, component
   specs, producers, consumers, controller wiring, and tests relevant to the
   question.
3. Compare their names, fields, types, routing, ordering, and lifecycle behavior
   with the documents.
4. Classify each material claim as:
   - **Implemented and documented**
   - **Accepted but not implemented**
   - **Implemented but undocumented**
   - **Open**
   - **Contradictory drift**

For a question such as “What payload do we use?”, answer from the exact
implemented dataclass and bus behavior, then add any documented conventions or
open lifecycle limitations. Do not answer from an example alone.

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

Also identify the tests and documents that assert the contract:

```text
producer -> topic -> schema -> consumer -> tests -> docs
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

Never resolve an open design question merely by preserving whichever behavior
was implemented first. Never label a documented target as current behavior
without finding its implementation.

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

When an authorized implementation changes a cross-component contract, update
code, tests, and documents in the same change:

1. Update `docs/architecture.md`.
2. Update `docs/message-contracts.md`.
3. Update the task-specific interface or runbook.
4. Resolve the corresponding item in `docs/open-questions.md`.
5. Add or supersede an ADR when an accepted decision changes.
6. Add a contract or integration test that exercises the documented behavior.

When documentation describes future work, mark it **Proposed**, **Required
target**, or **Not implemented**. Do not phrase it as an existing capability.

When reviewing, treat a public-contract code change without matching
documentation and tests as drift. Treat documentation that no longer matches the
selected code as drift even if the prose still sounds architecturally sensible.

Do not rewrite an accepted ADR as if the earlier decision never existed.

## Report

Summarize:

- exact branch or commit checked;
- decisions applied;
- open questions encountered;
- producer/topic/schema/consumer impacts;
- implementation, test, and documentation agreement or drift;
- documentation or tests changed or still required; and
- assumptions that remain temporary.
