# ADR 0007: Session lifecycle and web-driven demo control

Status: **Accepted**
Date: **2026-08-03**

## Decision

`SessionController` owns a single lifecycle:

```text
IDLE -> STARTING -> READY -> RUNNING -> DRAINING -> COMPLETED
                                              \--> FAILED
```

- **STARTING** validates configuration and the data file, allocates
  `runs/<run-id>/`, registers every component spec, finalises the topology, and
  spawns processes.
- **READY** waits on a per-component `ready_event` that each runner sets after
  construction succeeds. Replay does not begin until all are set.
- **RUNNING** sets the shared `start_event`.
- **DRAINING** begins when the feed process exits. That is end of stream. The
  controller then waits until message counters stop moving before setting
  `shutdown_event`, so consumers finish what is already queued.
- **COMPLETED / FAILED** joins children, writes `summary.json`, and reports any
  component whose exit code is non-zero.

The runtime is `python -m exchange_simulator`, which serves a FastAPI dashboard.
A session is started and stopped from that page.

This resolves [Q4](../open-questions.md).

## Context

ADR 0005 requires one command, a readiness barrier, visible progress, durable
artifacts, clean shutdown, and detectable failure. The previous controller
started two components and slept for sixty seconds.

Q4 asked who detects completion. The feed is the only finite producer, so its
process exit is the natural signal and needs no new message or sentinel.

## Consequences

- Three existing runners gained an optional `ready_event` parameter. The change
  is additive and backwards compatible.
- Components are spawned, not forked: the controller creates children from a
  process already running an asyncio server and a thread pool, where forking
  risks inheriting held locks.
- The topology object must outlive process start. A spawned child opens a
  queue's semaphore lazily, so dropping the topology first unlinks it and the
  child dies with `FileNotFoundError`.
- The dashboard is a registered bus component like any other, so it observes the
  system through the declared topology rather than a side channel.
- All processes append to one `system.log` via an environment variable. Records
  can in principle interleave.

## Alternatives rejected

- **End-of-stream sentinel message.** More explicit, but needs a new topic and a
  schema, and every consumer would have to handle it.
- **Fixed drain timeout.** Simpler, but either truncates a busy queue or wastes
  presentation time.

## Follow-up work

- Acknowledge recorder completion explicitly rather than inferring it from quiet
  counters.
- Per-process log files if interleaving becomes a problem.
