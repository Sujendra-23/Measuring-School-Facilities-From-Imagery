"""
Send one satellite image crop to a vision-capable LLM and get back the four
facility measurements as structured JSON, each with its own confidence.

Primary model: OpenAI's gpt-5.4, used for all 25 schools. (gpt-4o was the
first choice, then swapped for gpt-5.4 after a head-to-head test showed it
just as fast, cheaper per token, and better-calibrated -- see config.py for
the specifics.)
validation/second_opinion.py uses gpt-4o, the former primary, as a second
opinion -- see that file for why it's OpenAI-vs-OpenAI rather than a true
cross-vendor comparison.

We talk to the API over plain HTTPS (no SDK) so the dependency list stays
short and it's obvious exactly what's being sent and received.
"""

import base64
import json
import re
import time
from dataclasses import dataclass
from typing import Optional

import requests

import config

PROMPT_TEMPLATE = """You are analyzing a top-down aerial image of a U.S. public school campus,
for a research project measuring school facilities at scale.

Image details:
- Ground sample distance: approximately {meters_per_pixel:.2f} meters per pixel
- Image size: {pixels} x {pixels} pixels ({frame_meters:.0f} m across)
- Campus boundary confirmed against OpenStreetMap: {boundary_confirmed}
  ({boundary_note})

Identify the following, counting ONLY features that belong to this school's
campus -- not neighboring houses, businesses, or unrelated parcels. If the
boundary was not independently confirmed, that uncertainty applies to the
WHOLE crop, not just objects near its edge -- you may be looking at a crop
centered on the wrong location entirely. In that case, cap every field's
confidence at 0.75 even for things that look clearly visible: the risk is
about location, not image clarity, and looking clear is not evidence against
that risk.

A. Rooftop solar: are there solar panels visible on any campus rooftop? If
   yes, estimate total panel area in square meters using the stated ground
   sample distance for scale.
B. Portable/modular classrooms: count distinct portable classroom buildings --
   small, uniform rectangular boxes, visually distinct from the main school
   building's roofline. The hard part isn't spotting a small rectangular
   building, it's telling a portable classroom apart from a storage shed,
   electrical/mechanical utility building, or maintenance structure, which
   look similar at this resolution. The single best signal is multiplicity:
   schools deploy portables in matching sets, not alone, so 2+ identical
   rectangular units in a row or cluster near classroom buildings or a
   playground are almost certainly portables. A single isolated small
   rectangular structure with no matching neighbors -- especially near a
   loading area, dumpster enclosure, or parking-lot service zone rather than
   near classrooms or a play area -- is more likely a shed or utility
   building than a portable. Count 1 only when you have a specific reason
   beyond "small rectangular building" to call it a classroom (its
   placement mirrors a classroom row, or it's clearly larger than a typical
   shed). If your count rests on a single ambiguous structure rather than a
   clear matching set, cap confidence at 0.5.
C. Perimeter fencing: is the campus perimeter fenced? Answer full (fenced
   nearly all the way around), partial (fenced along some but not all
   sides), or none. If you can tell the dominant fence type, report
   chain-link, wrought-iron, wall, or other. Fences are genuinely hard to
   see at this resolution, especially chain-link -- if you can't tell,
   say so with a low confidence rather than guessing full or none.
D. Athletic facilities:
   - Running track: an oval track around a field. Look specifically for
     lane markings or a clearly paved/rubberized oval surface -- a worn dirt
     path or a field's curved edge is not enough by itself. This distinction
     is one independent reviewers disagree on often; reserve confidence
     above 0.85 for cases where lane markings or a paved oval are
     unambiguous, not just "there's a reddish curved area."
   - Full-size sports fields: football/soccer/baseball/multi-use fields
     large enough for a team sport, each with its own visible boundary
     markings, goalposts, or bases. Do not count small grassy areas or
     playgrounds. Before giving a count, list each candidate field
     separately in sports_fields_list (one short phrase per field, e.g.
     "football field with track", "baseball diamond, NE corner") -- this is
     to make you justify each one individually rather than pattern-matching
     straight to a number. Adjacent fields sharing turf (e.g. a baseball
     diamond overlapping a football field's end zone) count as separate
     only if each has its own distinct markings -- don't inflate the count
     by treating one shared open area as multiple fields. Two independent
     reviewers still disagree on this count roughly half the time even
     after careful review -- in practice this has been the least reliable
     count in this whole pipeline, worse than that reviewer-disagreement
     rate alone suggests. Treat 0.65 as a rare ceiling, not a typical
     answer: reserve anything above it only for a small campus where every
     single list entry is a clean, unmistakable field. If even one entry
     needed a judgment call -- a blurry boundary, uncertainty over whether
     two markings are one field or two, anything cut off at the frame's
     edge -- the count's confidence belongs at 0.3-0.5, not just under 0.65.
   - Hard courts: paved basketball, tennis, or multi-purpose courts. The
     ambiguity here isn't spotting a court, it's deciding how many when
     several sit together -- independent reviewers of the same image have
     disagreed by a factor of 3-4x on this (one calling a complex 2 courts,
     another calling the same complex 9), which is a far bigger gap than
     ordinary counting error. To make counts comparable, use this fixed
     rule instead of judgment: count distinct rectangular paved surfaces
     you can see separated from their neighbors by a visible gap, seam, or
     color/texture change -- NOT individual painted lines within a surface,
     which are usually too fine to resolve at this image scale. A large
     paved area with faint or unclear internal markings is ONE court
     region, even if its overall size suggests it could hold several --
     don't infer a higher count from size alone. Before giving a count,
     list each distinct surface in hard_courts_list (one short phrase per
     surface, e.g. "tennis court, west side" or "one large paved complex,
     internal divisions unclear"). At this resolution a court can look like
     a parking lot or plaza; if you can't tell which, say so in the list
     entry instead of defaulting to court. Confidence discipline: reserve
     above 0.6 only when every surface's separation from its neighbors is
     visibly clear, and use 0.3-0.5 whenever you counted a large area as
     one region because its internal divisions weren't resolvable.
   - Pool: a swimming pool clearly on campus grounds (not a backyard pool
     next door).

Respond with ONLY this JSON object, no markdown fences, no commentary:
{{
  "solar_present": true/false,
  "solar_area_m2": number or null,
  "solar_confidence": number 0-1,
  "portables_count": integer,
  "portables_confidence": number 0-1,
  "fence_status": "full" | "partial" | "none",
  "fence_type": "chain-link" | "wrought-iron" | "wall" | "other" | null,
  "fence_confidence": number 0-1,
  "track_present": true/false,
  "track_confidence": number 0-1,
  "sports_fields_list": ["short phrase per candidate field, empty array if none"],
  "sports_fields_count": integer,
  "sports_fields_confidence": number 0-1,
  "hard_courts_list": ["short phrase per candidate court, empty array if none"],
  "hard_courts_count": integer,
  "hard_courts_confidence": number 0-1,
  "pool_present": true/false,
  "pool_confidence": number 0-1,
  "notes": "one or two sentences on anything that made this hard to read: tree cover, cloud, image cut off the campus, ambiguous boundary, etc. Empty string if nothing notable."
}}

A confidence of 0.9 should mean you'd expect to be right about 9 times out
of 10 -- do not default to high confidence out of habit. Low resolution,
tree cover, or an unconfirmed campus boundary should pull confidence down.
"""

# Hard courts has shown real instability even with temperature 0 -- the same
# model, same image, same prompt has produced very different counts on
# separate calls (one school: 1, then 4, on back-to-back runs). Two prompt
# wording changes were tried on the main prompt above: a counting-convention
# rule (kept, it helped) and a borderline-exclusion rule (reverted, it made
# both accuracy and confidence-vs-accuracy worse). This is a different fix:
# resample the count independently a couple of times and take the median,
# so a single unlucky sample can't stand as the answer. Kept as its own
# short prompt, not the full multi-field one, since it only needs to ask
# one question and every extra resample is an extra API call.
HARD_COURTS_RESAMPLE_PROMPT = """You are analyzing a top-down aerial image of a U.S. public school campus,
approximately {meters_per_pixel:.2f} meters per pixel, {frame_meters:.0f}m across.
Campus boundary confirmed against OpenStreetMap: {boundary_confirmed} ({boundary_note})

Count paved basketball, tennis, or multi-purpose courts on this campus only --
not neighboring parcels. The ambiguity here isn't spotting a court, it's
deciding how many when several sit together -- independent reviewers of the
same image have disagreed by a factor of 3-4x on this (one calling a complex
2 courts, another calling the same complex 9). Use this fixed rule instead
of judgment: count distinct rectangular paved surfaces separated from their
neighbors by a visible gap, seam, or color/texture change -- NOT individual
painted lines within a surface, which are usually too fine to resolve at
this image scale. A large paved area with faint or unclear internal markings
is ONE court region, even if its size suggests it could hold several -- don't
infer a higher count from size alone. At this resolution a court can look
like a parking lot or plaza; if you can't tell which, don't default to court.

Respond with ONLY this JSON object, no markdown fences, no commentary:
{{"hard_courts_count": integer}}
"""


@dataclass
class VisionResult:
    raw: dict
    model: str
    error: Optional[str] = None


def _build_prompt(meters_per_pixel, boundary_confirmed, boundary_note):
    return PROMPT_TEMPLATE.format(
        meters_per_pixel=meters_per_pixel,
        pixels=config.IMAGE_PIXELS,
        frame_meters=meters_per_pixel * config.IMAGE_PIXELS,
        boundary_confirmed="yes" if boundary_confirmed else "no",
        boundary_note=boundary_note,
    )


def _strip_code_fences(text):
    text = text.strip()
    match = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, re.DOTALL)
    return match.group(1) if match else text


def _backoff_seconds(exc, attempt):
    """A 429 comes with a Retry-After header telling us how long to wait; trust it over a guess."""
    if isinstance(exc, requests.HTTPError) and exc.response is not None and exc.response.status_code == 429:
        retry_after = exc.response.headers.get("retry-after")
        if retry_after:
            try:
                return float(retry_after) + 1
            except ValueError:
                pass
        return 20
    return 2 * (attempt + 1)


def _post_prompt(image_b64, prompt, attempts=3):
    """
    Send one text+image prompt to the primary model at temperature 0 and
    return (parsed_json_dict, error). Shared by the main extraction call and
    the hard-courts resampling calls below, so both go through the same
    auth/retry/parsing path rather than two copies of it.
    """
    body = {
        "model": config.OPENAI_MODEL,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{image_b64}"}},
            ],
        }],
        "temperature": 0,
    }
    # Auth via header, not a URL query param -- requests' own exception
    # messages echo the request URL verbatim, and a key belongs in a header,
    # never somewhere it could get printed into a log or a results file.
    headers = {"Authorization": f"Bearer {config.OPENAI_API_KEY}"}

    last_error = None
    for attempt in range(attempts):
        try:
            response = requests.post(
                "https://api.openai.com/v1/chat/completions", json=body, headers=headers, timeout=60
            )
            response.raise_for_status()
            text = response.json()["choices"][0]["message"]["content"]
            return json.loads(_strip_code_fences(text)), None
        except (requests.RequestException, KeyError, IndexError, json.JSONDecodeError) as exc:
            last_error = str(exc)
            time.sleep(_backoff_seconds(exc, attempt))

    return None, last_error


def _resample_hard_courts_count(image_b64, meters_per_pixel, boundary_confirmed, boundary_note):
    """One extra, focused ask about hard_courts_count alone. Returns an int, or None on failure."""
    prompt = HARD_COURTS_RESAMPLE_PROMPT.format(
        meters_per_pixel=meters_per_pixel,
        frame_meters=meters_per_pixel * config.IMAGE_PIXELS,
        boundary_confirmed="yes" if boundary_confirmed else "no",
        boundary_note=boundary_note,
    )
    parsed, _ = _post_prompt(image_b64, prompt, attempts=2)
    return parsed.get("hard_courts_count") if parsed else None


def analyze_image(image_path, meters_per_pixel, boundary_confirmed, boundary_note, attempts=3):
    with open(image_path, "rb") as f:
        image_b64 = base64.b64encode(f.read()).decode("utf-8")

    prompt = _build_prompt(meters_per_pixel, boundary_confirmed, boundary_note)
    parsed, error = _post_prompt(image_b64, prompt, attempts=attempts)
    if parsed is None:
        return VisionResult(raw={}, model=config.OPENAI_MODEL, error=error)

    if isinstance(parsed.get("hard_courts_count"), int):
        samples = [parsed["hard_courts_count"]]
        for _ in range(2):
            extra = _resample_hard_courts_count(image_b64, meters_per_pixel, boundary_confirmed, boundary_note)
            if isinstance(extra, int):
                samples.append(extra)
            time.sleep(config.OPENAI_DELAY_SECONDS)
        samples.sort()
        # Lower median: for 3 samples this is the plain middle value; if one
        # resample call failed and only 2 came back, this picks the smaller
        # of the two -- consistent with the rest of this prompt's rule to
        # not infer a higher count than what's clearly resolvable.
        parsed["hard_courts_count"] = samples[(len(samples) - 1) // 2]
        if len(set(samples)) > 1:
            # The model disagreed with itself across independent samples --
            # that's measured evidence of unreliability no single call's own
            # confidence claim can see, so it overrides whatever confidence
            # this specific call happened to report. `or 0.4` would be wrong
            # here: a genuine 0 is falsy and would get bumped up to 0.4
            # instead of correctly staying at 0 (didn't happen in this run's
            # data -- confidence never came back as exactly 0 -- but it's a
            # real bug in the fallback logic, not just a hypothetical one).
            reported = parsed.get("hard_courts_confidence")
            parsed["hard_courts_confidence"] = 0.4 if reported is None else min(0.4, reported)

    return VisionResult(raw=parsed, model=config.OPENAI_MODEL)
