# Measuring School Facilities from Imagery

Pipeline for the take-home task: given `data/schools_sample.csv`, resolve each
school's real campus location, pull a satellite image, and use a vision model
to measure rooftop solar, portable classrooms, perimeter fencing, and athletic
facilities, each with a confidence score.

## How it works

1. **Locate the campus** (`src/geolocate.py`). The CCD lat/lon is sometimes a
   mailing address or district office, not the campus. We query OpenStreetMap's
   Overpass API for a school-tagged feature near that point whose name matches,
   and use its real footprint if found. If nothing matches, we fall back to the
   CCD point with a default crop size and flag it as unconfirmed
   (`location_source` / `location_confidence` columns).
2. **Fetch imagery** (`src/imagery.py`). USGS NAIP aerial imagery via Esri's
   public ImageServer REST API — free, no API key, ~0.6m/pixel, covers the
   whole continental US. We also look up the acquisition date of the specific
   tile covering each school.
3. **Extract measurements** (`src/vision_extract.py`). The image (plus its
   known scale and whether the campus boundary was confirmed) goes to
   OpenAI's gpt-5.4, which returns structured JSON for all four required
   attributes with a confidence per field. (gpt-4o was tried first and
   works fine; gpt-5.4 tested faster-or-equal per call, cheaper per token,
   and visibly better-calibrated on the same images — see `src/config.py`
   for the head-to-head numbers, including why the more "premium" gpt-5.5 /
   gpt-5.5-pro turned out to be the wrong choice for a repeated batch call.)
   One field, `hard_courts_count`, gets asked twice more independently and
   resolved to the median of the three answers, since it's shown real
   instability even at temperature 0 — see Known limitations for what that
   did and didn't fix.
4. **Write output** (`src/pipeline.py`). One row per school to
   `output/measurements.csv`.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
```

Edit `.env` and set `OPENAI_API_KEY`. This costs real (small) money — about
$0.26 total for all 25 schools plus the validation subset (hard courts
costs extra: it resamples itself 2 more times per school, see Known
limitations), since OpenAI doesn't have a meaningful free tier for vision.

## Run

```bash
python -u src/pipeline.py
```

(`-u` just keeps progress lines appearing in real time if you redirect
output to a file or pipe it; harmless otherwise.)

Takes a few minutes for 25 schools, most of it deliberate, polite delays
between API calls (see `OPENAI_DELAY_SECONDS` / `OVERPASS_DELAY_SECONDS` in
`src/config.py`), not compute. Writes `output/measurements.csv` and caches
every fetched image in `output/images/{school_id}.png` so you can visually
spot-check any row.

## Validation

Two passes, of different strength — see `memo.pdf` for the full writeup.

**Location, by hand (the stronger one).** `validation/manual_spotcheck.md`
has a clickable Google Maps satellite link for every one of the 25 CCD
coordinates. All 25 were checked this way (not by an AI): 24/25 land on the
correct, identifiable campus. The single exception and two naming quirks
are documented in the memo's Failures section.

**Facility attributes, by a second model.**

```bash
python validation/second_opinion.py
```

Re-analyzes a hand-picked subset of 8 schools (chosen to span rural/urban,
different school levels, and both location-resolution outcomes) with
`gpt-4o` — the former primary model — using the identical prompt, and
reports per-field agreement with the gpt-5.4-based pipeline output. This
doubles as a before/after check on the gpt-4o → gpt-5.4 switch. It's also a
weaker independence guarantee than a cross-vendor check would be —
same-provider models can share correlated blind spots — and the memo says
so plainly rather than overselling it.

## Optional part: tracking one measure over time

The brief's optional extra: pick one measure, show how it changes across
two or more dates, for as many schools as feasible. We picked rooftop
solar — the main pipeline already turned up a few schools where solar
looked like it might have appeared recently, so this follows up on that
directly rather than picking an attribute at random.

```bash
python optional/solar_over_time.py
```

Runs all 25 schools, comparing a ~2016 snapshot against the most recent one
available. Both dates come from **Esri Wayback Imagery** (free, keyless,
dated satellite snapshots back to 2014) — not NAIP, which only serves its
current mosaic per area (confirmed directly: querying it for historical
tiles at a fixed point returns just one, regardless of how the query is
framed). Using Wayback for both dates keeps the comparison apples-to-apples
instead of mixing providers. Writes `optional/solar_over_time.csv` and
caches every fetched image in `optional/images/`.

Real result: 2 of 25 schools (Wells Middle, Spring Lake Heights) show solar
genuinely appearing between the two dates. Running this also **overturned
two of our own earlier claims** — see the memo's Failures section for
specifics; the short version is that a plausible-looking screenshot read
turned out to be wrong for one school, and confirmed for another that a
"solar not detected" result was a real miss rather than a timing gap.
That correction is arguably the most useful thing this script produced.

**A known limitation of this script specifically** (not the main pipeline):
it fetches a fixed ~350m crop around each school's point, rather than
reusing the main pipeline's actual campus-polygon extent. For at least one
large campus (Kofa HS) this crop landed on a real part of the school but
missed the specific building with its solar array — confirmed true positive
in the main pipeline and by direct screenshot, read as a false negative
here. Named plainly rather than quietly re-scoped away.

## Spatial index, terrain, and routing (added after the take-home)

Three modules that sit beside the facility pipeline and do not touch it:
`output/measurements.csv` is only ever read. Tests run offline (`python -m pytest`)
on small synthetic fixtures; nothing in `tests/` calls a live API.

### Spatial index (`src/spatial_index.py`)

Campus footprints and facilities as GeoJSON, indexed with a Shapely `STRtree`.
`CampusIndex` answers `schools_within(lat, lon, radius_km)`, `nearest_school(lat, lon)`,
`facilities_in_campus(school_id)` and `campus_containing(lat, lon)`. The tree works
on raw lon/lat envelopes, so it only picks candidates; each one is then re-checked
with a distance in meters in a local flat frame centered on the query point, which
keeps results exact at any latitude. (A test comparing against a linear scan caught
exactly this kind of mismatch during development: a candidate box using a slightly
different meters-per-degree constant than the metric dropped a campus at 14 km.)

```bash
python src/spatial_index.py                 # writes data/schools_points.geojson, prints sample queries
python benchmarks/bench_spatial_index.py    # index vs linear scan
```

Benchmark (synthetic random 100-800 m square campuses over the continental US,
25 km radius, mean per query, Python 3.13 on one laptop, one run; the script also
asserts index and scan return identical results on every query):

| N campuses | within: Python scan | within: numpy bbox scan | within: index | nearest: Python scan | nearest: index |
|---|---|---|---|---|---|
| 1,000 | 6.34 ms | 0.012 ms | 0.015 ms | 6.31 ms | 0.042 ms |
| 10,000 | 64.2 ms | 0.079 ms | 0.057 ms | 63.5 ms | 0.062 ms |
| 50,000 | 312 ms | 0.244 ms | 0.162 ms | 309 ms | 0.075 ms |

Read this honestly: the big speedups (400-4000x) are against a deliberately naive
baseline that does an exact distance per geometry in a Python loop. Against a
vectorized numpy bounding-box prefilter, which is the fairer comparison, the index
is roughly even at 1,000 campuses (0.8x) and about 1.4-1.5x faster at 10-50k. The
index's real advantage is that its cost barely grows with N.

Limitations: the only real campus data in the repo is the 25 resolved points in
`measurements.csv`; the pipeline does not persist campus polygons or facility
locations (the vision model returns counts, not coordinates), so polygon and
"facility inside campus" queries were exercised only on synthetic fixtures and
random data, never on real footprints. Distances use a local flat-earth frame, fine at
the tens-of-kilometers scale here, not for continental distances.

### Composite DEM (`src/terrain.py`)

Fetches USGS 3DEP bare-earth elevation per campus through the same Esri ImageServer
REST pattern as NAIP (`exportImage`, float32 GeoTIFF, decoded with Pillow, so no
rasterio/GDAL dependency). Each campus extent is split into small tiles
(`DEM_MAX_TILE_PIXELS`, 32 px at 10 m), fetched separately, and mosaicked back
into one array, with a one-pixel overlap between neighbors that is averaged. Slope
comes from central differences on the composite. Output goes to a new file,
`output/terrain.csv`: min/max/range/mean elevation, mean and max slope, plus tile
count and no-data fraction.

```bash
python src/terrain.py
```

**Ran live:** all 25 campuses fetched successfully (4 tiles each, 0% no-data, about
48 s total). Elevation range across a campus extent runs from 2.2 m (Thompson
Middle) to 89.8 m (Pittsburgh Brashear HS, also the steepest at 14.0 degrees mean slope).

Limitations: the extent is the same default 500 m square the imagery step uses when
no campus polygon is known (not the real campus boundary), at an effective 10 m
pixel (50x50 px), so the "mean slope" is a coarse figure that smooths out
building pads, retaining walls and berms, and the max slope is a single-pixel extreme that I did not inspect
(Beverly Hills reports a 43 degree max on a 2.9 degree mean, which could be real terrain or a data artifact).
Small tiles are used on purpose so mosaicking is exercised on every campus, even though
one request would have covered each. Elevation is bare-earth, with no buildings or vegetation.

### Terrain-aware routing (`src/routing.py`)

Grid A* (`heapq`, 8-connected) over a cost raster derived from DEM slope. Each cell
gets a time rate (speed decays exponentially with slope, impassable above 25 degrees)
and a risk rate (`(slope / 25)^2`); the cost of a move is a weighted sum of time and
risk, `w_time * time + w_risk * risk`. The heuristic is octile distance times
`w_time` times the cheapest time-per-meter on the grid, which is admissible and
consistent. `compare_weightings` routes under several weightings and flags routes
that are Pareto-dominated on (time, risk).

```bash
python src/routing.py [school_id]    # live DEM, SW corner to NE corner, three weightings
```

Tests use known-answer grids: a flat grid (diagonal and straight-line distance), a
wall with one gap (hand-computed detour length), a gentle hump where the time-optimal
route crosses it and the risk-averse route goes around (expected time, risk and distance
worked out by hand), unreachable goals, the slope cutoff, and 40 random terrains where A*
cost must equal plain Dijkstra's. Live example (SW to NE corner of a 50x50, 10 m DEM,
one run, weights `w_time:w_risk`):

| Campus | Weights | Distance | Time | Risk | Max slope |
|---|---|---|---|---|---|
| Wedowee Middle | 1:0 | 727 m | 721 s | 28.0 | 13.0 deg |
| | 1:50 | 828 m | 768 s | 19.4 | 10.1 deg |
| | 0:1 | 914 m | 827 s | 19.0 | 10.1 deg |
| Pittsburgh Brashear | 1:0 | 954 m | 1575 s | 162.5 | 24.6 deg |
| | 1:50 | 1044 m | 1621 s | 154.8 | 24.6 deg |
| | 0:1 | 1072 m | 1644 s | 154.5 | 24.6 deg |

None of those routes is dominated: each step trades a little more time for a little
less risk. At Pittsburgh the trade is small because the steep terrain leaves
little room to avoid steep cells.

Limitations: the speed and risk functions are illustrative and not calibrated to
any real vehicle, drone or walking speed; the cost raster is per cell, so uphill
and downhill cost the same; it ignores buildings, fences and land cover (the live
routes cut across whatever the DEM says is passable, which on a real campus includes
buildings); diagonal moves may cut corners between blocked cells; and the live runs
use the 10 m DEM over a 500 m extent, which is a toy scale for path planning.

## Output schema (`output/measurements.csv`)

| Column | Meaning |
|---|---|
| `solar_present`, `solar_area_m2`, `solar_confidence` | Rooftop solar (A) |
| `portables_count`, `portables_confidence` | Portable classrooms (B) |
| `fence_status`, `fence_type`, `fence_confidence` | Perimeter fencing (C) |
| `track_present`, `track_confidence` | Running track (D) |
| `sports_fields_count`, `sports_fields_confidence` | Full-size fields (D) |
| `hard_courts_count`, `hard_courts_confidence` | Hard courts (D) |
| `pool_present`, `pool_confidence` | Pool (D) |
| `imagery_date`, `imagery_source`, `meters_per_pixel` | Vintage/provenance of the image used |
| `location_lat`, `location_lon`, `location_source`, `location_confidence` | Where we decided the campus actually is, and how sure we are |
| `vision_model` | Which model produced the row |
| `notes` | Free-text caveats the model surfaced (tree cover, cropped campus, ambiguous cases, etc.) |

## Known limitations

See `memo.pdf` for the full validation methodology, error rates, failure
modes, and cost-at-scale estimate. Short version: hard courts is the one
remaining weak spot, and it took three real attempts to understand why.
Two models disagreed by 3-4x on the same multi-court complex (9 courts vs.
2, on one school) — a segmentation-granularity disagreement, not a
calibration problem. Replacing the vague "count separate painted surfaces"
rule with a mechanical one (count paved surfaces separated by a visible
gap, not internal lines too fine to resolve at this scale) shrank that
same disagreement to 3-vs-1 and moved aggregate agreement 38%→50%. A
second attempt — excluding one borderline extra court — made things worse
(agreement fell to 25%, confidence didn't follow) and was reverted rather
than shipped. A third — resampling the count 3x per school and taking the
median, to catch the model being inconsistent with itself — changed
nothing (agreement held at exactly 50%), which is itself informative: the
remaining gap is two models genuinely disagreeing on ambiguous imagery,
not one model being unstable. Kept anyway, since it grounds hard-courts
confidence in measured cross-sample agreement rather than self-report.
Portables had a different problem — models weren't disagreeing on the
count, they were disagreeing on whether a single ambiguous structure was
a classroom or a shed — fixed with an explicit rule that multiplicity is
the signal (portables come in matching sets); agreement rose 38%→75%.
Checked directly: the most dramatic swing (Adena Elementary, 18→0
portables) holds up against its actual image — the row of small
rectangles the old prompt was likely counting is a bus lot. Along the
way, `validation/second_opinion.py` was found to never pin the
second-opinion model's temperature to 0 like the primary pipeline does —
fixed, since otherwise some of what looks like model disagreement is just
that model being inconsistent with itself. Perimeter fencing remains the
most under-confident field (0.46 average confidence) despite good
agreement (0.75) — appropriately humble rather than weak.

**One more finding, from re-running everything fresh right before
submission**, both the main pipeline and `second_opinion.py`, to
double-check reproducibility: temperature 0 lowers this model's run-to-run
variance but does not eliminate it. Adena's portables count came back as
18 on this clean re-run, not the validated 0 — re-checking the freshly
fetched image confirmed 0 (the bus lot) is still correct, so this was the
model contradicting itself, not a wrong fix. The second-opinion agreement
numbers shifted too (fencing and portables both moved 0.75→0.875 on this
re-run) — a plausible-looking improvement I did not adopt, since a single
noisy re-sample isn't grounds to swap in a nicer number. `output/measurements.csv`
and `validation/second_opinion_results.csv` in this repo are the original,
manually spot-checked run, not the fresh one — this note exists precisely
so that distinction isn't silently lost.
Pittsburgh Brashear HS's CCD
point is the one confirmed location miss (nearest Google Maps label there is
a different school — a manual screenshot check couldn't tell whether that's a
wrong coordinate or a genuinely adjacent/shared campus, left open rather than
guessed at); a distinct bug (also caught by manual
screenshot review) had schools resolved to a confirmed OSM point still
missing real facilities sitting just outside the default crop —
`DEFAULT_CROP_METERS` was widened from 350 to 500 to fix this, verified on
the case that surfaced it (Coleman HS); the OpenStreetMap Overpass API this
pipeline depends on for campus-boundary resolution was fully unreachable
for over an hour during development, and a local network drop failed one
run outright mid-project — both confirmed, neither a code bug; and solar
specifically needed a proper before/after check to sort out (see Optional
part below) — an earlier claim that three schools (Bel Air, Bertha, Wells
Middle) showed a simple imagery-vintage gap held up for only one of them
(Wells Middle) once actually tested against historical imagery. Bertha
shows no solar at either date, and Bel Air's panels were already visible
in 2016 — a real detection miss, not a vintage gap. A fourth school,
Spring Lake Heights, turned up as a genuine vintage-gap case not in the
original claim at all.

## Tooling disclosure

Built with Claude Code (Anthropic) as a coding assistant, under my
direction throughout — I made the calls on model choice, what to fix,
when to stop iterating, and did the manual validation myself; Claude
Code implemented it. Facility measurements are produced by OpenAI's
gpt-5.4; the validation cross-check
uses gpt-4o, the former primary model. Location resolution uses
OpenStreetMap (Overpass API); imagery is USGS NAIP via Esri's ArcGIS
ImageServer. Total usage: about $0.26 in OpenAI API calls for the full run
plus validation, covered by an existing credit balance already on the
account (no fresh payment made) — everything else used free public data
sources.
