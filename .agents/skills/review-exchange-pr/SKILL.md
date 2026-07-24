---
name: review-exchange-pr
description: Review exchange-simulator pull requests against the exact latest branch head, accepted architecture, interface documents, code contracts, tests, issue scope, and executable behavior. Use when asked to inspect, assess, summarize, reproduce findings for, or draft review comments on a repository PR or contributor branch, especially when schemas, payloads, protocols, topics, entry points, or cross-component behavior may drift between docs and code.
---

# Review Exchange PR

Produce an evidence-backed, scope-calibrated review without mutating the PR unless
the user explicitly requests an external action.

## Establish the review target

1. Resolve the repository, PR number, base branch, head branch, and exact head
   commit from GitHub.
2. Read the PR description, linked issue, existing reviews, and unresolved
   threads.
3. Refresh remote state when local refs may be stale.
4. Record the exact commit reviewed and recheck it before delivering findings.

Do not claim a finding applies to the latest branch without verifying the head.

## Load project contracts

Read:

- `docs/README.md`
- `docs/architecture.md`
- `docs/message-contracts.md`
- `docs/open-questions.md`
- relevant files in `docs/decisions/`

For market-data or messaging changes, also read
`docs/market-data-interface.md`. For controller, lifecycle, integration, or demo
changes, also read `docs/demo-runbook.md`.

When these files are absent from the base branch, inspect an in-flight
documentation branch if the user identifies one; otherwise state the limitation.

Treat accepted decisions as contracts and open questions as non-binding. Do not
mistake temporary PR behavior for a settled policy.

## Reconcile documentation and code

For every public or cross-component contract touched by the PR:

1. Identify the producer, topic, schema, consumer, and owning component.
2. Inspect the actual dataclass or model fields, topic and type registries,
   component specs, publish calls, receive logic, and relevant tests.
3. Find the corresponding claim in the architecture, message-contract, interface,
   runbook, open-question, or ADR documents.
4. Compare names, field types, routing, ordering, provenance, lifecycle, and
   failure behavior.
5. Classify the result:
   - **Aligned:** code, tests, and docs agree.
   - **Implementation gap:** accepted or required behavior is not implemented.
   - **Documentation gap:** code changes a contract without updating docs.
   - **Test gap:** the stated contract lacks executable coverage.
   - **Open decision:** the PR selects behavior the team has not accepted.
   - **Contradiction:** code and accepted documentation disagree.

Do not assume documentation is correct merely because it is detailed. Do not
assume code is authoritative merely because it runs. Report the exact mismatch
and which status or decision must be resolved.

## Calibrate scope

Classify the PR before judging completeness:

- **Architecture:** component boundaries, schemas, topics, interfaces, and one
  executable seam matter most.
- **Behavior:** matching rules and edge cases require focused tests.
- **Integration:** real processes, routing, completion, and shutdown must work
  end to end.
- **Cleanup:** avoid expanding into unrelated design changes.

For an initial architecture PR, require stable contracts and a smoke test; record
full behavioral coverage as follow-up unless the PR claims to complete it.

## Inspect safely

- Preserve dirty worktrees and unrelated user changes.
- Prefer a separate worktree or isolated temporary archive for execution.
- Inspect the complete diff against the actual base.
- Trace changes to schemas, topics, component specs, dependencies, entry points,
  and lifecycle code.
- Check whether every changed public contract updates its interface documents and
  tests in the same PR.
- Check direct conflicts with in-flight PR contracts.
- Run existing tests and static checks appropriate to the project.

Install dependencies only in an isolated environment and only when needed.

## Validate suspected findings

For each potential blocker:

1. Identify the exact code path and affected contract.
2. Construct the smallest realistic reproduction.
3. Run it against the exact reviewed commit when feasible.
4. Distinguish observed behavior from the judgment that the behavior is wrong.
5. Downgrade unconfirmed or policy-dependent concerns to design questions.

Never say “reproduced” without running the case. Include actual and expected
results.

## Rank the review

Separate findings into:

1. **Blockers:** definite failures or unstable public contracts within PR scope.
2. **Design questions:** choices requiring team confirmation.
3. **Follow-ups:** valuable work outside the current PR's declared scope.
4. **Cleanup:** non-functional improvements.

Prefer a few high-confidence findings over a long speculative list.

## Draft comments in the team's style

Make each proposed comment:

- collaborative rather than accusatory;
- concrete about the observed flow and consequence;
- explicit about whether it was reproduced;
- clear about the suggested direction or decision needed; and
- one copyable paragraph when practical.

Use questions for policy choices and direct requests for verified bugs. Refer to
the affected line where the wrong value or decision is introduced, not merely the
generic helper where it eventually fails.

## Deliver and act

Report:

- exact reviewed commit;
- verdict calibrated to PR scope;
- blockers, questions, and follow-ups;
- documentation/code/test alignment and any drift;
- checks and reproductions performed; and
- CI or environment limitations.

Write `review.md` only when requested. Do not post comments, submit a review,
resolve threads, request reviewers, mark readiness, merge, or otherwise mutate
GitHub unless the user explicitly authorizes that action.
