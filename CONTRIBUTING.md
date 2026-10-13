# Contributing to Nova Shop

## Ground rules

- **English only** in UI strings, comments, and docs (en-GB spelling).
- **Buttons and descriptions are frozen.** UI work never renames, removes, or
  rewords an existing button label or description.
- **Money code is guilty until proven innocent.** Anything touching balances,
  payments, deposits, or fulfilment needs a test and an idempotency story.

## Branches

- Work happens on feature branches off `refactor/nova-shop-professional`.
- Never commit directly to a retired branch; check `git branch --show-current`
  before you start.

## Commits

- Conventional-commit style subjects: `fix(scope): …`, `feat(scope): …`,
  `test(scope): …`, `docs: …`, `chore: …`.
- One logical change per commit; say *why* in the body when it isn't obvious.

## Before you push

1. `make test` — the suite must pass (`bot/tests`).
2. `make lint` — ruff, line length 100, target py312.
3. If you touched money paths, say which invariant your change preserves
   (atomicity, idempotency, no-overdraw, fulfil-exactly-once) in the PR body.

## Architecture decisions

Significant decisions get an ADR under `docs/adr/` (numbered, dated, with the
alternatives considered). See `docs/ARCHITECTURE.md` for the current design
and its one rule: **clients propose actions; the server verifies facts; the
database claims state; fulfilment happens once.**
