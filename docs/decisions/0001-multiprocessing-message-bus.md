# ADR 0001: Use a multiprocessing message bus

Status: **Accepted**
Date: **2026-07-21**

## Decision

Use Python multiprocessing queues behind a topic-based component message bus for
the MVP.

Each component declares subscribed and published topics through `ComponentSpec`.
The controller registers all specs, finalizes the topology, and then creates
component-scoped buses. The bus enforces topic permissions and message types.

## Context

The simulator has independently owned modules that must evolve in parallel:
historical replay, matching, platform, and strategy. Direct function calls would
couple their lifecycles and make it harder to run modules in separate processes.

ZeroMQ remains a possible alternative, but it is unnecessary for the local MVP
until the team needs cross-host communication or stronger transport guarantees.

## Consequences

- Cross-component behavior is defined through explicit topics and schemas.
- All subscribers must be registered before topology finalization.
- Messages must be serializable across process queues.
- Shutdown, backpressure, and failure handling require explicit protocols.
- A component cannot publish to undeclared topics.

## Alternatives rejected

- Direct in-process calls: too tightly coupled for the intended component split.
- ZeroMQ for the initial build: additional operational complexity without a
  current cross-host requirement.

## Follow-up work

- Define end-of-stream and graceful-shutdown behavior.
- Add an end-to-end multiprocessing contract test.
- Decide queue bounds and backpressure behavior.
