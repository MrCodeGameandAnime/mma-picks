# MMA Picks Tracker Implementation Plan

## Summary

Build a single-user Flask application launched from `root/` with:

```powershell
python main.py run
```

The fixed structure is:

```text
root/
├── main.py
├── data/
├── src/
│   ├── server.py
│   └── app/
│       ├── templates/
│       └── static/
├── tests/
└── tools/
```

`root/src/server.py` remains a thin Flask controller. Routes, database access, business rules, providers, analytics, templates, and static assets live under `root/src/app/`. No Python code goes above `root/`.

## Implementation

### Gate 1 — Foundation

- Keep `root/.env` ignored and add `root/.env.example`.
- Rename the current `KEY` variable to `ODDS_API_KEY`.
- Store SQLite at `root/data/tracker.db`.
- Use numbered SQL migrations under `root/tools/`, recording applied versions in `schema_migrations`.
- Create:
  - `settings`: starting bankroll 750 cents, default stake 50 cents, 15-fight maximum, 750-cent maximum exposure.
  - `analysts`: unique slug, name, source metadata, active status.
  - `events`: promotion, card name/date, status, timestamps.
  - `fights`: event, fighters, division, gender, section, order, schedule, result, provider identity.
  - `predictions`: unique analyst/fight pair, pick, 0–100 confidence, optional method and provenance.
  - `odds_snapshots`: fighter, sportsbook, provider, American line, capture time.
  - `wagers`: one per prediction, optional snapshot reference, stake cents, recorded line, status, profit cents, settlement time.
- Store money as integer cents and American lines as integers.
- Calculate payouts with `Decimal`, rounding half-up to the nearest cent.
- Use UTC ISO-8601 timestamps.
- Seed TheWeasle without hardcoding that analyst into domain logic.
- Construct Flask in `server.py` and register separate web and `/api/v1` blueprints from `src/app/`.

### Gate 2 — Manual Tracker MVP

- Implement `/`, `/events`, `/events/new`, `/events/<id>`, `/events/<id>/edit`, `/events/<id>/settle`, and `/analytics`.
- Allow draft cards containing incomplete picks or wagers.
- Save each whole-card submission atomically.
- Validate finalized wagers against the 15-fight and $7.50 exposure limits.
- Permit manual moneylines and sportsbook/source entry when provider data is unavailable.
- Settle the whole card transactionally:
  - win: calculated positive profit;
  - loss: negative stake;
  - draw/no contest: push with zero profit;
  - canceled fight: void and excluded from wager and prediction totals.
- Re-submitting identical results is a no-op.
- Corrected results replace derived outcomes and profits atomically.
- Derive metrics rather than storing a running bankroll:
  - current bankroll = starting bankroll + net settled profit;
  - ROI = net profit ÷ total non-void amount wagered;
  - accuracy = wins ÷ wins plus losses;
  - gross winnings = positive profit, excluding returned stake;
  - pushes remain in wager totals; canceled fights do not;
  - peak bankroll and drawdown follow chronological settlements.

### Gate 3 — The Odds API

- Use sport key `mma_mixed_martial_arts`, market `h2h`, American format, and default region `us`. The provider exposes individual bouts rather than UFC card identities. [Official MMA documentation](https://the-odds-api.com/sports-odds-data/mma-odds.html)
- Users create/name a card and select matching provider bouts for import.
- Keep division, gender, card section, and bout order manually editable because the provider does not supply them.
- Query the quota-free events endpoint for discovery, then request current odds only when the user initiates an import or refresh. Track quota headers and surface provider errors without losing entered data. [Official API v4 documentation](https://the-odds-api.com/liveapi/guides/v4/)
- Display available sportsbooks and let the user choose the recorded line per fight.
- Persist all imported snapshots, but never replace a wager’s historical recorded line with newer odds.
- Do not use paid historical endpoints in v1.
- Keep manual settlement canonical unless MMA result coverage is separately verified.
- Never expose raw bookmaker snapshots through `/api/v1`; provider terms prohibit redistributing the market data as a standalone API/feed. [The Odds API terms](https://the-odds-api.com/terms-and-conditions.html)

### Gate 4 — Analytics

- Load normalized SQLite query results into pandas DataFrames.
- Keep calculations in dedicated analytics functions, not routes or templates.
- Support accuracy, ROI, sample size, bankroll history, peak bankroll, and maximum drawdown.
- Support gender, division, card section, confidence band, odds range, favorite/underdog, analyst, result, and date filters.
- Always display subgroup sample size and avoid presenting tiny samples as meaningful findings.

### Gate 5 — Public API

- Use analyst slugs consistently in public URLs and internal numeric IDs for events.
- Implement:
  - `GET /api/v1/analysts`
  - `GET /api/v1/analysts/{slug}`
  - `GET /api/v1/events`
  - `GET /api/v1/events/{event_id}`
  - `GET /api/v1/events/{event_id}/picks`
  - `GET /api/v1/analysts/{slug}/picks`
  - `GET /api/v1/analysts/{slug}/stats`
- Use stable envelopes:
  - success: `data` plus `meta`;
  - failure: `error` containing a stable code and message.
- Paginate list responses with a default limit of 50 and maximum of 200.
- Expose prediction provenance and derived results/statistics.
- Do not expose sportsbook names, raw odds snapshots, or recorded provider moneylines.
- Favorite/underdog and ROI filters may use private stored odds internally.

### Gates 6–7 — Analyst Automation and RapidAPI

- Add a picks-provider interface while retaining manual entry permanently.
- Automate TheWeasle only if a public, stable, technically permitted source is found.
- Preserve source URL, source identifier, publication time, and capture time.
- Keep failed automated imports isolated from existing data through transactions.
- Add deployment, API documentation, error conventions, usage logging, and rate-limit hooks for RapidAPI.
- Do not add user accounts, custom billing, parlays, generated picks, or live betting.

## Test Plan

- Payouts: positive and negative lines, loss, push, void, invalid line, and half-cent rounding.
- Database: migrations, foreign keys, uniqueness, seed idempotency, rollback, and duplicate prevention.
- Cards: draft saves, complete atomic saves, exposure limits, canceled fights, repeated settlement, and corrected settlement.
- Metrics: bankroll, gross winnings, net profit, ROI, accuracy, peak bankroll, and drawdown.
- Analytics: every subgroup filter, combined filters, empty datasets, and sample-size reporting.
- Provider: normalized MMA responses, missing bookmakers, stale odds, malformed payloads, authentication errors, quota exhaustion, 429 handling, and timeouts.
- API: endpoint schemas, pagination, filters, missing resources, invalid parameters, and confirmation that raw odds are never returned.
- All external requests use mocks; tests never consume the live API key or quota.

## Assumptions and Acceptance

- Python 3.14.6, Flask 3.1, SQLite, pandas, Jinja, plain CSS, minimal JavaScript, and `httpx`.
- Single local user, no authentication, no ORM, and no background workers.
- The MVP is accepted when a full card can be created, populated with TheWeasle picks, wagered at $0.50 per fight, settled, analyzed, and retrieved through `/api/v1`, with the complete test suite passing offline.
- Each gate must be usable and tested before beginning the next; Gate 2 delivers the first operational tracker.
