# Manual spot-check checklist

Click each link (satellite view, zoomed to the campus), compare against what
the pipeline claimed, and jot your own read in the "Your read" column -- even
a quick one. That's what turns this into real hand-labeled ground truth
rather than a second AI's opinion on a different image.

Pipeline's claim (solar / portables / fence / track / fields / courts / pool)
is pulled from `output/measurements.csv` at the time this file was generated.

**Filled in below.** These are the actual results: you captured each
screenshot in Google Maps, sent it over, and I read it and compared it
against `output/measurements.csv`. Location was checked this way for all 25
schools. Facility-level details (solar, track, etc.) were only checked
opportunistically, when something in a screenshot stood out enough to
mention -- marked "not checked" everywhere else, rather than silently assumed
correct. This table was cross-checked against the raw conversation log
before being written here, so it reflects what was actually found, not a
memory reconstruction.

| school_id | School | Google Maps | Pipeline claim | Your read |
|---|---|---|---|---|
| 010282001124 | Wedowee Middle School (Wedowee, AL) | [open](https://www.google.com/maps/@33.313157,-85.495877,18z/data=!3m1!1e3) | solar:N portables:0 fence:none track:N fields:0 courts:1 pool:N | Location: correct campus, but the pin shows "Wedowee Elementary," the street is "Middle School Rd.," and OSM separately labels the same point "Wedowee High School" -- likely one shared multi-grade site, not confirmed either way. Facility: not checked. |
| 040963000996 | Kofa High School (Yuma, AZ) | [open](https://www.google.com/maps/@32.6743,-114.636,18z/data=!3m1!1e3) | solar:Y portables:0 fence:partial track:Y fields:3 courts:5 pool:N | Location: correct (exact match). Facility: solar -- confirmed correct. |
| 060483000471 | Beverly Hills High (Beverly Hills, CA) | [open](https://www.google.com/maps/@34.061692,-118.412181,18z/data=!3m1!1e3) | solar:N portables:0 fence:partial track:Y fields:1 courts:5 pool:N | Location: correct (exact match). Facility: not checked from this screenshot. |
| 061734009378 | Cerra Vista Elementary (Hollister, CA) | [open](https://www.google.com/maps/@36.829411,-121.372331,18z/data=!3m1!1e3) | solar:Y portables:3 fence:partial track:N fields:3 courts:2 pool:N | Location: correct (exact match). Facility: solar -- confirmed correct. |
| 060001909278 | Wells Middle (Dublin, CA) | [open](https://www.google.com/maps/@37.711839,-121.918954,18z/data=!3m1!1e3) | solar:N portables:0 fence:partial track:N fields:2 courts:1 pool:N | Location: correct (exact match). Facility: solar looked possible at the time from the screenshot; later confirmed via the Wayback check (see optional/) as a genuine 2016->2026 gain. |
| 130333001308 | Lincoln County Elementary School (Lincolnton, GA) | [open](https://www.google.com/maps/@33.796652,-82.49178,18z/data=!3m1!1e3) | solar:N portables:0 fence:partial track:N fields:0 courts:1 pool:N | Location: correct (exact match). Facility: not checked. |
| 160264000465 | Claude A Wilcox Elementary (Pocatello, ID) | [open](https://www.google.com/maps/@42.898474,-112.47438,18z/data=!3m1!1e3) | solar:N portables:0 fence:partial track:N fields:0 courts:1 pool:N | Location: correct (exact match). Facility: not checked. |
| 160000100084 | Priest River Lamanna High (Priest River, ID) | [open](https://www.google.com/maps/@48.189478,-116.917391,18z/data=!3m1!1e3) | solar:N portables:0 fence:partial track:Y fields:2 courts:0 pool:N | Location: correct (exact match). Facility: track -- confirmed correct. |
| 180283000341 | Zionsville Community High School (Zionsville, IN) | [open](https://www.google.com/maps/@39.9611,-86.274,18z/data=!3m1!1e3) | solar:N portables:0 fence:partial track:Y fields:1 courts:0 pool:N | Location: correct (exact match). Facility: not checked from this screenshot. |
| 240039000683 | Bel Air High (Bel Air, MD) | [open](https://www.google.com/maps/@39.531077,-76.348008,18z/data=!3m1!1e3) | solar:N portables:0 fence:partial track:Y fields:5 courts:4 pool:N | Location: correct (exact match). Facility: solar clearly visible on the screenshot, pipeline said none -- flagged as a miss. Later confirmed via Wayback that panels were already up in 2016, so this is a real detection miss, not a timing gap. |
| 263039006679 | Thompson Middle School (Saginaw, MI) | [open](https://www.google.com/maps/@43.4324,-83.986401,18z/data=!3m1!1e3) | solar:N portables:0 fence:partial track:N fields:1 courts:0 pool:N | Location: correct (exact match). Facility: not checked. |
| 270543000204 | Bertha Secondary (Bertha, MN) | [open](https://www.google.com/maps/@46.263877,-95.062093,18z/data=!3m1!1e3) | solar:N portables:0 fence:partial track:N fields:2 courts:0 pool:N | Location: correct campus, labeled "Bertha-Hewitt Public School" on Google. Facility: sports fields (2 diamonds) -- confirmed correct. Solar was initially read as present from this screenshot, but that read was later retracted -- the Wayback check (see optional/) showed no solar at either date, likely a non-solar roof pattern misread the first time. |
| 330246000063 | Rundlett Middle School (Concord, NH) | [open](https://www.google.com/maps/@43.189478,-71.543379,18z/data=!3m1!1e3) | solar:N portables:0 fence:partial track:N fields:2 courts:0 pool:N | Location: correct (exact match; the map pin covered the on-screen label in this particular screenshot). Facility: not checked. |
| 341560004108 | Spring Lake Heights Elementary (Spring Lake Heights, NJ) | [open](https://www.google.com/maps/@40.154128,-74.036948,18z/data=!3m1!1e3) | solar:Y portables:0 fence:partial track:N fields:2 courts:2 pool:N | Location: correct (exact match). Facility: not checked from this screenshot -- its confirmed solar gain came from the separate Wayback run (see optional/), not this check. |
| 360008802312 | PS 78 Anne Hutchinson (Bronx, NY) | [open](https://www.google.com/maps/@40.8786,-73.8507,18z/data=!3m1!1e3) | solar:N portables:0 fence:partial track:N fields:0 courts:1 pool:N | Location: correct (exact match). Facility: not checked. |
| 390494903613 | Adena Elementary School (Frankfort, OH) | [open](https://www.google.com/maps/@39.41589,-83.193859,18z/data=!3m1!1e3) | solar:N portables:0 fence:partial track:N fields:1 courts:0 pool:N | Location: correct campus, combined/district naming. Facility: not checked (the high portables count here was not independently verified against the screenshot). |
| 390458502363 | Ridgeview Elementary School (Ashtabula, OH) | [open](https://www.google.com/maps/@41.874048,-80.763807,18z/data=!3m1!1e3) | solar:N portables:0 fence:partial track:N fields:0 courts:1 pool:N | Location: correct (exact match). Facility: not checked. |
| 402277001928 | Emerson Alternative Ed. HS (Oklahoma City, OK) | [open](https://www.google.com/maps/@35.4747,-97.5221,18z/data=!3m1!1e3) | solar:N portables:0 fence:partial track:N fields:0 courts:0 pool:N | Location: correct campus, combined/district naming. Facility: not checked. |
| 401452000682 | Hilldale Lower ES (Muskogee, OK) | [open](https://www.google.com/maps/@35.710378,-95.370948,18z/data=!3m1!1e3) | solar:N portables:0 fence:partial track:N fields:0 courts:1 pool:N | Location: correct campus, combined/district naming. Facility: not checked. |
| 421917006915 | Pittsburgh Brashear HS (Pittsburgh, PA) | [open](https://www.google.com/maps/@40.4186,-80.0181,18z/data=!3m1!1e3) | solar:N portables:0 fence:partial track:N fields:3 courts:1 pool:N | Location: **incorrect** -- the nearest label on Google Maps at this point is "South Hills Middle School," a different school entirely. Couldn't tell from the screenshot whether this is a wrong CCD coordinate or a genuinely adjacent/shared campus -- left open rather than guessed at. Facility: not checked. |
| 421929000163 | Pleasant Valley El Sch (Kunkletown, PA) | [open](https://www.google.com/maps/@40.912699,-75.472289,18z/data=!3m1!1e3) | solar:N portables:0 fence:partial track:N fields:0 courts:1 pool:N | Location: correct (exact match). Facility: not checked. |
| 450387001491 | India Hook Elementary (Rock Hill, SC) | [open](https://www.google.com/maps/@35.003148,-81.022339,18z/data=!3m1!1e3) | solar:N portables:0 fence:partial track:N fields:0 courts:1 pool:N | Location: correct (exact match). Facility: not checked. |
| 481455000943 | Coleman HS (Coleman, TX) | [open](https://www.google.com/maps/@31.809203,-99.424587,18z/data=!3m1!1e3) | solar:N portables:1 fence:partial track:Y fields:2 courts:1 pool:N | Location: correct (exact match). Facility: **miss found** -- screenshot showed a clear track, baseball diamonds, and courts; the pipeline had reported zero. Root cause: the default 350m crop was too small for this campus. Fixed by widening the default to 500m; verified directly on this school (numbers above are post-fix). |
| 481623001325 | Paul L Dunbar Learning Center (Dallas, TX) | [open](https://www.google.com/maps/@32.77488,-96.749203,18z/data=!3m1!1e3) | solar:N portables:0 fence:partial track:N fields:0 courts:1 pool:N | Location: correct (exact match). Facility: not checked. |
| 550957000382 | Northside Intermediate (Milton, WI) | [open](https://www.google.com/maps/@42.78247,-88.94737,18z/data=!3m1!1e3) | solar:N portables:0 fence:partial track:N fields:0 courts:1 pool:N | Location: correct (exact match). Facility: not checked. |

**Tally: 24/25 correct** (19 exact matches + 5 right-campus/combined-naming
cases: Wedowee, Bertha, Adena, Emerson, Hilldale), **1 confirmed miss**
(Pittsburgh Brashear HS). Facility-level accuracy above is opportunistic
spot-checking, not a systematic pass across all 25 -- the systematic facility
check is the second-opinion model comparison (`second_opinion.py`), which is
weaker on independence but consistent in coverage. See memo.pdf's Validation
section for how the two checks are weighted against each other.

## How to use this

1. Click a link -> it opens Google Maps satellite view centered on the CCD
   coordinate at zoom 18 (roughly campus-scale).
2. Compare against `output/measurements.csv` for that `school_id` -- or just
   send me the screenshots and I'll pull the pipeline's numbers to compare.
3. If you want this to count as real hand-labeled validation (not just a
   second AI opinion on a different image), write your own read in the
   "Your read" column before or alongside sending screenshots -- even
   short-hand like "track:y portables:1 fence:none" is enough.
4. You don't have to do all 25 -- the brief explicitly says a subset is
   fine. More is better if you have the time, but a genuine 8-10 school
   check outweighs a rushed 25.
