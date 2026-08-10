## References

API: https://the-odds-api.com/liveapi/guides/v4/

## MMA Picks Tracker + Public Picks API

### Mission

Build a small, maintainable Flask application for tracking UFC analyst predictions, moneyline performance, bankroll growth, and analyst-specific performance patterns.

The initial analyst is **TheWeasle**, but the architecture must support arbitrary analysts from the beginning.

The system should also expose normalized analyst prediction data through a clean HTTP API suitable for eventual publication on **RapidAPI**.

This is intentionally a small project. Avoid unnecessary infrastructure, frontend frameworks, ORMs, authentication systems, queues, microservices, or deployment complexity in the first version.

### Core stack

Use:

```text
Python
Flask
SQLite
pandas
NumPy where useful
Jinja
plain HTML/CSS
minimal vanilla JavaScript
requests/httpx for external API access
pytest
```

Architecture:

```text
External data providers
        ↓
ingestion / normalization
        ↓
      SQLite
        ↓
     pandas
        ↓
 ┌───────────────┐
 │               │
Flask UI      REST API
 │               │
Tracker       RapidAPI
```

SQLite is the persistent source of truth.

pandas is the primary analysis/query layer.

Do not use pandas as persistent storage and do not rewrite entire SQLite tables with `to_sql(..., if_exists="replace")` during routine application operations.

Use explicit inserts/updates within transactions.

---

# 1. Primary user workflow

The tracker should make entering and settling an entire UFC card extremely fast.

### New card

User opens:

```text
/events/new
```

The application can query an external card/odds provider and populate the upcoming fights.

Initial external provider:

```text
The Odds API
```

The exact API behavior, quota rules, endpoint contracts, and current pricing must be verified against the live documentation before implementation.

The application should retrieve as much of this automatically as the provider makes available:

```text
event
event date
fighter A
fighter B
fight start time
moneyline for fighter A
moneyline for fighter B
sportsbook/source
odds snapshot timestamp
```

Then display the entire card as an editable table.

Example:

| Bout | Fighter A | Fighter B | Pick      | Confidence | Division | Section |   ML |
| ---: | --------- | --------- | --------- | ---------: | -------- | ------- | ---: |
|    1 | Fighter A | Fighter B | Fighter A |         60 | WW       | Prelim  | +115 |
|    2 | Fighter C | Fighter D | Fighter D |         70 | SW       | Prelim  | -140 |

The user should be able to enter all analyst-specific fields directly in this table.

Required editable fields:

```text
analyst
pick
confidence percentage
predicted method, optional
gender
weight class
card section
bout order
moneyline used for wager
stake
```

Default stake for the initial strategy:

```text
$0.50
```

Saving the card should write the entire event atomically.

If one required database operation fails, the whole card import/save should roll back.

---

# 2. Bankroll model

Initial tracker configuration:

```text
Starting bankroll: $7.50
Default stake:     $0.50
Maximum card:      15 fights
Maximum exposure:  $7.50
```

The philosophy of the tracker is flat-moneyline bankroll building, not parlays or prop betting.

The application must calculate:

```text
current bankroll
starting bankroll
total amount wagered
gross winnings
net profit/loss
ROI
wins
losses
pushes/no contests
pick accuracy
cards tracked
peak bankroll
maximum drawdown
```

Canceled fights should not count as wagers or predictions settled.

The bankroll should be derived from transactions/results rather than stored as an independently editable running number.

---

# 3. Database design

Keep the schema normalized but small.

At minimum:

```text
analysts
events
fights
predictions
odds_snapshots
wagers
```

Potential schema:

### analysts

```text
id
slug
name
source_type
source_url
active
created_at
```

### events

```text
id
promotion
name
event_date
external_id
created_at
```

### fights

```text
id
event_id
fighter_a
fighter_b
weight_class
gender
card_section
bout_order
scheduled_at
status
winner
external_id
```

### predictions

```text
id
fight_id
analyst_id
picked_fighter
confidence
predicted_method
source_url
source_published_at
captured_at
```

### odds_snapshots

```text
id
fight_id
fighter
sportsbook
moneyline
captured_at
external_provider
```

### wagers

```text
id
prediction_id
stake
moneyline
placed_at
status
profit
settled_at
```

Use proper foreign keys and uniqueness constraints.

Important uniqueness examples:

```text
one event/external provider ID
one fight/external provider ID
one prediction per analyst per fight
```

Do not duplicate derived metrics in the schema unless there is a compelling performance reason later.

---

# 4. Odds ingestion

Create a provider abstraction rather than embedding The Odds API logic throughout Flask routes.

Example:

```python
class OddsProvider:
    def upcoming_events(self):
        ...

    def get_event(self, event_id):
        ...

    def get_odds(self, event_id):
        ...

    def get_results(self, event_id):
        ...
```

Then:

```python
class TheOddsAPIProvider(OddsProvider):
    ...
```

Normalize provider responses before they reach the rest of the application.

The rest of the system should not care whether card data eventually comes from The Odds API, SportsDataIO, Sportradar, or another source.

Persist the odds actually used by the experiment.

Never calculate historical wager performance using a current moneyline that changed after the prediction was captured.

---

# 5. Analyst-picks ingestion

This is the important second half of the project.

Create a separate provider interface:

```python
class PicksProvider:
    def analysts(self):
        ...

    def get_event_picks(self, analyst, event):
        ...
```

The first target analyst is:

```text
TheWeasle
```

But do not hardcode TheWeasle into the database model or API design.

The application should eventually support:

```text
TheWeasle
Analyst B
Analyst C
...
```

The source of automated picks is not yet locked.

X should investigate public, technically usable sources for retrieving analyst predictions.

Potential sources may include:

```text
structured prediction websites
public feeds
video metadata/transcripts where permitted and technically reliable
manual ingestion
future first-party analyst integrations
```

Do not build the system around undocumented scraping assumptions.

For v1, **manual whole-card prediction entry is an acceptable fallback**.

The architecture is more important than forcing unreliable automation immediately.

---

# 6. Public analyst-picks API

Expose normalized prediction data independently of the tracker UI.

Initial namespace:

```text
/api/v1/
```

Minimum endpoints:

```http
GET /api/v1/analysts

GET /api/v1/analysts/{analyst}

GET /api/v1/events

GET /api/v1/events/{event_id}

GET /api/v1/events/{event_id}/picks

GET /api/v1/analysts/{analyst_id}/picks

GET /api/v1/analysts/{analyst_id}/stats
```

Useful query filters:

```text
event
date_from
date_to
gender
weight_class
card_section
confidence_min
confidence_max
favorite
underdog
result
```

Example:

```http
GET /api/v1/analysts/theweasle/stats?gender=female&card_section=prelim
```

Example response:

```json
{
  "analyst": "TheWeasle",
  "filters": {
    "gender": "female",
    "card_section": "prelim"
  },
  "sample_size": 42,
  "wins": 31,
  "losses": 11,
  "accuracy": 0.7381,
  "roi": 0.0914
}
```

Every public response should use a stable documented schema.

Version the API from the beginning.

---

# 7. pandas analytics layer

Do not scatter analytics calculations throughout Flask routes.

Create an analysis module.

For example:

```text
analytics/
    bankroll.py
    analyst.py
    events.py
    performance.py
```

Functions should operate primarily on DataFrames.

Example:

```python
def analyst_performance(
    df,
    analyst_id=None,
    gender=None,
    weight_class=None,
    card_section=None,
    confidence_min=None,
):
    ...
```

The system must support analysis such as:

```text
overall analyst accuracy

ROI by analyst

accuracy by:
    gender
    division
    card section
    confidence band
    favorite/underdog
    odds range

ROI by the same categories

sample size for every subgroup
```

This is critical because the long-term goal is not merely:

```text
TheWeasle wins 67%
```

It is discovering where an analyst performs unusually well.

For example:

```text
Female prelim picks
75% accuracy
n = 44
+11% ROI

Men's welterweight undercard
73% accuracy
n = 51
+8% ROI
```

Do not present tiny samples as meaningful patterns.

Always expose sample size beside subgroup statistics.

---

# 8. Flask UI

Keep the interface extremely simple.

Primary routes:

```text
/
    dashboard

/events
    event list

/events/new
    import/create whole card

/events/<id>
    card view

/events/<id>/edit
    edit predictions / odds / metadata

/events/<id>/settle
    enter or import results

/analytics
    analyst analytics
```

### Dashboard

Show:

```text
CURRENT BANKROLL
$7.50

Starting bankroll
$7.50

Unit
$0.50

Record
0-0

Hit rate
0.0%

Net P/L
$0.00

ROI
0.0%

Cards tracked
0
```

Then show recent events in a table.

### Event view

One fight per row:

```text
Bout
Matchup
Analyst
Pick
Confidence
Moneyline
Stake
Result
Profit
```

Avoid unnecessary cards, animations, modals, dashboards, charts, or UI libraries.

The table is the product.

---

# 9. Automatic payout calculation

Support American moneylines correctly.

Positive moneyline:

```text
profit = stake × odds / 100
```

Negative moneyline:

```text
profit = stake × 100 / abs(odds)
```

Loss:

```text
profit = -stake
```

Push/cancel:

```text
profit = 0
```

Centralize this calculation and test it thoroughly.

Never duplicate payout formulas in templates or JavaScript as authoritative business logic.

Frontend calculations may preview values, but backend calculations are canonical.

---

# 10. Results settlement

The system should eventually support automatic results import.

Until that provider is implemented, settling a card manually should be extremely fast.

The event page should allow selecting the winner for every fight and pressing:

```text
Settle Card
```

The application should then:

```text
determine prediction win/loss
settle wagers
calculate profit
update derived bankroll
refresh analytics
```

All settlement operations should be idempotent.

Re-submitting the same results must not duplicate bankroll transactions or payouts.

---

# 11. RapidAPI readiness

The public API should be designed so deployment behind RapidAPI later requires minimal application changes.

Keep RapidAPI concerns outside the core domain logic.

Prepare for:

```text
API keys
request quotas
usage logging
rate limiting
plan tiers
```

But do not implement a custom billing system.

RapidAPI should handle marketplace subscription/billing concerns when the API is eventually published there.

Potential eventual plans might expose different:

```text
request quotas
historical depth
analyst coverage
analytics endpoints
```

Do not build pricing logic during initial implementation.

---

# 12. Data provenance

Every imported prediction should preserve its origin.

Store where practical:

```text
source URL
analyst
publication timestamp
capture timestamp
raw source identifier
```

Every imported odds snapshot should preserve:

```text
sportsbook
provider
capture timestamp
moneyline
```

This becomes especially important once historical data itself becomes a product.

---

# 13. Repository structure

Keep it boring and obvious.

Suggested starting structure:

```text
mma-picks/
├── app.py
├── config.py
├── requirements.txt
├── README.md
├── data/
│   └── tracker.db
├── tracker/
│   ├── db.py
│   ├── models.py
│   ├── payouts.py
│   ├── services/
│   │   ├── events.py
│   │   ├── predictions.py
│   │   └── settlement.py
│   ├── providers/
│   │   ├── odds/
│   │   │   ├── base.py
│   │   │   └── the_odds_api.py
│   │   └── picks/
│   │       ├── base.py
│   │       └── manual.py
│   ├── analytics/
│   │   ├── bankroll.py
│   │   └── analyst.py
│   ├── api/
│   │   └── v1.py
│   └── web/
│       └── routes.py
├── templates/
├── static/
└── tests/
```

Do not over-package the application if this structure proves heavier than necessary.

Clarity is more important than theoretical architecture purity.

---

# 14. Testing requirements

At minimum test:

```text
positive moneyline payout
negative moneyline payout
loss settlement
push settlement
canceled fight handling
card transaction rollback
duplicate prediction prevention
duplicate settlement prevention
bankroll calculation
ROI calculation
accuracy calculation
analyst subgroup filtering
API response schema
external provider normalization
```

External APIs must be mocked in tests.

Tests must never consume live API quota.

---

# 15. Initial seed configuration

The first bankroll experiment starts with:

```text
Bankroll: $7.50
Flat unit: $0.50
Strategy: straight moneyline only
Analyst: TheWeasle
```

No parlays should be implemented in the first release.

The point of v1 is accumulating clean historical data.

Parlay analysis comes later after sufficient observations exist.

---

# 16. Explicit non-goals for v1

Do not implement:

```text
React
Vue
Next.js
SQLAlchemy unless clearly justified
Postgres
Redis
Celery
Docker unless needed for deployment later
user accounts
social features
custom billing
parlay recommendations
AI-generated picks
live-betting functionality
mobile app
multi-user synchronization
complex charting
```

Keep v1 small.

---

# 17. Implementation sequence

### Gate 1: foundation

Create:

```text
repository structure
SQLite schema
DB initialization
configuration
payout engine
tests
```

### Gate 2: manual tracker

Implement:

```text
create event
whole-card entry
prediction entry
event table
manual settlement
bankroll calculations
dashboard
```

At the end of this gate, the application must already be usable without external APIs.

### Gate 3: odds/card provider

Integrate The Odds API behind the provider interface.

Implement:

```text
upcoming event discovery
card import
moneyline import
odds snapshot persistence
quota/error handling
```

### Gate 4: pandas analytics

Implement:

```text
overall accuracy
ROI
bankroll history
gender splits
weight-class splits
card-section splits
confidence splits
odds/favorite-underdog splits
sample-size reporting
```

### Gate 5: public API

Implement `/api/v1`.

Document schemas and endpoints.

### Gate 6: automated analyst ingestion

Investigate and implement the first reliable automated picks provider.

Do not compromise the rest of the application if no sufficiently stable source exists.

Manual entry must remain supported permanently.

### Gate 7: RapidAPI preparation

Prepare deployment and public documentation suitable for listing the prediction API on RapidAPI.

---

# Definition of done for initial MVP

The MVP is complete when I can:

1. Launch the Flask server locally.
2. Import or create an upcoming UFC card.
3. View the entire card in one table.
4. Enter TheWeasle's picks and confidence values across the whole card.
5. Attach a $0.50 moneyline wager to each selected fighter.
6. Save everything to SQLite.
7. Return after the event and settle the entire card.
8. See the bankroll automatically update from the initial $7.50.
9. See overall accuracy and ROI.
10. Filter TheWeasle's historical performance by gender, division, card section, confidence, and odds characteristics.
11. Retrieve the same normalized prediction data through `/api/v1`.
12. Run the full test suite without making live external API calls.

**Priority order: correctness, clean historical data, low-friction entry, useful analytics, then automation.**

That last distinction is important. I would not let X burn half the project trying to perfectly automate TheWeasle ingestion before the tracker itself works. The **manual provider is v1**, card/odds import removes most of the typing, and the automated picks provider becomes the final missing adapter. Then that adapter is also what turns the internal tracker into the RapidAPI product.
