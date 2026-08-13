# MMAPicks Post-Gate 7 Unified Direction

## Purpose

After Gate 7, MMAPicks stops being only a picks tracker and begins expanding into a broader MMA data platform.

The post-Gate-7 program has three tightly connected expansions:

1. **Historical analyst and betting-pick corpus**
2. **Comprehensive fighter, fight, and statistics corpus**
3. **Transcript recovery engine for extracting exact picks from analyst videos**

These should not be built as isolated feature dumps. They should feed one canonical MMA data graph:

```text
Analysts → Predictions → Fights ← Fighters → Statistics
                         ↑
                       Events
                         ↑
                        Odds
```

Provenance, timestamps, results, market data, and historical state connect the entire system.

The objective is not merely to collect more rows. The objective is to build a normalized, auditable historical dataset capable of answering questions about analyst performance, fighter context, betting value, confidence calibration, and market behavior at the time each prediction was made.

---

# 1. Foundation Before Expansion

Gate 6 and Gate 7 should remain narrow and finish the plumbing before the large data expansion begins.

The post-Gate-7 systems will depend on the guarantees already being established:

- safe analyst-ingestion boundaries;
- manual fallback;
- atomic imports;
- source provenance;
- stable event and fight identities;
- public API contracts;
- analytics separation;
- historical odds preservation;
- deployment and API readiness.

Once historical importers, fighter datasets, and transcript extraction begin processing hundreds of thousands or millions of records, weak identity or provenance rules become expensive to repair.

The existing ingestion boundary should therefore remain the final trusted checkpoint before any automated source is allowed to modify canonical MMAPicks data.

---

# 2. Expansion One: Historical Analyst and Betting-Pick Corpus

## Goal

Recover as much historical analyst prediction data as possible and normalize it into MMAPicks.

MMA Prophecy is an important first source because its current public structure exposes a natural discovery hierarchy:

```text
Leaderboard
    ↓
Channel
    ↓
Video
    ↓
Picks
```

Example source path:

```text
https://mmaprophecy.com/
    ↓
https://mmaprophecy.com/leaderboard
    ↓
https://mmaprophecy.com/channel/UCZD2qRU8J82XGdGdUWYneNQ
    ↓
https://mmaprophecy.com/video/QPAaIueT50E
```

MMA Prophecy pages already expose useful historical concepts including:

- analyst/channel identity;
- analyzed videos;
- event-level standings;
- moneyline performance;
- prop performance;
- CLV;
- hit rate;
- units;
- divisions;
- historical video lists;
- individual picks.

The historical importer should not directly dump scraped rows into `predictions`.

It should preserve three layers:

```text
Raw Source
    ↓
Parsed Source Record
    ↓
Canonical MMAPicks Record
```

## Required provenance

Every imported historical prediction should be able to answer:

- where did this record come from?
- which source system?
- which analyst/channel?
- which source page?
- which video?
- which event?
- which fight?
- which fighter was selected?
- was it a moneyline pick or a prop?
- what confidence was supplied, if any?
- what method was predicted, if any?
- when was the source published?
- when was it captured?
- what source price was supplied, if any?
- what closing price is available, if any?
- what was the result?
- what were the resulting units?
- which parser version created the normalized row?
- was identity normalization automatic or manually reconciled?

## Source preservation

Historical source artifacts should be retained with hashes or equivalent immutable identity.

Conceptually:

```text
source_capture
    source_type
    source_url
    source_identifier
    captured_at
    content_hash
    parser_version
```

This allows a record to remain auditable even if a source website later changes its layout or removes the page.

## Resumable backfill

The historical backfill should run as a resumable pipeline rather than one enormous scraper invocation:

```text
Discover channels
    ↓
Discover videos
    ↓
Capture source records
    ↓
Parse candidate picks
    ↓
Resolve event identities
    ↓
Resolve fight identities
    ↓
Resolve fighter identities
    ↓
Validate
    ↓
Commit canonical records
```

Every stage should be checkpointed so interrupted work can resume without reprocessing completed material.

## Reconciliation against source aggregates

MMA Prophecy aggregate statistics can be used as an ingestion-integrity check.

For example, if a channel page reports a specific number of moneyline picks and a specific net-unit result under its grading method, MMAPicks should be able to reproduce those values from the normalized imported records.

If the source says one number and MMAPicks calculates another, that becomes a reconciliation failure to investigate rather than silently accepting an incomplete import.

This is particularly useful for identifying:

- missing videos;
- missed picks;
- duplicate picks;
- parser mistakes;
- incorrect odds normalization;
- incorrect result mapping.

## Source qualification before bulk scraping

Before turning MMA Prophecy or any other source into a production bulk importer, explicitly qualify:

- robots policy;
- terms;
- request behavior;
- HTML versus callable backend endpoints;
- rate limits;
- schema stability;
- licensing or redistribution constraints;
- source corrections behavior.

A public page should not automatically be treated as permission for unrestricted bulk redistribution.

---

# 3. Expansion Two: Comprehensive Fighter and Fight Corpus

## Goal

Turn fighters from strings embedded in fight rows into canonical entities with historical identity and statistics.

Current fight records fundamentally refer to fighters by name. The long-term model should instead treat fighters as first-class objects.

Conceptually:

```text
fighter
    internal_fighter_id
    canonical_name
    aliases
    date_of_birth
    nationality
    height
    reach
    stance
    debut
    active_status

fighter_external_identity
    fighter_id
    provider
    external_id

event
    ↓
fight
    fighter_a_id
    fighter_b_id
    winner_id

fight_round_stats
    fight_id
    fighter_id
    round
    knockdowns
    significant_strikes
    total_strikes
    takedowns
    submission_attempts
    control_time
    ...
```

## Historical state matters

A fighter profile is not fully static.

The following can change over time:

- record;
- ranking;
- weight class;
- age;
- championship status;
- organizational status;
- measurements or reported physical data;
- competitive history.

Therefore important historical dimensions should be represented as snapshots rather than only storing the latest value.

Conceptually:

```text
fighter_ranking_snapshot
fighter_record_snapshot
fighter_measurement_snapshot
fighter_status_snapshot
```

The system should eventually be able to answer:

> What was this fighter's record when the analyst made the pick?

rather than only:

> What is the fighter's record today?

That distinction is essential for historically valid analytics and modeling.

## Candidate data classes

The fighter and fight corpus should eventually include as much qualified data as practical:

### Fighter identity and profile

- canonical name;
- aliases;
- DOB;
- nationality;
- stance;
- height;
- reach;
- active status;
- organization;
- division history.

### Fight history

- event;
- event date;
- promotion;
- opponent;
- result;
- method;
- round;
- time;
- weight class;
- bout order.

### Round and fight statistics

- knockdowns;
- significant strikes;
- total strikes;
- striking accuracy;
- striking defense;
- takedowns;
- takedown accuracy;
- takedown defense;
- submission attempts;
- control time;
- other available round-level metrics.

### Historical market context

Where qualified sources permit:

- historical moneylines;
- opening lines;
- prediction-time lines;
- closing lines;
- favorite/underdog status;
- CLV-derived information.

### Rankings and historical state

- ranking snapshots;
- record snapshots;
- division membership;
- title/championship status;
- age at event;
- experience at event.

## Source qualification

The previously identified GitHub MMA/UFC projects are best treated as candidate inputs, not automatically as canonical truth.

Before choosing a fighter-data source, qualify:

- schema;
- historical depth;
- update mechanism;
- upstream source;
- license;
- fighter identity stability;
- event identity stability;
- missingness;
- duplicate behavior;
- corrections policy;
- freshness;
- whether consuming the upstream source directly is preferable.

The system should support multiple external identities per canonical fighter rather than coupling MMAPicks to one provider.

---

# 4. Expansion Three: Transcript Recovery Engine

## Goal

Recover exact analyst predictions directly from historical YouTube breakdown videos when structured source data is missing, incomplete, or needs verification.

This does **not** require recreating NotebookLM.

The purpose-built workflow is:

```text
YouTube URL
    ↓
YouTube audio downloader
    ↓
video_id.mp3
    ↓
Whisper
    ↓
Timestamped transcript
    ↓
Extraction AI
    ↓
STRICT structured picks
    ↓
Fight/fighter resolver
    ↓
Gate 6 ingestion boundary
    ↓
MMAPicks DB
```

The extraction AI is not intended to freely chat with the transcript.

Its task is narrowly defined:

> Read this transcript and extract every actual fight prediction the analyst makes. Do not infer picks. Cite the exact transcript evidence.

## Timestamped transcripts

Whisper output should preserve timestamps.

Instead of storing only:

```text
I think Dustin wins this one...
```

retain evidence in a form such as:

```text
[00:42:13 - 00:42:21]
I think Dustin wins this one. I'm about 65 percent confident
and I think he gets it done by decision.
```

This enables direct evidence linking from a normalized prediction back to the exact moment in the source video.

## Strict extraction schema

The extraction model should return rigid structured output.

Example:

```json
{
  "picks": [
    {
      "fighter_a": "Dustin Poirier",
      "fighter_b": "Justin Gaethje",
      "picked_fighter": "Dustin Poirier",
      "confidence": 65,
      "predicted_method": "decision",
      "evidence": {
        "start_seconds": 2533,
        "end_seconds": 2541,
        "text": "I think Dustin wins this one..."
      }
    }
  ]
}
```

The AI output is only a candidate extraction.

Normal application code performs the final validation.

## Deterministic validation after extraction

Before a transcript-derived pick can reach canonical MMAPicks data, normal code should:

- resolve fighter names against the fighter corpus;
- resolve the bout against the event;
- verify the selected fighter belongs to the resolved fight;
- enforce confidence from `0` to `100`;
- reject ambiguous fighter identities;
- reject ambiguous fight identities;
- reject duplicates;
- reject conflicting picks;
- attach the YouTube video ID;
- attach the video URL;
- attach publication time;
- retain the Whisper transcript hash/version;
- retain the extraction model/version;
- route the record through the Gate 6 ingestion boundary.

The extraction model should not be allowed to bypass these checks.

## Two-pass extraction

A two-pass AI workflow should reduce hallucinated predictions.

### Pass One: Candidate extraction

Prompt objective:

> Extract every candidate prediction explicitly stated in the transcript.

### Pass Two: Evidence verification

Prompt objective:

> Given the extracted predictions and their cited transcript passages, verify that each prediction is explicitly supported. Reject anything inferred or ambiguous.

Only predictions that survive verification proceed to deterministic resolution.

## Long-video processing

Long transcripts do not require a full NotebookLM-style RAG product.

A practical batch process is:

```text
Timestamped transcript
    ↓
Overlapping transcript chunks
    ↓
Candidate extraction per chunk
    ↓
Merge candidates
    ↓
Deduplicate
    ↓
Load neighboring evidence
    ↓
Verification pass
    ↓
Identity resolution
```

## Local artifact storage

Every source video should have a durable working directory so expensive steps do not need to be repeated.

Example:

```text
data/
└── sources/
    └── youtube/
        └── QPAaIueT50E/
            ├── metadata.json
            ├── audio.mp3
            ├── transcript.json
            ├── transcript.txt
            └── extracted_picks.json
```

If extraction logic changes or the model makes a mistake, MMAPicks can rerun extraction against the saved transcript without downloading or transcribing the video again.

## Expected implementation difficulty

This is substantially simpler than creating a local NotebookLM equivalent.

A basic working pipeline should be a relatively contained implementation.

A reliable batch pipeline adds:

- resumability;
- artifact hashing;
- timestamps;
- strict structured extraction;
- verifier pass;
- fighter/fight identity resolution;
- provenance;
- tests;
- batch scheduling;
- failure recovery.

Once those pieces exist, processing hundreds or thousands of historical analyst videos becomes primarily a compute and elapsed-time problem rather than a new architectural problem.

---

# 5. How the Three Expansions Converge

The three programs should converge into the same canonical graph rather than maintain separate truths.

```text
                         HISTORICAL PICK SOURCES
                      MMA Prophecy / other sources
                                  │
                                  ▼
                         Analyst / Video Corpus
                                  │
                                  │
                                  ├───────────────┐
                                  │               │
                                  ▼               │
                              Predictions         │
                                  │               │
                                  ▼               │
Events ──────────────────────── Fights ◄──────────┘
                                  ▲
                                  │
                                  │
                         Fighter / Fight Corpus
                                  │
              ┌───────────────────┼───────────────────┐
              ▼                   ▼                   ▼
           Profiles          Round Stats          Rankings
           Records            Results              History
       Physical Attributes    Methods             Snapshots

                                  ▲
                                  │
                         Transcript Recovery
                                  │
                         YouTube → MP3 → Whisper
                                  │
                         Timestamped Transcript
                                  │
                          AI Pick Extraction
                                  │
                          Evidence Validation
                                  │
                         Identity Reconciliation
                                  │
                                  └──────────────► Predictions
```

---

# 6. Cross-Source Reconciliation

The structured historical corpus and transcript recovery engine should validate each other.

Conceptually:

```text
Structured source says pick exists
Transcript agrees
    → high-confidence historical record

Structured source says pick exists
Transcript disagrees
    → reconciliation review

Transcript finds explicit pick
Structured source has no record
    → new candidate historical pick

Structured source record exists
Source video is unavailable
    → preserve structured-source provenance only
```

MMA Prophecy therefore becomes an important evidence source, but not necessarily the sole historical truth.

Transcript recovery can potentially find predictions that an aggregator missed.

Similarly, source-level aggregates can detect transcript extraction gaps.

---

# 7. Unified Evidence Model

Every canonical prediction should ultimately be explainable.

For structured-source imports:

```text
Canonical Prediction
    ↓
Parsed Source Record
    ↓
Source Capture
    ↓
Source URL / Source Identifier / Content Hash
```

For transcript-derived imports:

```text
Canonical Prediction
    ↓
Extracted Pick
    ↓
Transcript Segment
    ↓
Transcript Version / Hash
    ↓
Audio Artifact
    ↓
YouTube Video / Metadata
```

An eventual transcript-derived record should be capable of retaining fields conceptually similar to:

```text
source_identifier
source_url
source_published_at
captured_at

video_id
transcript_hash
transcription_engine
transcription_model
extraction_model

evidence_start_seconds
evidence_end_seconds
evidence_text
```

The exact schema can evolve, but the evidence chain should remain intact.

---

# 8. Analytics Unlocked by the Unified Dataset

Once analyst predictions, market data, fighter history, and fight statistics share canonical identities, MMAPicks can answer substantially richer questions.

Examples:

> Which analysts outperform the market when picking wrestlers against strikers?

> Who is best at heavyweight underdogs?

> Which analyst has the best ROI on fighters with a four-inch or greater reach advantage?

> Does an analyst's 80%+ confidence actually correlate with better performance?

> Which analyst performs best against closing lines?

> Who identifies underdogs that later close as favorites?

> Who is best at predicting aging fighters?

> Which analysts understand women's divisions best?

> Who performs well on debuting UFC fighters?

> Does analyst performance change depending on fighter experience differential?

> Who is best at method predictions for fighters with high takedown rates?

The important distinction is temporal correctness.

The system should evaluate the state of the world **when the prediction was made**, rather than joining a historical prediction to today's fighter profile or today's record.

This enables:

- accuracy;
- ROI;
- units;
- CLV;
- confidence calibration;
- division performance;
- card-section performance;
- favorite/underdog performance;
- style-matchup analytics;
- fighter-attribute analytics;
- experience-differential analytics;
- age analytics;
- market-movement analytics;
- consensus;
- analyst rankings;
- model-ready historical datasets.

---

# 9. Public API Evolution

The current analyst-focused public API can eventually expand as canonical fighter and fight entities become available.

Possible future routes include:

```text
/fighters/{id}
/fighters/{id}/fights
/fighters/{id}/stats

/fights/{id}
/fights/{id}/picks
/fights/{id}/consensus

/analysts/{slug}/stats
/analysts/{slug}/performance

/events/{id}/predictions

/rankings/analysts
```

The public API should continue exposing derived and provenance-aware data without leaking private raw sportsbook data that existing contracts intentionally keep internal.

---

# 10. Suggested Post-Gate-7 Execution Order

The three expansions are connected, but they do not need to land simultaneously.

A practical sequence is:

## Phase A: Canonical Identity Expansion

Build the minimum fighter and fight identity layer needed to support large-scale reconciliation.

Deliver:

- canonical fighter IDs;
- aliases;
- external fighter identities;
- canonical event/fight identities;
- migration path from name-based references;
- deterministic resolver APIs.

This reduces ambiguity for both historical scraping and transcript extraction.

## Phase B: Structured Historical Backfill

Build the MMA Prophecy importer and other qualified structured-source adapters.

Deliver:

- source discovery;
- source capture;
- content hashing;
- parsed historical pick records;
- resumable checkpoints;
- reconciliation against source aggregate statistics;
- canonical import through Gate 6 boundaries.

This establishes a large initial historical corpus quickly.

## Phase C: Fighter and Fight Data Expansion

Qualify and import the broader fighter/statistical sources.

Deliver:

- fighter profiles;
- fight history;
- round statistics;
- historical records;
- ranking snapshots;
- other time-sensitive fighter snapshots;
- source identity and reconciliation.

## Phase D: Transcript Recovery Engine

Build:

```text
YouTube URL
    ↓
MP3
    ↓
Whisper
    ↓
Timestamped transcript
    ↓
AI candidate extraction
    ↓
AI evidence verification
    ↓
Fighter/fight resolution
    ↓
Gate 6 import
```

Use it first to:

- verify structured historical picks;
- recover picks missing from structured sources;
- extend coverage to analysts or videos not represented by an aggregator.

## Phase E: Cross-Source Reconciliation

Compare:

- structured source data;
- transcript-derived predictions;
- event/fight results;
- odds;
- source aggregate statistics.

Generate explicit reconciliation queues for disagreements instead of silently choosing one record.

## Phase F: Advanced Analytics and API Expansion

Once the data foundation is sufficiently complete:

- historical analyst rankings;
- consensus;
- fighter-context performance;
- CLV analysis;
- confidence calibration;
- style and attribute correlations;
- model-ready datasets;
- expanded public API.

---

# 11. Architectural Principle

The post-Gate-7 direction can be summarized as:

```text
Collect broadly.
Preserve raw evidence.
Normalize cautiously.
Resolve identities deterministically.
Record historical state.
Fail closed on ambiguity.
Keep provenance attached.
Reconcile independent sources.
Only then compute analytics.
```

The destination is not merely a larger picks tracker.

It is a historical MMA data layer that combines:

- analysts;
- predictions;
- confidence;
- source evidence;
- videos;
- transcripts;
- fighters;
- events;
- fights;
- statistics;
- odds;
- results;
- market movement;
- rankings;
- time-sensitive snapshots;
- derived analytics.

That common data layer is what allows MMAPicks to move from tracking picks to answering questions that require the complete historical context around those picks.

---

# Source Links Referenced in the Direction

[MMA Prophecy Leaderboard](https://www.mmaprophecy.com/leaderboard)

[Example MMA Prophecy Channel](https://mmaprophecy.com/channel/UCZD2qRU8J82XGdGdUWYneNQ)

[Example MMA Prophecy Video](https://mmaprophecy.com/video/QPAaIueT50E)

[Example MMA Prophecy Fight IQ Page](https://mmaprophecy.com/fight/17139)
