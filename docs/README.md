# Architecture documentation

This directory is the shared source of truth for the exchange simulator's
architecture and cross-component contracts. It describes the intended system,
including accepted decisions that may not yet be present on `master` while their
pull requests are in flight.

## Start here

1. [Architecture](architecture.md) — components, responsibilities, data flow,
   invariants, and integration sequence.
2. [Message contracts](message-contracts.md) — topics, producers, consumers,
   schemas, and routing assumptions.
3. [Market-data interface](market-data-interface.md) — exact snapshot and trade
   payloads, multiprocessing transport, and integration examples.
4. [Demo runbook](demo-runbook.md) — one-command presentation lifecycle,
   observable progress, outputs, and rehearsal checks.
5. [Open questions](open-questions.md) — decisions that are not settled and must
   not be inferred from temporary code.
6. [Decision records](decisions/) — accepted architecture decisions and their
   consequences.

## Document status vocabulary

- **Accepted** — the team has agreed to the decision. New code should follow it
  unless the decision record is explicitly superseded.
- **Proposed** — a preferred direction that still needs team confirmation.
- **Open** — no direction has been selected.
- **In flight** — accepted or proposed behavior is being implemented in an open
  pull request and may not exist on `master`.

## Maintenance rule

When a cross-component decision changes:

1. Add or supersede a decision record.
2. Update the message-contract table and architecture diagram.
3. Update the relevant GitHub issue or pull request.
4. Record implementation details in code only after the system-level contract is
   clear.
