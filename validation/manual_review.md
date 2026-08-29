# Manual review notes (early pilot, superseded)

**Superseded by `manual_spotcheck.md`.** This was an early, 2-school pilot
of "AI reads the cached image" before the real check -- a human (you)
reading independent Google Maps screenshots for all 25 schools -- replaced
it. Kept here only as a record of that earlier step; the completed,
25-school check with real findings is in `manual_spotcheck.md`, and the
memo's Validation section is based on that file, not this one.

This is validation approach #2: a direct visual read of the cached image for
each school, done by the coding assistant (Claude, via Claude Code) looking
at the same PNGs the pipeline used. It is **not independent human ground
truth** -- it's an AI reading the same image a different AI already read.
It's disclosed here as exactly that, not dressed up as something stronger.

What it's actually good for: catching cases where the pipeline's output is
implausible on its face (e.g. claims a track exists where there's obviously
none), and giving concrete, citable examples of the resolution-quality
problems described in memo.pdf. It is a weaker signal than the second-opinion
model comparison (`second_opinion.py`) for anything subtle, because a
correlated blind spot (e.g. both readers failing on the same tree-covered
roof) would show up here as false agreement. Treat this as a sanity check,
not the headline validation number.

For a real submission, at least a handful of these rows should be replaced
with an actual independent human's read before relying on the error rate.

---

## 010282001124 -- Wedowee Middle School (Wedowee, AL)

Location: no OSM match, fell back to CCD point + default 350m crop.

Visual read: single L-shaped main building (metal roof), one small
rectangular outbuilding north of it that could be a shed or a single
portable -- genuinely ambiguous at this resolution. Grass area to the
upper right is unmown/rough, not a maintained field. No track, no hard
courts, no pool, no visible fence, no solar. A scrapyard and a couple of
unrelated houses sit inside the crop to the southwest, which is exactly
the "unconfirmed boundary" risk the pipeline is supposed to flag.

## 060483000471 -- Beverly Hills High (Beverly Hills, CA)

Location: OSM school-grounds polygon matched with high confidence.

Visual read: matches the pipeline's read closely. Running track with
turf field inside, a couple of hard courts, ongoing construction near
the center of campus (visible as bare earth / equipment), no rooftop
solar visible, no outdoor pool visible. I can't independently confirm
the pipeline's note about an indoor "Swim-Gym" pool from the image alone
-- that's outside knowledge the model added, not something visible in
the crop, and its presence/absence should be treated as unverified by
this image even though it happens to be a real, documented fact about
this school.
