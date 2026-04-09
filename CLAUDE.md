# Grocery Assistant

## Purpose
Build a household grocery assistant with Discord + SMS intake, a shared grocery list, Instacart draft generation, and a strict approval gate that blocks all ordering unless Vern explicitly approves.

## Guardrails
- Never implement auto-submit in MVP.
- Approval must be per-order-session.
- Only Vern can approve.
- Ambiguous items should be flagged, not silently guessed.
- Keep the stack boring and easy to run locally.

## Delivery Expectations
- Propose a short architecture before deep implementation.
- Build phase 1 first.
- Add tests for normalization and approval gating.
- Document how to run it locally.

## Suggested Direction
- Python is fine for MVP.
- SQLite is preferred for local persistence.
- Keep adapters for Discord and SMS isolated behind interfaces.
- Start with a CLI or local service layer before any browser automation.

## Repo Priorities
1. correctness
2. safety
3. simplicity
4. traceability

## MVP Deliverables
- README
- project scaffold
- SQLite-backed models or storage layer
- intake event model
- grocery list normalization logic
- approval session logic
- Instacart-ready draft generation
- tests for key logic
- clear next-steps list for phase 2
