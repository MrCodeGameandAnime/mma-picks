Exactly. That is probably one of the **most valuable products hidden inside the dataset**.

Once the historical corpus is deep enough, we can stop asking only:

> “What did 200 YouTubers pick?”

and start asking:

> **“What do the analysts who have historically been right in situations like this pick?”**

Those are very different signals.

A fight could ultimately have a consensus object something like:

```text
FIGHT: Fighter A vs Fighter B
Coverage: 213 analysts

ALL ANALYSTS
─────────────────────────────
Fighter A       138    64.8%
Fighter B        75    35.2%

METHOD CONSENSUS FOR FIGHTER A
KO/TKO           83    60.1%
Submission       28    20.3%
Decision         27    19.6%

TOP HISTORICAL PERFORMERS
─────────────────────────────
Qualified analysts: 34

Fighter A        27    79.4%
Fighter B         7    20.6%

Top-performer method:
KO/TKO           19    70.4%
Submission        4    14.8%
Decision          4    14.8%

OVERLAP
─────────────────────────────
All analysts agree A:          64.8%
Top analysts agree A:          79.4%

Strong shared consensus:
Fighter A

Distinctive elite signal:
Top analysts are +14.6 pts
more bullish on Fighter A.

Most common elite method:
Fighter A by KO/TKO
```

And then we go further than simply “top analysts.”

We can create **qualified cohorts**.

For example:

```text
Overall historical winners
Best ROI analysts
Best accuracy analysts
Best CLV analysts

Heavyweight specialists
Women's MMA specialists
Underdog specialists
Favorite specialists

High-confidence specialists
Main-card specialists
Prelim specialists

KO prediction specialists
Submission specialists
Decision specialists

Analysts strong on Fighter A's style
Analysts strong against Fighter B's style

Analysts with 100+ graded picks
Analysts with 250+ graded picks
Analysts profitable over multiple years
```

Then for the exact same matchup, MMAPicks could show:

```text
ALL 213 ANALYSTS
A 65% / B 35%

TOP 50 BY LONG-TERM ROI
A 74% / B 26%

TOP 25 BY ACCURACY, MIN 200 PICKS
A 80% / B 20%

BEST UNDERDOG ANALYSTS
A 47% / B 53%

BEST WELTERWEIGHT ANALYSTS
A 84% / B 16%

BEST METHOD PREDICTORS
A KO 68%
A DEC 18%
A SUB 14%
```

Now you suddenly see something much more interesting than a generic consensus.

Maybe **everyone** likes Fighter A, but the historically good underdog analysts are unusually concentrated on Fighter B.

That disagreement itself becomes a signal.

### The overlap/difference view could be killer

For every fight:

**Consensus**
What everybody thinks.

**Qualified consensus**
What historically successful analysts think.

**Overlap**
Where both populations strongly agree.

**Divergence**
Where successful analysts materially disagree with the crowd.

**Method consensus**
How analysts think the fight ends.

**Confidence consensus**
Average/median declared confidence.

**Market comparison**
Whether analyst consensus agrees with the betting market.

You could eventually surface something like:

> **Consensus Edge**
>
> 73% of all analysts pick Fighter A.
> 88% of historically profitable analysts pick Fighter A.
> 76% of qualified method predictors expect KO/TKO.
> Market implied probability: 61%.
>
> **High agreement, positive analyst-market divergence.**

Or:

> **Contrarian Elite Signal**
>
> 68% of all analysts pick Fighter A.
> Only 39% of top-ROI analysts pick Fighter A.
> Top performers favor Fighter B 61%.
>
> **Broad consensus and historically successful consensus disagree.**

That second category might be **way more interesting** than simple majority picks.

And I would absolutely keep the raw counts beside percentages.

`8/10 = 80%` is not the same thing as `160/200 = 80%`.

So every aggregate should carry:

```text
pick_count
eligible_analyst_count
coverage_rate
sample_size_of_each_analyst
historical_accuracy
historical_roi
historical_clv
relevant-subgroup sample
```

Then we can build weighting later.

A naïve consensus:

```text
one analyst = one vote
```

A smarter consensus could eventually be:

```text
analyst vote
× reliability
× historical sample confidence
× relevant subgroup performance
× recency
```

But I would preserve both.

**Raw consensus** is valuable because it represents the crowd.

**Weighted/qualified consensus** is valuable because it represents historical skill.

Never hide one behind the other.

And once we have method picks too, your example becomes completely realistic:

```text
Fighter A selected by 71% of analysts

Among Fighter A picks:
60% KO/TKO
20% Submission
20% Decision
```

Then compare that against elite predictors:

```text
Top method predictors selecting Fighter A:

78% KO/TKO
 8% Submission
14% Decision
```

That tells you the majority thinks A wins, but the people who have historically been best at predicting **how** fights finish are even more concentrated on the knockout.

That's a legitimately useful analytical layer.

At scale the page practically writes itself:

```text
                    Crowd       Top Analysts
Fighter A             67%           81%
Fighter B             33%           19%

A by KO                42%           61%
A by SUB               11%            8%
A by DEC               14%           12%

B by KO                 8%            5%
B by SUB                7%            3%
B by DEC               18%           11%
```

Then:

**Shared Pick:** Fighter A
**Shared Method:** KO/TKO
**Elite Difference:** +14 pts toward Fighter A
**Strongest Distinction:** elite analysts disproportionately favor A by KO

And with enough history, we could also answer:

> “These 17 analysts all independently picked Fighter A, and when at least 14 of these 17 have agreed historically, that consensus has gone 63-21 with +18.4u.”

Now we're no longer merely tracking analysts.

We're finding **persistent combinations of analyst agreement that themselves have historical performance**.

That could become one of MMAPicks' signature features.
