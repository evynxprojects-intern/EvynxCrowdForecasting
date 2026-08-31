# Evynx Crowd Forecasting Engine — Final Model

Predicts how crowded a tour package will be on a given date, and recommends
either a quieter **package** or a quieter **date**.

---

## Quick start

```python
from crowd_engine import Engine

e = Engine()
e.recommend('TPQQQXBJN1', '2026-11-08')
```

Or as a service:

```bash
pip install flask
python app.py                 # dev
gunicorn app:app              # production
```

---

## Files

```
crowd_engine.py     the engine
app.py              REST wrapper
test_engine.py      17 regression tests
demo.py             worked examples

places.json         617 locations, visitor counts, seasons, classes
seasonal.json       city / state / region monthly curves
tours.json          632 packages with parsed routes
festivals.json      31 verified festival windows, 2026-27
holidays.json       public holidays
```

No external services. Everything runs from local JSON.

---

## The two-track design

Swapping one package for another requires **both packages measured and in the
same measurement class**. That holds for 290 of 632 packages. For the rest we
fall back to a date suggestion, which works for every package because it only
needs the seasonal model.

```
                    package + date
                          |
                    crowd forecast
                          |
              is it busy enough to act?
                    no -> say so, stop
                          |
                     yes, what intent?
                          |
      pilgrimage ---------+--------- everything else
           |                              |
     logistics advice          can we swap this package?
     (never sent away)                    |
                              yes -> quieter package
                              no  -> quieter date
                                     (group tours: next departure)
```

---

## Three indices — never mixed

| Index | Built from | Used for |
|---|---|---|
| `seasonal_index` | Layers 1-3, month level | intermediate |
| `recommendation_index` | seasonal + verified festival | **all ranking and triggering** |
| `display_index` | recommendation + weekend + holiday | shown to the user |

Festival windows are date-verified, so they drive decisions. Weekend and holiday
multipliers are unvalidated estimates, so they explain but never trigger.

---

## Rules the engine enforces

- **Never compare across measurement classes.** ASI counts monument tickets;
  states count district visits. The same place measured both ways differs by
  2.3× at Konark and 147× at Champaner-Pavagadh. A conversion was attempted and
  failed (R² = 0.005), so cross-class comparison is blocked.
- **Never compare across regions.** Cross-region ranking measured 24% accuracy,
  worse than random.
- **ESTIMATE-class places never make a package swappable.** 284 locations have
  no government figure; they can be displayed but not ranked.
- **Per-night dates.** A festival on day 3 is checked against day 3's calendar
  date, not the departure date. Kullu Dussehra runs 20–26 October: departing
  10 October misses it, departing 18 October hits it.
- **Best Seasons is a hard gate.** An alternate date is never offered if any
  stop falls outside its own season window. Manali scores quiet in December
  because the season is over, not because it is a good time to go.
- **Group tours never receive an arbitrary date.** Fixed departures cannot be
  moved, so they get the next-departure message instead.
- **Peak stop is named only at city tier.** Naming a specific stop is a strong
  claim; it is not made off a state-level estimate.

---

## Coverage

```
places               617
places measured      333    (54%)
tours                632
swappable tours      290    (46%)
stops resolved       95.2%
```

Swappable tours by region:

```
western-ghats       97      north-india        29
western-himalayas   90      south-india        17
western-india       31      central-india      14
east-india          10      eastern-himalayas   0
```

Eastern-himalayas has no measured locations — Sikkim and the Northeast publish
only state totals.

Recommendation types across all 632 tours on a peak date (8 Nov 2026, Diwali):

```
none                 444    not busy enough to act on
alternate_date       100
alternate_package     49
logistics             22    pilgrimage packages
group_departure       11
none_available         3    already the quietest option
unavailable            3    route could not be resolved
```

---

## Accuracy

| Capability | Result | Basis |
|---|---|---|
| Seasonal (when to visit) | **92.8%** | independent test against human-written Best Seasons, never seen in training; random baseline 53.6% |
| ASI monument seasonal | 75% | real government footfall |
| Pipeline reproducibility | 4,044 / 4,044 exact | rebuilt from documented formula |
| Cross-place comparison | 24% | worse than random — this is why swaps are class-restricted |

---

## Tuning constants

```python
FESTIVAL_FLOOR    = 80     a festival crowds a place regardless of usual level
FESTIVAL_ADD      = 35     added on top for already-busy places
WEEKEND_MULT      = 1.08   a busy place stays busy midweek
HOLIDAY_MULT      = 1.10
NATURE_FEST_SENS  = 0.35   festivals fill temples, not beaches
HIGH_THRESHOLD    = 65     ~30% of packages trigger a recommendation
SWAP_MARGIN       = 8      alternative must be meaningfully quieter
DATE_MARGIN       = 5
```

These are chosen values, not fitted ones. Validating them needs real busyness
data across many places and dates, which exists for only 9.7% of the dataset.

---

## Known limits

- **342 packages cannot be swapped** because at least one stop has no
  government visitor count. They fall back to date suggestions.
- **Cross-class comparison is impossible**, not merely unimplemented. The ratio
  between measurement types is a property of each individual place — whether
  its visitors pass a ticket gate — and cannot be inferred from the source.
- **High-altitude Himalayan sites peak a month early.** Leh, Sonamarg and
  Tso Moriri predict May where the human window says June–September. The cold
  gate opens too early at altitude.
- **Festival dates are luni-solar** and must be refreshed annually.
  `festivals.json` currently covers July 2026 – February 2027.
- **3 tours have unresolvable routes** and return `unavailable`.

---

## Refreshing

**Annually** — update `festivals.json` with next year's luni-solar dates.

**When new visitor data arrives** — add rows to `places.json` with `cls` set to
`DESTINATION`, `AREA` or `PARTIAL`. Packages become swappable automatically once
all their stops are measured and share one class.

**When the catalogue changes** — regenerate `tours.json` from the tours export.

The long-term fix for the 342 unswappable packages is Evynx's own booking data.
Actual departures per package per date would give one consistent measurement
across every package, removing the class problem entirely.
