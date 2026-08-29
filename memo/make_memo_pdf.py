"""
Renders memo.pdf from the section text and tables below.

The assignment caps the memo at one page, so the layout is tuned tight
(small margins/font) to fit real content -- data tables, not just prose --
without spilling to a second page. Content lives directly in this script
rather than being parsed from Markdown -- it's a one-page memo, not a
document pipeline, and a parser would be more code than the content it's
parsing.

Run with (from the repo root):  python memo/make_memo_pdf.py
"""

import os

from fpdf import FPDF

TITLE = "Measuring School Facilities from Imagery -- Memo"

# Each section is (heading, body_text, table_or_None).
# table format: (col_headers, rows, col_widths_mm) -- kept simple since this
# is a two-table document, not a general table renderer.
SECTIONS = [
    ("Validation", """\
All 25 schools got measured, and nothing failed outright. Two different checks here, and they
don't carry the same weight.

Location, the stronger check: I went through all 25 CCD points by hand on Google Maps satellite
view. Real human judgment, not an AI grading its own homework. 24 of 25 landed on the right
campus. That process is also how a real bug turned up -- our OpenStreetMap queries were skipping
node-type features, so any school mapped as a single point instead of a traced building just
never showed up in the pipeline. Fixed it and re-ran everything; OSM now matches the manual check
exactly, with one exception. Pittsburgh Brashear HS is the one school OSM still can't place, and
it's also the one location the manual check flagged as wrong (see Failures).

Facility attributes, the weaker check: gpt-4o re-reads 8 schools that gpt-5.4 already processed,
and I compare the two sets of answers -- 56 comparisons in total. This is a weaker guarantee than
a true cross-vendor check, since two models from the same shop can share the same blind spots.
Agreement rate per field:""", (
        ["Field", "Agree", "Field", "Agree"],
        [
            ["Pool", "1.00", "Sports fields", "0.88"],
            ["Solar", "1.00", "Fencing", "0.75"],
            ["Track", "1.00", "Portables", "0.75"],
            ["", "", "Hard courts", "0.50"],
        ],
        [28, 18, 28, 18],
    )),

    ("", """\
Track was overconfident at first -- 0.97 stated confidence against only 75% agreement, a 22-point
gap. Turned out confidence just wasn't dropping on schools with an unconfirmed campus boundary,
even though the prompt asked for that. Fixed it, and track has held near-perfect agreement every
round since.

One fix here matters for every number below, not just one field. "Temperature" is the setting
that controls how much randomness a model uses when it answers; at 0, the same question and the
same image should get you the same answer every time. The primary pipeline sets it to 0. The
second-opinion script never did, so it defaulted to 1.0 -- gpt-4o could answer the same image two
different ways purely from that randomness. That looked like real disagreement with gpt-5.4 when
it wasn't. Fixed a while back, so what follows is real signal, not noise that happened to move.

Hard courts was the worst field: two models disagreed 3-4x on the same multi-court complex, one
saying 9 courts, the other 2. A more mechanical rule (count paved surfaces separated by a visible
gap, ignore internal lines too fine to resolve here) cut that gap to 3-vs-1 on that school and
pushed agreement from 38% to 50%. Two more fixes got tried and neither helped -- one made things
worse and got reverted, the other (resampling the count three times, taking the median) changed
nothing. That's useful on its own: the remaining gap is two models genuinely disagreeing, not one
being flaky. Kept the resampling anyway, since it grounds confidence in something measured.

Portables had a problem that stayed hidden until the temperature fix cleared the noise -- agreement
dropped to 38%, a gap the earlier noisy numbers had been masking. The real issue was
classification, not counting: telling a portable classroom apart from a shed. A rule that
multiplicity is the tell (portables show up in matched sets, sheds don't) got agreement up to
75%. Checked directly: Adena Elementary's count went from 18 to 0, and the cached image explains
why -- that row of small rectangles the old prompt was counting is actually parked buses, not
classrooms. One caveat added right before submitting: a clean re-run gave 18 again for this
school, not 0. I re-checked the image and 0 is still right, so the model is being inconsistent
with itself, not the fix breaking. Temperature 0 cuts down on that drift but doesn't kill it; I
kept the originally validated numbers rather than the noisier re-run.

Confidence tracks location quality fairly consistently: 0.71 average on confirmed campuses versus
0.58-0.61 on the three less-certain tiers, same direction every round so far. One honest caveat:
sports fields moved from 75% to 88% agreement with no change on my part, a reminder that some of
this is just noise at an 8-school validation size. That's why the hard-courts and portables
writeups above lean on something concrete rather than a percentage that happened to move.

No field ends up more confident than it actually is -- which is the point of this exercise. In
practice: track, pool, and solar you can trust at face value (100% agreement, confidence to
match). Portables and sports fields are usually right but worth a second glance. Hard courts and
fencing you should check by hand -- hard courts because 50% agreement is a coin flip, and fencing
because 24 of the 25 schools got the exact same "partial, chain-link" answer. That reads more
like a converged default guess than 24 independent reads, and its low confidence (0.46, the
lowest of anything here) is probably more honest than the 75% agreement number suggests. I tried
a fix that required pointing to specific visible fence evidence, and it made things worse --
confidence went up, but the answer got even more uniform, 25 of 25 -- so I reverted it. Location
shows the sharpest version of this same pattern: Brashear, the one wrong location, also has the
lowest confidence of all 25 (0.30, next lowest is 0.65). The one wrong answer is the one flagged
the loudest.""", (
        ["Field", "Mean", "Min", "Max"],
        [
            ["Track", "0.87", "0.70", "0.97"],
            ["Pool", "0.87", "0.70", "0.97"],
            ["Solar", "0.84", "0.70", "0.95"],
            ["Portables", "0.68", "0.45", "0.82"],
            ["Sports fields", "0.52", "0.40", "0.62"],
            ["Hard courts", "0.50", "0.40", "0.70"],
            ["Fencing", "0.46", "0.35", "0.56"],
        ],
        [38, 18, 18, 18],
    )),

    ("Failures", """\
Pittsburgh Brashear HS: the nearest label to the CCD point on Google Maps is "South Hills Middle
School," a different school entirely. I can't tell from a screenshot alone whether that's a bad
CCD coordinate or an adjacent/shared campus, so I left it open instead of guessing.

Two more are naming quirks rather than real errors. Bertha Secondary goes by "Bertha-Hewitt
Public School" on the ground. Wedowee Middle sits on what looks like a shared
elementary/middle/high complex -- OSM has that same point labeled "Wedowee High School," Google
calls it "Wedowee Elementary." Sorting out which co-located school a given facility belongs to is
still an open problem, separate from the location fix.

There's also a distinct bug, caught during manual screenshot review: Coleman HS resolved to the
correct OSM point, but the default 350m crop still cut off its track, fields, and courts, sitting
outside the frame. I widened the default crop to 500m for point/unconfirmed matches and checked
directly that this fixed Coleman's track and field counts.

Solar needed more than a quick read to get right. A before/after comparison (2016 vs. 2026, the
brief's optional part -- see optional/) confirmed solar gains at Wells Middle and Spring Lake
Heights, and overturned two claims I'd made earlier. Bertha shows no solar at either date, so my
earlier screenshot read was probably a non-solar roof pattern. Bel Air's panels were already
visible in 2016, so its main-pipeline miss is a genuine detection failure, not the timing gap I
first claimed -- worth naming plainly. Solar area is only reported for 3 of the 25 schools (Kofa
~5200m², Cerra Vista ~430m², Spring Lake Heights ~1800m²), and it's an LLM eyeball estimate, not a
real measurement -- these numbers have swung by hundreds to thousands of square meters across
re-runs, which is itself the evidence they're rough guesses.

Separately, Overpass, which sizes crops to real campus boundaries, went fully unreachable for
over an hour during development, and a local network drop killed one entire run mid-project.
Both are confirmed infrastructure problems, not bugs in the code. What they imply at scale is
next."""),

    ("Cost at scale", """\
This run cost about $0.26 in OpenAI API calls, all 25 schools plus the 8-school validation subset
combined. That works out to about $0.0076/school for the core pipeline -- the number that
actually scales -- plus a fixed one-time cost for the validation subset. It came out of an
existing credit balance already on the account, so no fresh payment happened. Everything else
(OpenStreetMap, USGS NAIP) is free public data anyway.

Worth being precise about one thing, though: that credit is a one-time balance, not a free tier
that renews. At 130,000 schools, model costs alone would run about $1,000 -- I got that from the
actual prompt lengths and OpenAI's published per-token pricing, not a rounded guess -- more than
enough to burn through that credit in a handful of schools. So the brief's "free tier is enough"
framing holds for this specific run, but it wouldn't hold at real scale. $1,000 is still small,
and the paid tier showed no rate-limit issues at this volume.

Wall-clock time was 10-12 minutes for all 25 schools, roughly 25-29 seconds per school. Scaled
up, that's 4-6 weeks for 130,000 schools on a single worker -- which argues for running things in
parallel, not for anything wrong with the approach.

The bigger constraint, covered in Failures, is that Overpass and USGS's ImageServer are both
shared public infrastructure, and neither is built to handle 130,000 bulk automated queries. A
real deployment would self-host both -- a local OpenStreetMap extract in PostGIS, and either a
bulk NAIP download or a paid imagery vendor with an SLA -- instead of hoping either public
service holds up at that volume."""),

    ("Next (100 hours instead of 5)", """\
First, extend the same hand-labeling I did for location -- all 25 schools, by hand -- to the four
facility attributes, instead of relying on a same-vendor AI cross-check. Location proved this is
doable at this school count, and it's probably the single highest-value thing to do next, since
every other number in this memo depends on how good that validation is.

Second, replace OpenStreetMap with a real parcel/boundary dataset and self-host an Overpass
mirror instead of relying on the public instance. Rural gaps and fuzzy name-matching misses like
Brashear's are the biggest source of location error now, and a service that can disappear for an
hour isn't something to build 130,000 schools on.

For hard courts specifically (see Validation for why three separate attempts plateaued at real
model disagreement rather than something a better prompt could fix): higher-resolution
commercial imagery is the more promising lever, since it removes the ambiguity instead of routing
around it. Same goes for fencing and small-object counts generally -- 0.6m NAIP isn't sharp
enough. I'd pull multiple imagery vintages per school by default rather than as an afterthought,
since this run's confirmed solar-vintage gains are a concrete reason to. I'd swap the ad hoc
vision-LLM solar-area estimate for a purpose-built segmentation model, and route any
low-confidence or model-disagreement row to human review automatically instead of shipping the
same single number for every school regardless of how sure the pipeline is."""),

    ("Tooling", """\
Claude Code (Anthropic) assisted with the coding throughout, under my direction -- I made the
calls on model choice, what to fix, when to stop iterating, and did the manual validation myself,
while Claude Code handled the implementation. That included a head-to-head test that moved
primary extraction off gpt-4o and onto gpt-5.4 (faster or equal per call, cheaper per token, and
better-calibrated on the same images). gpt-5.5 and gpt-5.5-pro got tested and rejected -- 85 to
150+ seconds per call from heavy default reasoning, the wrong tradeoff for a job repeating the
same call 25 times. gpt-4o now serves as the second-opinion model instead.

Location: OpenStreetMap's Overpass API. Imagery: USGS NAIP via Esri's ArcGIS ImageServer.
Optional part: Esri's Wayback archive (free, back to 2014), since NAIP keeps no queryable
history."""),
]


def _block(pdf, h, text, **kwargs):
    """
    multi_cell in this fpdf2 version leaves the cursor's x wherever the last
    line happened to end, instead of resetting it to the left margin. Left
    alone, the next call inherits almost no horizontal room and dies with
    "Not enough horizontal space to render a single character". Resetting x
    before every call sidesteps it.
    """
    pdf.set_x(pdf.l_margin)
    pdf.multi_cell(0, h, text, **kwargs)


def _table(pdf, headers, rows, col_widths, row_h=4.0):
    """A small bordered table -- just enough for the two data tables in this memo."""
    pdf.set_x(pdf.l_margin)
    pdf.set_font("Helvetica", "B", 6.4)
    for header, w in zip(headers, col_widths):
        pdf.cell(w, row_h, header, border=1, align="C")
    pdf.ln(row_h)

    pdf.set_font("Helvetica", "", 6.4)
    for row in rows:
        pdf.set_x(pdf.l_margin)
        for value, w in zip(row, col_widths):
            pdf.cell(w, row_h, value, border=1, align="C")
        pdf.ln(row_h)


def build_pdf(sections, out_path):
    pdf = FPDF(format="Letter", unit="mm")
    pdf.set_margins(left=8.5, top=6.5, right=8.5)
    pdf.set_auto_page_break(auto=True, margin=6.5)
    pdf.add_page()

    pdf.set_font("Helvetica", "B", 11.2)
    _block(pdf, 4.3, TITLE, align="C")
    pdf.ln(0.4)

    for entry in sections:
        heading, body = entry[0], entry[1]
        table = entry[2] if len(entry) > 2 else None

        if heading:
            pdf.set_font("Helvetica", "B", 8.3)
            _block(pdf, 3.2, heading)
        pdf.set_font("Helvetica", "", 7.3)
        # Blank lines in the source mark real paragraph breaks -- collapse
        # whitespace within each paragraph (the source wraps long lines with
        # trailing backslashes) but keep paragraphs visually separated,
        # otherwise every section renders as one dense, run-on block.
        paragraphs = [p for p in body.split("\n\n") if p.strip()]
        for i, paragraph in enumerate(paragraphs):
            _block(pdf, 2.8, " ".join(paragraph.split()))
            if i < len(paragraphs) - 1:
                pdf.ln(0.1)

        if table:
            pdf.ln(0.08)
            headers, rows, widths = table
            _table(pdf, headers, rows, widths, row_h=2.15)

        pdf.ln(0.08)

    page_count = pdf.page_no()
    pdf.output(out_path)
    return page_count


if __name__ == "__main__":
    out_path = os.path.join(os.path.dirname(__file__), "..", "memo.pdf")
    pages = build_pdf(SECTIONS, out_path)
    print(f"Wrote {out_path}")
    if pages > 1:
        print(f"WARNING: memo is {pages} pages -- assignment caps it at 1. Shorten the text.")
    else:
        print("Page count: 1 (within the assignment's limit)")
