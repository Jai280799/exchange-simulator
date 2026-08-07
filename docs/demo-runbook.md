# Demo runbook

Status: **Implemented**
Last updated: **2026-08-07**

## Objective

The presentation must begin by launching the complete exchange simulator. It
must continue running while the team presents the slides, then provide visible
results that the team can explain at the end.

The demo should use the same application entry point and component wiring as
normal end-to-end testing. It must not depend on manually starting individual
modules in the correct order.

## Launch command

```bash
python -m exchange_simulator
```

This starts the control plane and dashboard on <http://127.0.0.1:8000>. The
session itself — dataset, instrument, date, replay pace, strategies, and the
realism settings — is chosen in the browser and posted to
`/api/session/start`, so no configuration file is needed and the launch stays a
single command. `--host` and `--port`, or the matching environment variables,
move the listener.

Run artifacts are written to `runs/<run-id>/`, one directory per session.

## Required lifecycle

1. `STARTING`: load and validate the configuration and input data.
2. `READY`: start the message bus and every required component, then wait until
   each component reports readiness.
3. `RUNNING`: replay historical data at the configured pace, run the strategy
   and trading platform, process orders through the matching engine, and write
   observable progress and results.
4. `DRAINING`: stop accepting new work, drain messages already in flight, and
   flush output files.
5. `COMPLETED`: print a summary and exit successfully. Any unrecoverable
   component failure must instead produce `FAILED` and a non-zero exit status.

The controller must not start replay until all consumers are ready. It must also
detect if a required child process exits unexpectedly.

## What should be visible

At launch, the console should show:

- the run identifier, configuration, input dataset, replay pace, and output
  directory;
- one readiness line for each required component;
- an unambiguous message when the complete system enters `RUNNING`.

During the presentation, a periodic heartbeat should show enough activity to
prove that the system is still progressing, such as:

- simulation timestamp;
- market-data rows or messages published;
- orders submitted and executions produced;
- current position or P&L, when available;
- component health or queue pressure.

At the end, the team should show the final summary and a small number of durable
artifacts rather than relying only on scrolling terminal output.

## Output contract

Each run should write to its own directory:

```text
runs/<run-id>/
├── run-config.json
├── system.log
├── orders.csv
├── executions.csv
├── simulated-trades.csv
├── positions.csv
└── summary.json
```

Files that are not yet supported may be introduced incrementally. At minimum,
the presentation build needs:

- the effective run configuration;
- a complete system log;
- submitted orders;
- execution reports;
- a machine-readable final summary.

`summary.json` should include the run status, start and end simulation times,
message and order counts, execution count, final positions, and any component
errors. Outputs should be flushed periodically so that a long-running
presentation demo still leaves useful evidence if it is interrupted.

Historical `MARKET_TRADES` and strategy-generated `TRADES` must remain separate
as specified in [ADR 0003](decisions/0003-separate-trade-streams.md).

### Current recording implementation

The current implementation provides CSV sinks for `ORDERS`, simulated `TRADES`,
and `EXECUTION_REPORT`, and the controller allocates a new `runs/<run-id>/`
directory for each launch. CSV rows are flushed immediately, and the recorder
consumes messages already queued when shutdown is requested until its inbox is
quiet for one receive timeout.

In flight in PR #28: the trading platform is now the `ORDERS` producer, so
`orders.csv` is written; the controller writes `run-config.json`, `system.log`
and `summary.json`; and completion ordering is defined by
[ADR 0007](decisions/0007-session-lifecycle-and-web-control.md) — the feed
process exiting is end of stream, after which consumers drain until their
message counts stop moving.

`positions.csv` is the one artifact still unimplemented; per-strategy inventory
and PnL are live on the dashboard and in `summary.json` but are not written as a
separate file. An explicit recorder completion acknowledgement also remains
open — a quiet inbox is inferred, not confirmed.

## Pre-presentation checklist

- Use the same computer, Python environment, dataset, and configuration planned
  for the presentation.
- Confirm the demo does not require network access after dependencies and data
  are installed.
- Confirm that the input data covers the instruments used by the strategy.
- Start with a new run directory so results cannot be confused with an earlier
  rehearsal.
- Run the complete demo for at least the expected presentation duration.
- Verify the final artifacts can be opened and explained quickly.
- Keep the last successful rehearsal artifacts as a diagnostic backup. They are
  not a substitute for launching the live system.

## Acceptance checks

| Requirement | Passing evidence |
|---|---|
| Single launch | One documented command starts the complete system. |
| Coordinated readiness | Replay begins only after all required components report ready. |
| Autonomous operation | No additional commands are needed while the slides are presented. |
| Visible progress | Heartbeats change throughout the run and identify unhealthy components. |
| Useful results | Orders, executions, logs, and a final summary are written to the run directory. |
| Repeatability | The same configuration and input produce explainable, deterministic behavior where promised. |
| Clean completion | Messages are drained, files are flushed, and child processes terminate. |
| Detectable failure | A component failure is reported and the application exits non-zero. |

## Test ladder

1. Unit-test parsing, strategy decisions, matching behavior, and artifact writers.
2. Test each producer-consumer message contract through the real messaging layer.
3. Run a short end-to-end smoke test with a small fixture through the same
   application entry point used for the demo.
4. Rehearse the complete presentation-duration run at the pace intended for the
   presentation, and confirm the dashboard stays readable throughout.

The short smoke test should be suitable for CI. The full-duration rehearsal may
remain a manual release check.

## Suggested ownership

- Historical market data owner: replay configuration, progress counters, and
  deterministic completion.
- Matching engine owner: order and execution correctness plus execution
  artifacts.
- Trading platform and strategy owner: order submission, positions, and
  presentation-level results.
- System controller owner: lifecycle, readiness, failure detection, shutdown,
  and the one-command interface.
- Whole team: complete rehearsals and agreement on which results will be shown.
