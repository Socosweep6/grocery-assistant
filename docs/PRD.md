# Grocery Assistant PRD

## Summary
Build a lightweight grocery assistant that accepts grocery items from a Discord thread and SMS from Cara, maintains one clean shared grocery list, prepares an Instacart-ready order draft, and never places an order without Vern's explicit approval.

## Product Goal
Reduce household grocery coordination friction while keeping full human control over checkout.

## Users
- Primary: Vern
- Secondary: Cara

## Core Constraints
- Instacart is the fulfillment path.
- No order may ever be placed without explicit Vern approval.
- Cara should be able to add items by text without being in Discord.
- MVP should optimize for reliability and low setup overhead over full autonomy.

## MVP Scope
### Inputs
- Discord thread messages
- SMS messages from Cara

### Outputs
- One unified grocery list
- Deduped, normalized, categorized items
- Instacart-ready cart draft output
- Review summary before any checkout action
- Explicit approval gate

### Out of Scope for MVP
- Auto-submit orders
- Automatic payment
- Meal planning
- Coupon optimization
- Multi-retailer support
- Home pantry inventory
- Voice input

## Functional Requirements
### 1. Multi-source intake
The system must ingest grocery items from:
- Discord thread messages
- SMS from Cara

Each intake event should capture:
- raw message text
- parsed items
- source channel
- sender
- timestamp

### 2. Unified master grocery list
All items must merge into one master list.

The list should:
- dedupe obvious duplicates
- normalize common variants
- preserve useful notes
- keep source traceability
- support status like pending, reviewed, drafted, ordered

Suggested categories:
- produce
- protein
- dairy
- pantry
- frozen
- household
- other

### 3. Natural-language parsing
Support messages like:
- bananas
- 2% milk
- paper towels
- ground turkey 2 lb
- bread
- don't forget dish soap
- bananas, eggs, oat milk

Parser behavior:
- split multi-item messages when obvious
- infer quantity only when explicit or highly clear
- avoid confident guessing on ambiguous items
- preserve notes and modifiers

### 4. List views
Support commands or actions for:
- show grocery list
- show grocery list by category
- show recently added items
- show what Cara added
- show unresolved ambiguities

### 5. Instacart-prep workflow
When Vern requests cart prep, the system should:
- gather current pending items
- normalize item names for Instacart search
- identify ambiguities
- attach substitution guidance when known
- produce a reviewable order draft

MVP can stop at a clean Instacart-ready draft output. Browser automation can be phase 2.

### 6. Hard approval gate
The system must never place an order without explicit Vern approval.

Rules:
- No automatic checkout submission
- No stored blanket permission
- Approval is required per order session
- Only Vern can approve
- Vague acknowledgments do not count

Approved examples:
- approve order
- place this order
- go ahead and submit

Not approved:
- looks good
- nice
- thumbs up
- prior general consent

### 7. Review summary
Before any order submission attempt, present:
- categorized items
- quantities
- unresolved items
- substitution assumptions
- estimated total if available
- pickup vs delivery mode if available
- current status: awaiting approval

### 8. Safe ambiguity handling
If an item is unclear, flag it instead of guessing.

Examples:
- milk without type or size
- bread without type
- chips without brand/flavor
- bananas without quantity

## Nice-to-Have After MVP
- Browser-assisted Instacart cart drafting that stops before final submit
- User/item preferences
- Exact-item-only vs substitutions-okay rules
- Recurring staples
- Weekly reminder flow
- Shared external intake form as a backup to SMS

## User Stories
### Vern
- As Vern, I want to add items in Discord so the household list stays centralized.
- As Vern, I want Cara to add items by SMS without joining Discord.
- As Vern, I want duplicates cleaned up automatically.
- As Vern, I want an Instacart-ready review before checkout.
- As Vern, I want a strict approval gate so nothing is ever ordered without my explicit signoff.

### Cara
- As Cara, I want to text grocery items naturally.
- As Cara, I want my additions to appear in the shared list.

## Recommended MVP Architecture
### Components
1. Intake layer
   - Discord message intake
   - SMS webhook or polling intake
2. Parser and normalization layer
   - item extraction
   - dedupe and categorization
3. Persistence layer
   - events, items, preferences, order sessions, approvals
4. Review layer
   - list views
   - unresolved ambiguity reporting
5. Instacart draft layer
   - generate Instacart-ready draft output
6. Approval gate
   - strict per-session approval logic

### Storage Recommendation
Use SQLite for MVP.

Reason:
- simple local setup
- easy auditing
- enough structure for events, items, sessions, approvals
- easy to swap later if needed

Suggested tables:
- users
- intake_events
- grocery_items
- grocery_item_sources
- preferences
- cart_sessions
- cart_session_items
- approvals

## Build Phases
### Phase 1
- project scaffold
- SQLite schema
- Discord intake stub/interface
- SMS intake stub/interface
- parsing and normalization
- master grocery list state
- review commands/output
- strict approval session model
- Instacart-ready draft output

### Phase 2
- browser-assisted Instacart cart drafting
- substitution preferences
- recurring staples
- improved heuristics

## Engineering Requirements
- Keep implementation simple and inspectable.
- Favor explicit state over hidden automation.
- Add tests around parsing, dedupe, and approval gating.
- Log approvals with timestamp and source.
- Make it impossible to accidentally submit an order from MVP.

## Acceptance Criteria for MVP
- Cara can add grocery items via SMS intake.
- Vern can add grocery items via Discord intake.
- System stores all events and maintains one shared grocery list.
- System dedupes and categorizes obvious duplicates.
- System can display the current grocery list and unresolved ambiguities.
- System can generate an Instacart-ready order draft.
- System requires explicit Vern approval per order session.
- System does not auto-submit any order.

## Open Decisions Claude Should Resolve
- exact local app/framework choice for MVP
- ingestion adapter shape for Discord and SMS
- CLI vs lightweight web UI for review flow
- best place to enforce approval gating so browser automation can never bypass it later

## Instructions for Claude
Start by proposing a minimal architecture and file layout. Then scaffold phase 1 inside this repo. Create a clean project folder structure, a short README, a focused CLAUDE.md for this repo, and the initial implementation skeleton with tests for the approval gate and list normalization. Prefer boring technology and reliable defaults.
