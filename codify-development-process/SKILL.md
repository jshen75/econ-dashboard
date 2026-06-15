---
name: codify-development-process
description: Codify a product development process for user-facing features, backend-backed refactors, and workflow changes. Use when Codex needs to scope an end-user flow, define 3-4 success criteria, map backend modules and adjacent concerns, verify architecture before building, coordinate Codex goals or fan-out work, add Playwright smoke tests and Django backend tests, and prepare push, deploy, and user-test guidance including staging, fake integrations, and local manual workflow testing.
---

# Codify Development Process

## Overview

Use this skill to turn a product change request into a disciplined implementation path: scope the end-user outcome, map the backend surface area, build or delegate the work, verify with the right tests, and decide how to validate integrations before deploy.

## Operating Principles

- Start at the end-user process level. Avoid backend-first scoping until the user flow and success criteria are clear.
- Keep success criteria concrete and few: usually 3-4 points that can be observed, tested, or demoed.
- Treat backend module mapping as a required design step, not an implementation detail.
- Keep unit tests close to backend modules. Use Playwright for smoke coverage of the user flow.
- Prefer realistic fakes, sandboxes, or staging toggles for integrations; do not hit production third-party systems during routine tests.

## Workflow

### 1. Scope

Produce a short scope before coding:

1. Name the end-user flow in one sentence.
2. Define 3-4 success criteria from the user's point of view.
3. Identify what is explicitly out of scope.
4. List all backend modules likely involved, including models, services, tasks, serializers, views, permissions, signals, API clients, webhooks, feature flags, migrations, admin surfaces, and observability.
5. Identify adjacent concerns: auth, tenancy, billing, rate limits, idempotency, async jobs, retries, data backfills, caching, emails, audit logs, compliance, and rollout safety.

Do not let success criteria become implementation tasks. "User sees a confirmation after Gmail connection succeeds" is useful; "Add OAuth model field" belongs in backend mapping.

### 2. Build Plan

Before editing code, verify the backend shape:

- Read the modules identified during scoping and confirm ownership boundaries.
- Check whether existing services, selectors, clients, tasks, or domain helpers should own the change.
- Look for brittle coupling, duplicated integration logic, missing transaction boundaries, insufficient idempotency, and error handling gaps.
- Decide whether the task is a feature set, refactor, or both. If both, separate enabling refactors from user-visible behavior.
- Convert the plan into either a single Codex goal or fan-out work when independent modules can be changed in parallel.

Use fan-out only when work streams have clear boundaries, such as "OAuth client hardening", "Django service and tests", and "Playwright user flow"; avoid fan-out when the data model or API contract is still moving.

### 3. Implement

Implement in the smallest coherent slices:

- Land backend structure first when the frontend depends on new API behavior.
- Keep integration boundaries injectable so tests can fake external systems.
- Add logging or metrics for states users or operators will need to understand.
- Preserve feature flags, rollout controls, or admin overrides when the change affects production workflows.
- Update migrations, fixtures, factories, and settings only where the feature requires them.

### 4. Verify

Create verification at two levels:

- Playwright smoke test: cover the primary end-user flow and one important failure or empty state when practical. Keep it broad and stable, not exhaustive.
- Django tests: keep unit and integration tests scoped to backend modules and adjacent concerns. Cover services, permissions, validation, task behavior, idempotency, retries, and integration adapters without requiring the UI.

Choose test style by risk:

- Pure domain logic: fast unit tests.
- ORM behavior, permissions, API views, tasks, and transactions: Django tests.
- Browser-level confidence in a user journey: Playwright smoke tests.
- Third-party calls: adapter tests with fakes, recorded fixtures, provider sandboxes, or staging-only checks.

### 5. Push, Deploy, User Test

Before final handoff:

- Summarize the end-user flow and success criteria.
- List backend modules touched and tests added.
- Report test commands and outcomes.
- Note deploy steps, migrations, feature flags, settings, and rollback considerations.
- Recommend user testing against either non-integrated or integrated flow based on the use case.

## Integration Testing Guidance

For integrations such as Gmail:

- Prefer provider sandbox or test accounts when available. Use real OAuth and API behavior without production user data.
- If no sandbox exists, fake the provider at the adapter boundary in local and automated tests. Use deterministic fixtures for responses, errors, rate limits, expired tokens, revoked permissions, and webhook payloads.
- In staging, use a dedicated test tenant/account and clearly labeled test credentials. Keep staging secrets separate from production and restrict outbound effects when possible.
- For webhooks, support local replay from saved payloads and staging delivery to a public tunnel or staging endpoint. Verify signature validation separately from business logic.
- For email-like side effects, route to a test inbox, mail capture service, or disabled-send mode that records intended sends.
- Treat one staging integrated test as confidence for wiring, not a substitute for backend tests around every branch.

Use this decision rule:

- Fake locally for development speed, deterministic CI, destructive operations, rate-limit risk, or unavailable provider sandboxes.
- Use staging integration for auth wiring, scopes, redirect URIs, webhook delivery, provider-specific validation, and final confidence before user testing.
- Use production only after deploy, behind flags or limited rollout, with test accounts or internal users first.

## Local Manual Workflow Testing

To manually test a longer workflow without staging:

1. Run the app and workers locally, including background queues, schedulers, cache, and mail capture if the flow depends on them.
2. Seed a realistic local user, organization, permissions, and feature flags.
3. Fake third-party adapters through settings, dependency injection, local stub servers, or recorded fixtures.
4. Provide fixtures for each important external state transition, such as "Gmail connected", "token expired", "message imported", or "provider error".
5. Run the browser flow end to end against local services, then inspect database rows, task logs, and emitted events.
6. Escalate to staging only for behavior that cannot be represented locally, such as OAuth redirect registration, real webhook delivery, or provider enforcement of scopes and quotas.

## Response Shape

When using this skill, structure the working plan or final summary as:

- `Scope`: end-user flow, success criteria, non-goals.
- `Backend map`: modules and adjacent concerns.
- `Build plan`: feature/refactor slices and ownership.
- `Verification`: Playwright smoke test, Django tests, integration strategy.
- `Deploy/user test`: migration, flags, staging/local choice, rollback notes.
