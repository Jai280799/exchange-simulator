# ADR 0004: Centralize component topology

Status: **Accepted**
Date: **2026-07-22**

## Decision

Define the complete set of `ComponentSpec` objects in one dedicated topology
module and have the system controller register that collection.

Component modules own runtime behavior and stable component names. The
composition root owns subscriptions and publications.

## Context

The topic graph is a system-level contract. If specs are scattered across
component modules, reviewers must inspect many files to understand which
components communicate. If specs are embedded directly in controller lifecycle
code, startup logic becomes harder to read.

A dedicated topology module provides one auditable view without coupling
component implementation to process orchestration.

## Consequences

- Missing subscriptions and conflicting publishers are easier to review.
- Topic changes require updating the central contract and affected behavior.
- The controller remains responsible for registration/finalization but not for
  defining business logic.
- Temporary component-local spec helpers should be removed during integration.

## Alternatives rejected

- Component-owned specs only: good locality, but the system graph is scattered.
- Specs embedded throughout the controller: one-file visibility, but mixes
  topology with lifecycle code.

## Follow-up work

- Create the topology module when feed, engine, and platform are integrated.
- Add a test that finalizes the complete topology and creates every component bus.
