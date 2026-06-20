# Rowbound — Roadmap Orientation Notes (Phase 0)

Snapshot of actual repo state vs. the development plan's assumptions, recorded
before layering product/brand on top. Date: 2026-06-20.

## Modes

- **Request mode + settlement engine: LIVE and well-tested.** Escrow (fund →
  hold), per-unit allocation with `min(eligible, remaining)` capping, cross-source
  exact-key dedup (`AcceptedKey`), acceptance window + confirm/claim/sweep,
  disputes, reviews-after-paid, gated MinIO/Local delivery, GDPR warranties.
- **Buy existing (catalog) — NOT built.** No `Listing` / catalog model or intake
  surface. Plan Phase 4 adds it.
- **Collect (forms/field) — NOT built.** No collection-form spec model or dispatch
  surface. Plan Phase 5 adds it.
- The engine is mode-agnostic (`DataRequest` + `Submission` + `Ledger`), but the
  distinct intake paths/UIs for modes 2 and 3 do not exist yet — matches the
  plan's expectation.

## Models (backend/app/models.py)

Present: `License`, `UserAuth`, `DataRequest`, `Submission`, `UserProfile`,
`UserAnalytics`, `Review`, `Dispute`, `AcceptedKey`, `Ledger`,
`ProcessedStripeEvent`.

- `DataRequest.pricing_mode` enum = `per_unit | fixed_bounty` (confirmed).
- **No** `Listing` or collection/`CollectionForm` models — Phases 4–5 introduce them.
- Money columns are `Numeric(12,2)`; ledger is append-only with unique `external_ref`.

## Brand

- App still presents generically: header/footer say **"Data Exchange"**, homepage
  hero is **"Open Data for Everyone"**, footer contact `contact@dataexchange.com`.
- `Rowbound_*` SVGs are **not** in `frontend/public` or `frontend/assets` (only
  default `favicon.ico` + `robots.txt`). Phase 1 imports them.
- No `tailwind.config.*` (uses `@nuxtjs/tailwindcss` defaults); `assets/css/main.css`
  exists but isn't registered via `nuxt.config` `css:`. Phase 1 wires tokens + css.

## CI

- **No `.github/workflows/`** — CI does not exist. Phase 2 adds `ci.yml`.

## Frontend auth

- **Already hardened** (prior FE1–FE5 work, on `main`): access token in memory only
  (no `localStorage`), cookie-rehydrate plugin, single-flight 401→refresh→retry in
  `useApi`, `postForm` multipart, FastAPI error normalization, real logout
  (`POST /auth/logout` clears `refresh_token_hash` + deletes cookie). Phase 2's
  auth item is therefore satisfied — only CI remains there.

## Deltas from the plan's assumptions

- None material. The plan's Phase 0 expectations hold: Request+engine live,
  Buy/Collect absent, brand generic, assets external, CI missing, auth done.

## Sequencing note (this session)

Executing the non-speculative do-early items: Phase 1 (brand), Phase 2 (CI), and
the security do-first blocker S1 (IDOR/authz audit) + S6 quick wins. Phases 4–8
(catalog, collect, cross-mode, instrumentation) are gated behind the plan's
business-validation go/no-go decisions and supplier density — deferred, not built
speculatively, per the plan's own "don't build everything at once."
