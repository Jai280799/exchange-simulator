# ADR 0005: One-command observable demo runtime

- Status: **Accepted**
- Date: **2026-07-23**

## Context

The instructor requires the team to launch the complete system at the beginning
of the presentation, leave it running while the slides are presented, and return
to it afterward to show the results.

The current application entry point does not yet provide this workflow. A
controller that only starts an idle component, waits for a fixed interval, or
requires the team to launch modules manually would not demonstrate an integrated
system.

## Decision

The project will provide one application command that:

1. validates the demo configuration and input data;
2. starts the messaging layer and all required application components;
3. waits at a readiness barrier before publishing replay data;
4. runs the replay, strategy, trading platform, and matching engine autonomously
   at a configurable pace;
5. displays periodic progress and component health;
6. writes durable run artifacts throughout the demo;
7. drains in-flight work, flushes outputs, and terminates child processes
   cleanly;
8. exits non-zero if a required component fails.

The end-to-end smoke test and presentation demo will use the same entry point
and topology. They may use different configurations and datasets.

The detailed operational contract is maintained in the
[demo runbook](../demo-runbook.md).

## Consequences

- The system controller is project code, not presentation-only glue.
- Component readiness and failures need explicit signals or another reliable
  coordination mechanism.
- A fixed-duration sleep is not an adequate application lifecycle.
- Replay pace, input paths, completion policy, and output paths must be
  configuration rather than hard-coded values.
- Results must remain available after the process exits.
- The team needs a short automated end-to-end fixture and a full-duration
  rehearsal.

## Alternatives rejected

### Launch every component manually

This makes startup order and operator timing part of correctness, increases
presentation risk, and does not prove that the repository has a coherent
application entry point.

### Start an idle system for a fixed time

This may show that processes remain alive, but it does not demonstrate expected
exchange behavior or produce results that can be inspected.

### Demonstrate each module independently

Module-level demonstrations remain useful during development, but they do not
satisfy the requirement to run the complete system.
