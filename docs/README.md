# MMA Picks Tracker

A small, single-user Flask application for tracking UFC cards, analyst picks, American moneyline wagers, bankroll performance, and historical odds provenance.

The application is currently implementing Gate 6 (automated analyst ingestion). Gates 1–5 are approved.

## Current capabilities

- Create a named UFC card with metadata only, then add fights later.
- Enter and edit a full card in one table.
- Discover individual MMA bouts from The Odds API and select which bouts belong to a card.
- Import selected bouts into one internal card without creating provider-owned cards.
- Import current odds in a batched request for selected provider event IDs.
- Choose the exact sportsbook snapshot used for each wager.
- Preserve historical odds lines across refreshes and card edits.
- Track quota headers and surface provider errors in the local UI.
- Settle MMA cards manually and idempotently.
- Show dashboard, event, settlement, and initial metrics views.

The public `/api/v1` API exposes normalized picks, event metadata, analyst provenance, derived results, and statistics. Raw bookmaker snapshots, sportsbook names, recorded moneylines, stakes, and wagers remain private to the tracker.

## Repository layout

Application code is kept under `root/`.

```text
MMAPicks/
|-- README.md
|-- docs/
|-- requirements.txt
`-- root/
    |-- main.py                 # entry point
    |-- data/                   # ignored local SQLite database
    |-- src/
    |   |-- server.py           # Flask application factory
    |   `-- app/
    |       |-- providers/      # provider interfaces and adapters
    |       |-- services/       # card, odds, and settlement logic
    |       |-- templates/
    |       `-- static/
    |-- tests/
    `-- tools/
        `-- migrations/
```

No Python code belongs above `root/`. Documentation and repository metadata may remain above it.

## Setup

From the repository directory, create or activate the virtual environment and install dependencies:

```powershell
\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

Create the local configuration file:

```powershell
Copy-Item root\.env.example root\.env
```

Edit `root/.env` and set `ODDS_API_KEY`. Keep the real `.env` file private; it is ignored by Git. `root/.env.example` is safe to commit.

## Run the application

The entry point is inside `root/`:

```powershell
Set-Location root
python main.py run
```

Open <http://127.0.0.1:5000>.

The application creates or updates the ignored local database at `root/data/tracker.db` using numbered migrations under `root/tools/migrations/`.

## Continuous integration

GitHub Actions runs the test suite and Python compilation checks on every branch push and on pull requests against any branch. A merge creates a push to the target branch, so the merged commit is checked as well.

## Public API

The versioned API uses stable JSON envelopes:

```json
{"data": {}, "meta": {"version": "v1"}}
```

List responses add `limit`, `offset`, `count`, `total`, and `has_more`. Errors use an `error` object containing a stable `code` and `message`. List endpoints default to 50 records and accept a maximum `limit` of 200.

Available endpoints:

```text
GET /api/v1/analysts
GET /api/v1/analysts/{slug}
GET /api/v1/events
GET /api/v1/events/{event_id}
GET /api/v1/events/{event_id}/picks
GET /api/v1/analysts/{slug}/picks
GET /api/v1/analysts/{slug}/stats
```

Pick and statistics filters include `event`, `date_from`, `date_to`, `gender`, `weight_class`, `card_section`, `confidence_min`, `confidence_max`, `favorite`, `underdog`, and `result`. Favorite/underdog and ROI calculations may use private stored odds internally, but those odds are never returned by the API.

## Provider workflow

The Odds API exposes individual MMA bouts, not UFC cards. The tracker therefore keeps card ownership local:

1. Create a card at `/events/new` with promotion, name, and date.
2. Open `Discover provider bouts` for that card.
3. Select only the bouts that belong to the card.
4. Import the selected bouts.
5. Choose the exact imported sportsbook line when recording a wager.
6. Use `Refresh odds` only when a new odds request is wanted.
7. Settle winners manually after the event.

Discovery uses the quota-free The Odds API events endpoint. Paid current odds are requested only for explicit import or refresh actions. All imported snapshots remain historical records; refreshing odds never changes an existing wager's recorded line.

Manual sportsbook and moneyline entry remains available when provider data is unavailable or when a manual line is intentionally used.

## Automated analyst-source status

Gate 6 now has an explicit picks-provider boundary and an atomic ingestion service. Imported predictions preserve a source URL, source identifier, publication timestamp, and capture timestamp. A failed or conflicting import cannot replace existing manual or previously imported predictions.

The automated external adapter is intentionally not enabled yet. The official [TheWeasle YouTube channel](https://www.youtube.com/@TheWeasle) and [X profile](https://x.com/ThaWeasle) are candidate first-party surfaces, but the available public metadata does not provide a stable structured per-fight pick feed. The [YouTube Data API](https://developers.google.com/youtube/v3/docs/activities/list) can enumerate channel activity and video metadata; it does not by itself establish structured pick data. X access must use documented authenticated API access rather than page scraping.

Until a stable, technically permitted structured source is available, `UnsupportedPicksProvider` fails closed and manual whole-card entry remains the canonical workflow. No undocumented scraping, transcript inference, third-party aggregator dependency, or live source request is part of the application.

## Tests and validation

Run the complete offline test suite from the repository directory:

```powershell
\.venv\Scripts\python.exe -m pytest root\tests -q
\.venv\Scripts\python.exe -m compileall -q root
```

All external provider calls are mocked in tests. Tests must not use the live API key or consume provider quota.

## Configuration defaults

| Setting | Default |
| --- | ---: |
| Starting bankroll | `$7.50` |
| Default stake | `$0.50` |
| Maximum fights per card | `15` |
| Maximum card exposure | `$7.50` |
| Provider sport | `mma_mixed_martial_arts` |
| Provider market | `h2h` |
| Provider odds format | American |

Money is stored as integer cents. Timestamps are persisted as UTC ISO-8601 values. The initial seeded analyst is TheWeasle, but the data model supports additional analysts.

## Project plan

The canonical execution contract is [MMA Picks Tracker Implementation Plan](MMA%20Picks%20Tracker%20Implementation%20Plan.md). The seven-gate status is:

- Gate 1: Foundation - complete
- Gate 2: Manual tracker MVP - complete
- Gate 3: The Odds API integration - approved
- Gate 4: Analytics - approved
- Gate 5: Public API - approved
- Gate 6: Automated analyst ingestion - in progress; external source adapter pending a stable structured source
- Gate 7: RapidAPI preparation - planned

`plan.md` is retained as historical planning material and is not the active execution contract.
