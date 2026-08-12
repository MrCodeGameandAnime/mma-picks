# MMA Picks Tracker

A small, single-user Flask application for tracking UFC cards, analyst picks, American moneyline wagers, bankroll performance, and historical odds provenance.

The application is currently complete through Gate 3. Gate 4 (pandas analytics) has not started.

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

The `/api/v1` blueprint is scaffolded, but the complete public analyst-picks API is planned for Gate 5. Raw bookmaker snapshots are kept private to the tracker.

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
- Gate 3: The Odds API integration - complete pending review/closure
- Gate 4: Analytics - not started
- Gate 5: Public API - planned
- Gate 6: Automated analyst ingestion - planned
- Gate 7: RapidAPI preparation - planned

`plan.md` is retained as historical planning material and is not the active execution contract.
