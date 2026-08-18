"""Rendered report HTML — the document the frontend shows and the PDF prints.

Two variants of one design, so the PDF cannot drift from the screen:

* ``screen`` — theme-aware (light/dark), sticky ranked cluster rail, claim
  tables and quality rationale collapsed behind disclosures.
* ``print``  — light palette forced, rail dropped for a single column, every
  disclosure expanded, `@page` rules and page-break control. This is what
  Playwright loads in `app/services/pdf_export.py`.

`export.to_dict` supplies the data, so an edited report (Phase 9) renders
exactly like a freshly generated one.
"""

from __future__ import annotations

import html
from typing import Any

from app.models.query import Query
from app.models.report import Report
from app.services import export

TIER_LABEL = {"high": "High", "medium": "Medium", "low": "Low", "unrated": "Unrated"}

_COMPONENT_LABEL = {
    "design": "Study design",
    "sample_size": "Sample size",
    "corroboration": "Corroboration",
    "extraction_confidence": "Extraction confidence",
    "conflict_penalty": "Conflict penalty",
}

_BASE_CSS = """
:root {
  --ground: #f5f6f8;
  --surface: #ffffff;
  --surface-sunk: #eef1f5;
  --ink: #131720;
  --ink-soft: #33405a;
  --muted: #58637a;
  --rule: #dce0e9;
  --rule-strong: #c3cbda;
  --accent: #17456e;
  --accent-soft: #e4ecf5;
  --high: #1f6f4a;
  --medium: #8a5a0b;
  --low: #8c3a34;
  --unrated: #58637a;
  --serif: "Iowan Old Style", "Palatino Linotype", Palatino, "Book Antiqua", Georgia, serif;
  --sans: system-ui, "Segoe UI", ui-sans-serif, Helvetica, Arial, sans-serif;
  --mono: ui-monospace, "Cascadia Mono", Consolas, "Liberation Mono", monospace;
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    --ground: #0d1117;
    --surface: #141a22;
    --surface-sunk: #1b232d;
    --ink: #e5e9f0;
    --ink-soft: #c3cddc;
    --muted: #97a3b6;
    --rule: #242d39;
    --rule-strong: #35414f;
    --accent: #86b6e8;
    --accent-soft: #1a2735;
    --high: #63c295;
    --medium: #ddae5a;
    --low: #e3897f;
    --unrated: #97a3b6;
  }
}
:root[data-theme="dark"] {
  --ground: #0d1117;
  --surface: #141a22;
  --surface-sunk: #1b232d;
  --ink: #e5e9f0;
  --ink-soft: #c3cddc;
  --muted: #97a3b6;
  --rule: #242d39;
  --rule-strong: #35414f;
  --accent: #86b6e8;
  --accent-soft: #1a2735;
  --high: #63c295;
  --medium: #ddae5a;
  --low: #e3897f;
  --unrated: #97a3b6;
}

* { box-sizing: border-box; }
html, body { margin: 0; padding: 0; }
body {
  background: var(--ground);
  color: var(--ink);
  font-family: var(--serif);
  font-size: 17px;
  line-height: 1.7;
  -webkit-text-size-adjust: 100%;
}
a { color: var(--accent); }
a:focus-visible, summary:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: 3px;
  border-radius: 3px;
}

.masthead { background: var(--surface); border-bottom: 1px solid var(--rule); }
.masthead__inner {
  margin: 0 auto; max-width: 1180px; padding: 2.6rem 1.5rem 2rem;
  display: flex; flex-direction: column; gap: 1.1rem;
}
.eyebrow {
  font-family: var(--sans); font-size: .72rem; letter-spacing: .14em;
  text-transform: uppercase; color: var(--muted); margin: 0;
}
h1 {
  font-size: clamp(1.75rem, 3.6vw, 2.6rem); line-height: 1.18; margin: 0;
  text-wrap: balance; letter-spacing: -.01em;
}
.question { font-family: var(--sans); font-size: .95rem; color: var(--ink-soft); margin: 0; }
.question b { font-weight: 600; }
.concepts { display: flex; flex-wrap: wrap; gap: .4rem; }
.concept {
  font-family: var(--sans); font-size: .78rem; color: var(--accent);
  background: var(--accent-soft); border-radius: 2px; padding: .15rem .5rem;
}
.runbar {
  display: flex; flex-wrap: wrap; gap: 0 2.2rem;
  border-top: 1px solid var(--rule); padding-top: 1.1rem; font-family: var(--sans);
}
.runbar div { display: flex; flex-direction: column; }
.runbar__label {
  font-size: .7rem; letter-spacing: .1em; text-transform: uppercase; color: var(--muted);
}
.runbar__value {
  font-family: var(--mono); font-variant-numeric: tabular-nums;
  font-size: 1.05rem; color: var(--ink);
}

.shell {
  margin: 0 auto; max-width: 1180px; padding: 2.5rem 1.5rem 4rem;
  display: grid; grid-template-columns: 1fr; gap: 2.5rem;
}
@media (min-width: 1080px) {
  .shell { grid-template-columns: 15rem minmax(0, 1fr); gap: 3.5rem; }
  .rail {
    position: sticky; top: 1.5rem; align-self: start;
    max-height: calc(100vh - 3rem); overflow-y: auto;
  }
}
.rail h2 {
  font-family: var(--sans); font-size: .7rem; letter-spacing: .12em;
  text-transform: uppercase; color: var(--muted); margin: 0 0 .7rem; font-weight: 600;
}
.rail ol {
  list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: .1rem;
}
.rail a {
  display: grid; grid-template-columns: 1.6rem minmax(0, 1fr) .6rem;
  align-items: baseline; gap: .3rem; font-family: var(--sans); font-size: .82rem;
  line-height: 1.35; color: var(--ink-soft); text-decoration: none;
  padding: .3rem .25rem; border-radius: 3px;
}
.rail a:hover { background: var(--surface-sunk); color: var(--ink); }
.toc__rank {
  font-family: var(--mono); font-variant-numeric: tabular-nums;
  color: var(--muted); font-size: .75rem;
}
.dot { width: .45rem; height: .45rem; border-radius: 50%; align-self: center; }
.dot--high { background: var(--high); }
.dot--medium { background: var(--medium); }
.dot--low { background: var(--low); }
.dot--unrated { background: var(--unrated); }

.doc { min-width: 0; display: flex; flex-direction: column; gap: 3rem; }
.prose { max-width: 68ch; }
.prose p { margin: 0 0 1.1rem; }
.prose p:last-child { margin-bottom: 0; }

.summary h2, .questions h2 { font-size: 1.35rem; margin: 0 0 .9rem; text-wrap: balance; }
.summary { border-left: 3px solid var(--accent); padding-left: 1.4rem; }
.findings { margin: 2rem 0 0; max-width: 72ch; }
.findings h2 {
  font-family: var(--sans); font-size: .72rem; letter-spacing: .12em;
  text-transform: uppercase; color: var(--muted); margin: 0 0 .8rem;
}
.findings ol, .questions ol {
  margin: 0; padding-left: 1.4rem; display: flex; flex-direction: column; gap: .8rem;
}
.questions ol { max-width: 70ch; }

.section { border-top: 1px solid var(--rule-strong); padding-top: 1.6rem; scroll-margin-top: 1rem; }
.section__rank {
  font-family: var(--sans); font-size: .7rem; letter-spacing: .1em;
  text-transform: uppercase; color: var(--muted); margin: 0 0 .5rem;
}
.section h2 {
  font-size: clamp(1.3rem, 2.2vw, 1.6rem); line-height: 1.25; margin: 0 0 .8rem;
  text-wrap: balance; max-width: 40ch;
}
.section__meta {
  display: flex; flex-wrap: wrap; align-items: center; gap: .5rem 1.1rem;
  font-family: var(--sans); font-size: .82rem; color: var(--muted); margin-bottom: 1.4rem;
}
.stat b {
  font-family: var(--mono); font-variant-numeric: tabular-nums;
  color: var(--ink); font-weight: 600;
}
.chip {
  font-size: .75rem; letter-spacing: .02em; padding: .2rem .55rem; border-radius: 2px;
  border: 1px solid currentColor; font-variant-numeric: tabular-nums;
}
.chip--high { color: var(--high); }
.chip--medium { color: var(--medium); }
.chip--low { color: var(--low); }
.chip--unrated { color: var(--unrated); }

.block { margin-top: 1.8rem; }
.block__head {
  font-family: var(--sans); font-size: .72rem; letter-spacing: .12em;
  text-transform: uppercase; color: var(--muted); margin: 0 0 .8rem; font-weight: 600;
}

.chain { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; }
.chain__node {
  display: grid; grid-template-columns: 3.4rem minmax(0, 1fr); gap: 1rem;
  padding: .55rem 0 .55rem 1rem; border-left: 1px solid var(--rule-strong);
  margin-left: .35rem; position: relative;
}
.chain__node::before {
  content: ""; position: absolute; left: -.27rem; top: 1.05rem;
  width: .5rem; height: .5rem; border-radius: 50%;
  background: var(--ground); border: 1.5px solid var(--accent);
}
.chain__year {
  font-family: var(--mono); font-variant-numeric: tabular-nums;
  font-size: .85rem; color: var(--muted); padding-top: .1rem;
}
.chain__body { display: flex; flex-direction: column; gap: .15rem; min-width: 0; }
.chain__rel {
  font-family: var(--sans); font-size: .68rem; letter-spacing: .1em;
  text-transform: uppercase; color: var(--accent);
}
.rel--contradicts { color: var(--low); }
.chain__title { font-size: .97rem; line-height: 1.45; }
.chain__cites {
  font-family: var(--mono); font-size: .75rem; color: var(--muted);
  font-variant-numeric: tabular-nums;
}

.drivers {
  list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column;
  gap: .7rem; max-width: 68ch;
}
.drivers li { display: flex; flex-direction: column; gap: .1rem; }
.driver__type {
  font-family: var(--sans); font-size: .7rem; letter-spacing: .1em;
  text-transform: uppercase; color: var(--medium);
}

details { margin-top: 1.5rem; }
summary {
  cursor: pointer; font-family: var(--sans); font-size: .78rem;
  letter-spacing: .04em; color: var(--accent); padding: .3rem 0;
}
.rationale__body {
  margin-top: .8rem; background: var(--surface-sunk); border-radius: 3px;
  padding: 1rem 1.1rem; max-width: 34rem;
}
.meters { display: flex; flex-direction: column; gap: .45rem; }
.meter {
  display: grid; grid-template-columns: 10.5rem minmax(0, 1fr) 2.6rem;
  align-items: center; gap: .7rem; font-family: var(--sans);
  font-size: .78rem; color: var(--ink-soft);
}
.meter__track { height: .4rem; background: var(--rule); border-radius: 2px; overflow: hidden; }
.meter__fill { display: block; height: 100%; background: var(--accent); }
.meter--penalty .meter__fill { background: var(--low); }
.meter__value {
  font-family: var(--mono); font-variant-numeric: tabular-nums;
  text-align: right; color: var(--muted);
}
.rationale__facts {
  font-family: var(--sans); font-size: .78rem; color: var(--muted); margin: .8rem 0 0;
}

.table-wrap {
  overflow-x: auto; margin-top: .8rem; border: 1px solid var(--rule); border-radius: 3px;
}
table {
  border-collapse: collapse; width: 100%; min-width: 46rem;
  font-family: var(--sans); font-size: .82rem;
}
thead th {
  background: var(--surface-sunk); text-align: left; font-size: .7rem;
  letter-spacing: .08em; text-transform: uppercase; color: var(--muted);
  font-weight: 600; padding: .55rem .7rem; white-space: nowrap;
}
td {
  padding: .55rem .7rem; border-top: 1px solid var(--rule);
  vertical-align: top; line-height: 1.5;
}
.cell--source { white-space: nowrap; color: var(--ink-soft); }
.cell--num {
  font-family: var(--mono); font-variant-numeric: tabular-nums;
  color: var(--muted); white-space: nowrap;
}
.stance {
  font-size: .68rem; letter-spacing: .08em; text-transform: uppercase; white-space: nowrap;
}
.stance--supports { color: var(--high); }
.stance--contradicts { color: var(--low); }
.stance--neutral { color: var(--muted); }

.caveats {
  margin-top: 1.6rem; border: 1px solid var(--rule); border-left: 3px solid var(--medium);
  border-radius: 0 3px 3px 0; padding: 1rem 1.2rem; background: var(--surface); max-width: 70ch;
}
.caveats ul {
  margin: 0; padding-left: 1.2rem; display: flex; flex-direction: column;
  gap: .5rem; font-size: .95rem;
}

.method {
  border-top: 1px solid var(--rule-strong); padding-top: 1.3rem;
  font-family: var(--sans); font-size: .8rem; color: var(--muted); max-width: 74ch;
}
.method p { margin: 0 0 .6rem; }
@media (prefers-reduced-motion: reduce) {
  * { transition: none !important; animation: none !important; }
}

/* Provenance marks. The four states are separated by border treatment, never by
   colour alone — a reader printing in greyscale must still tell a verified quote
   from an approximate span — and each glyph repeats the distinction for anyone
   who cannot see borders at all. */
.prov {
  display: inline-flex; align-items: baseline; gap: .3em;
  font-family: var(--mono); font-size: .78em; letter-spacing: .02em;
  padding: .1em .4em; white-space: nowrap; color: var(--muted);
  border: 1px solid transparent;
}
.prov__glyph { font-style: normal; }
.prov--verified { border-color: var(--ink); color: var(--ink); }
.prov--approximate { border-style: dashed; border-color: var(--rule-strong); }
.prov--abstract {
  border-color: var(--rule-strong);
  border-left-width: 3px; border-left-color: var(--ink);
}
.prov--unavailable {
  border: 0; border-bottom: 1px dotted var(--rule-strong);
  padding-left: 0; padding-right: 0;
}
.sources { margin-top: 1rem; }
.sources ol { list-style: none; margin: 0; padding: 0; display: grid; gap: .5rem; }
.sources li {
  display: grid; grid-template-columns: 2.4rem 1fr; gap: .6rem; font-size: .82rem;
}
.mark { font-family: var(--mono); font-weight: 600; color: var(--ink); }
.sources__quote { font-style: italic; }
.sources__note { color: var(--muted); }
.coverage {
  display: flex; align-items: center; gap: .6rem; flex-wrap: wrap;
  font-size: .78rem; color: var(--muted); margin: .2rem 0 .6rem;
}
.coverage__bar { display: flex; height: 5px; width: 180px; gap: 1px; }
.coverage__seg--verified { background: var(--ink); }
.coverage__seg--approximate {
  background: repeating-linear-gradient(45deg, var(--muted) 0 2px, transparent 2px 4px);
}
.coverage__seg--abstract { background: var(--rule-strong); }
.coverage__seg--unavailable { box-shadow: inset 0 0 0 1px var(--rule-strong); }
"""

_PRINT_CSS = """
@page { size: A4; margin: 18mm 16mm; }
body { font-size: 11pt; line-height: 1.55; background: #ffffff; }
.masthead { border-bottom: 1.5pt solid var(--rule-strong); }
.masthead__inner { padding: 0 0 1rem; max-width: none; }
.shell { display: block; padding: 1.2rem 0 0; max-width: none; }
.rail { display: none; }
.doc { display: block; }
/* Only tables take the full measure; everything read as prose keeps a sane
   line length — the full 178mm of A4 runs to ~105 characters, 156mm gives ~92.
   A physical unit, not `ch`: the digit glyph this serif measures `ch` against
   is wider than its average letter, so 92ch would not constrain anything. */
.prose, .findings, .questions ol, .caveats, .method { max-width: 156mm; }
h1 { font-size: 20pt; }
.section {
  break-inside: avoid-page; page-break-inside: avoid;
  break-before: auto; padding-top: 1rem; margin-top: 1.4rem;
}
.section h2 { break-after: avoid-page; page-break-after: avoid; max-width: none; }
.block__head, .caveats h3 { break-after: avoid-page; page-break-after: avoid; }
.summary { break-inside: avoid-page; }
table { min-width: 0; font-size: 8.5pt; }
.table-wrap { overflow: visible; }
tr { break-inside: avoid; page-break-inside: avoid; }
.rationale__body { max-width: none; }
/* Disclosures are rendered already-open for print — nothing may be hidden in a PDF. */
summary { list-style: none; color: var(--muted); font-weight: 600; }
summary::-webkit-details-marker { display: none; }
a { color: var(--ink); text-decoration: none; }
.doc > div:first-child { break-after: page; page-break-after: always; }
/* A chip cannot be clicked on paper, so the marker becomes the link: it keys a
   claim row to its footnote under the same section. */
.prov { font-size: 7pt; padding: 0 3px; }
.sources { font-size: 8pt; break-inside: avoid-page; page-break-inside: avoid; }
.sources li { grid-template-columns: 2rem 1fr; }
.coverage__bar { width: 120px; }
"""


def _esc(value: Any) -> str:
    return html.escape(str(value)) if value is not None else ""


def _paragraphs(text: str | None) -> str:
    if not text:
        return ""
    blocks = (block.strip() for block in text.split("\n\n"))
    return "\n".join(f"<p>{_esc(block)}</p>" for block in blocks if block)


def _meters(rationale: dict[str, Any] | None, *, expanded: bool) -> str:
    if not rationale:
        return ""
    components = rationale.get("components") or {}
    rows = []
    for key, label in _COMPONENT_LABEL.items():
        if key not in components:
            continue
        value = min(max(float(components[key] or 0.0), 0.0), 1.0)
        penalty = " meter--penalty" if key == "conflict_penalty" else ""
        rows.append(
            f'<div class="meter{penalty}"><span>{_esc(label)}</span>'
            f'<span class="meter__track"><span class="meter__fill" '
            f'style="width:{value * 100:.0f}%"></span></span>'
            f'<span class="meter__value">{value:.2f}</span></div>'
        )

    inputs = rationale.get("inputs") or {}
    known = [t for t in (inputs.get("study_types") or []) if t and t != "unknown"]
    facts = []
    if inputs.get("paper_count") is not None:
        facts.append(f"{inputs['paper_count']} papers")
    if known:
        facts.append(f"mostly {_esc(max(set(known), key=known.count).replace('_', ' '))} designs")
    largest = inputs.get("largest_sample_size")
    facts.append(f"largest reported n: {format(largest, ',') if largest else 'none'}")

    open_attr = " open" if expanded else ""
    return (
        f'<details class="rationale"{open_attr}><summary>How this tier was computed</summary>'
        f'<div class="rationale__body"><div class="meters">{"".join(rows)}</div>'
        f'<p class="rationale__facts">{" · ".join(facts)}</p></div></details>'
    )


def _lineage(section: dict[str, Any]) -> str:
    chain = ((section.get("lineage") or {}).get("chain")) or []
    if not chain:
        return ""
    items = []
    for node in chain:
        relationship = _esc(node.get("relationship") or "unknown")
        cites = format(node.get("citation_count") or 0, ",")
        items.append(
            '<li class="chain__node">'
            f'<span class="chain__year">{_esc(node.get("year") or "n.d.")}</span>'
            f'<span class="chain__body">'
            f'<span class="chain__rel rel--{relationship}">{relationship}</span>'
            f'<span class="chain__title">{_esc(node.get("title"))}</span>'
            f'<span class="chain__cites">{cites} citations</span></span></li>'
        )
    return (
        '<div class="block"><h3 class="block__head">Lineage</h3>'
        f'<ol class="chain">{"".join(items)}</ol></div>'
    )


def _drivers(section: dict[str, Any]) -> str:
    rows = section.get("disagreement_drivers") or []
    if not rows:
        return ""
    items = "".join(
        f'<li><span class="driver__type">{_esc(d.get("type"))}</span>'
        f"<span>{_esc(d.get('description'))}</span></li>"
        for d in rows
    )
    return (
        '<div class="block"><h3 class="block__head">Why the papers disagree</h3>'
        f'<ul class="drivers">{items}</ul></div>'
    )


#: The four provenance states a claim can be in, with the glyph and word that
#: identify each. Order matters: it is the order the legend and the coverage bar
#: read in, best-evidenced first.
_PROV_ORDER = ("verified", "approximate", "abstract", "unavailable")
_PROV_GLYPH = {
    "verified": "\u00b6",
    "approximate": "\u2248",
    "abstract": "\u00a7",
    "unavailable": "\u2014",
}
_PROV_WORD = {
    "verified": "verified",
    "approximate": "approximate span",
    "abstract": "abstract only",
    "unavailable": "not locatable",
}
#: Printed beside a footnote whose provenance is less than a verified body quote.
#: Deliberately terse — the full sentence is the API's `reason`.
_PROV_NOTE = {
    "approximate": "Span boundaries approximate; verify against the page.",
    "abstract": "Quoted from the abstract; the paper body was never retrieved.",
    "unavailable": "Quote recorded but not locatable in the retrieved text.",
}

#: Markers key a claim row to its footnote: section 2's third claim is "2c".
_MARK_LETTERS = "abcdefghijklmnopqrstuvwxyz"

_MIDDOT = "·"


def prov_kind(claim: dict[str, Any]) -> str:
    """Which provenance state a claim is in.

    Origin is tested before match on purpose. An abstract-only quote can match
    exactly, and calling that "verified" would assert the paper body was checked
    when it was never retrieved.
    """
    if claim.get("source_origin") == "abstract":
        return "abstract"
    match = claim.get("source_match") or "none"
    if match in {"exact", "normalized"}:
        return "verified"
    if match == "fuzzy":
        return "approximate"
    return "unavailable"


def _prov_label(claim: dict[str, Any], kind: str) -> str:
    if kind == "unavailable":
        return "no source"
    if kind == "abstract":
        return "abstract"
    where = claim.get("source_section") or "source"
    page = claim.get("source_page")
    return f"{where} \u00b7 p. {page}" if page else str(where)


def _prov_mark(claim: dict[str, Any]) -> str:
    kind = prov_kind(claim)
    return (
        f'<span class="prov prov--{kind}" title="{_esc(_PROV_WORD[kind])}">'
        f'<i class="prov__glyph" aria-hidden="true">{_PROV_GLYPH[kind]}</i>'
        f"<span>{_esc(_prov_label(claim, kind))}</span></span>"
    )


def _mark_for(position: int, index: int) -> str:
    return f"{index}{_MARK_LETTERS[position % len(_MARK_LETTERS)]}"


def _coverage(rows: list[dict[str, Any]]) -> str:
    """How much of a section's evidence can actually be pointed at.

    The same honesty as "built on 17 of 20 papers", one level down: a section
    whose claims are mostly unlocatable should say so on its face rather than
    leaving a reader to notice.
    """
    if not rows:
        return ""
    counts = {kind: 0 for kind in _PROV_ORDER}
    for claim in rows:
        counts[prov_kind(claim)] += 1

    segments = "".join(
        f'<div class="coverage__seg coverage__seg--{kind}" style="flex:{counts[kind]}"></div>'
        for kind in _PROV_ORDER
        if counts[kind]
    )
    words = " \u00b7 ".join(
        f"{counts[kind]} {_PROV_WORD[kind]}" for kind in _PROV_ORDER if counts[kind]
    )
    return (
        f'<div class="coverage"><span>Source coverage</span>'
        f'<span class="coverage__bar" aria-hidden="true">{segments}</span>'
        f"<span>{_esc(words)}</span></div>"
    )


def _source_notes(section: dict[str, Any], index: int) -> str:
    """Footnotes carrying the verbatim quote behind every claim in a section.

    Rendered open for print rather than hidden in a disclosure: a chip cannot be
    clicked on paper, so the quote, section and page have to be on the page.
    """
    rows = section.get("claims") or []
    items = []
    for position, claim in enumerate(rows):
        quote = claim.get("source_quote")
        if not quote:
            continue
        kind = prov_kind(claim)
        page = claim.get("source_page")
        locus = " \u00b7 ".join(
            part
            for part in (claim.get("source_section"), f"p. {page}" if page else None)
            if part
        )
        note = _PROV_NOTE.get(kind)
        note_html = f'<span class="sources__note"> {_esc(note)}</span>' if note else ""
        # Assembled before the f-string: Python 3.11 rejects a backslash escape
        # inside an f-string expression, and these are typographic characters.
        locus_html = f" {_MIDDOT} {_esc(locus)}" if locus else ""
        items.append(
            f'<li><span class="mark">{_mark_for(position, index)}</span><span>'
            f'<span class="prov prov--{kind}">'
            f'<i class="prov__glyph" aria-hidden="true">{_PROV_GLYPH[kind]}</i>'
            f"<span>{_esc(_PROV_WORD[kind])}</span></span> "
            f"{_esc(claim.get('citation'))}"
            f"{locus_html} \u2014 "
            f'<span class="sources__quote">\u201c{_esc(quote)}\u201d</span>'
            f"{note_html}</span></li>"
        )
    if not items:
        return ""
    return (
        f'<div class="sources"><div class="block__head">Sources for section {index}</div>'
        f'<ol>{"".join(items)}</ol></div>'
    )


def _claims(section: dict[str, Any], index: int, *, expanded: bool) -> str:
    rows = section.get("claims") or []
    if not rows:
        return ""
    body = []
    for position, claim in enumerate(rows):
        stance = _esc(claim.get("stance") or "neutral")
        score = claim.get("confidence_score")
        sample = claim.get("sample_size")
        mark = _mark_for(position, index) if claim.get("source_quote") else ""
        body.append(
            "<tr>"
            f'<td class="cell--num"><span class="mark">{mark}</span></td>'
            f'<td><span class="stance stance--{stance}">{stance}</span></td>'
            f'<td class="cell--source">{_esc(claim.get("citation"))}</td>'
            f"<td>{_esc(claim.get('claim_text'))}</td>"
            f"<td>{_prov_mark(claim)}</td>"
            f'<td class="cell--num">{_esc(claim.get("evidence_type"))}</td>'
            f'<td class="cell--num">{format(sample, ",") if isinstance(sample, int) else "—"}</td>'
            f'<td class="cell--num">{format(score, ".2f") if score is not None else "—"}</td>'
            "</tr>"
        )
    open_attr = " open" if expanded else ""
    return (
        f'<details class="claims"{open_attr}>'
        f"<summary>Underlying claims ({len(rows)})</summary>"
        f"{_coverage(rows)}"
        '<div class="table-wrap"><table><thead><tr><th></th><th>Stance</th>'
        "<th>Source</th><th>Claim</th><th>Provenance</th><th>Evidence</th>"
        "<th>n</th><th>Conf.</th></tr></thead>"
        f'<tbody>{"".join(body)}</tbody></table></div>'
        f"{_source_notes(section, index) if expanded else ''}"
        "</details>"
    )


def _caveats(section: dict[str, Any]) -> str:
    rows = section.get("caveats") or []
    if not rows:
        return ""
    items = "".join(f"<li>{_esc(c)}</li>" for c in rows)
    return (
        '<aside class="caveats"><h3 class="block__head">Caveats</h3>'
        f"<ul>{items}</ul></aside>"
    )


def render_body(payload: dict[str, Any], *, variant: str = "screen") -> str:
    """The document body — shared by the standalone page and the PDF."""
    expanded = variant == "print"
    query = payload["query"]
    report = payload["report"]
    sections = report.get("sections") or []
    concepts = (query.get("structured_query") or {}).get("core_concepts") or []

    tier_counts: dict[str, int] = {}
    total_claims = 0
    contradictions = 0
    for section in sections:
        tier = section.get("quality_tier", "unrated")
        tier_counts[tier] = tier_counts.get(tier, 0) + 1
        total_claims += len(section.get("claims") or [])
        contradictions += (section.get("stance_counts") or {}).get("contradicts", 0)

    toc: list[str] = []
    body: list[str] = []
    for index, section in enumerate(sections, start=1):
        tier = section.get("quality_tier", "unrated")
        counts = section.get("stance_counts") or {}
        score = format(section.get("quality_score") or 0.0, ".2f")
        toc.append(
            f'<li><a href="#section-{index}"><span class="toc__rank">{index}</span>'
            f'<span>{_esc(section.get("heading"))}</span>'
            f'<span class="dot dot--{_esc(tier)}" aria-hidden="true"></span></a></li>'
        )
        body.append(
            f'<section class="section" id="section-{index}">'
            f'<p class="section__rank">Rank {index} of {len(sections)} '
            "by evidence strength</p>"
            f"<h2>{_esc(section.get('heading'))}</h2>"
            '<div class="section__meta">'
            f'<span class="chip chip--{_esc(tier)}">'
            f"{_esc(TIER_LABEL.get(tier, 'Unrated'))} quality · {score}</span>"
            f'<span class="stat"><b>{counts.get("supports", 0)}</b> supporting</span>'
            f'<span class="stat"><b>{counts.get("contradicts", 0)}</b> contradicting</span>'
            f'<span class="stat"><b>{counts.get("neutral", 0)}</b> neutral</span>'
            f'<span class="stat"><b>{section.get("paper_count", 0)}</b> papers</span>'
            "</div>"
            f'<div class="prose">{_paragraphs(section.get("narrative"))}</div>'
            f"{_meters(section.get('quality_rationale'), expanded=expanded)}"
            f"{_lineage(section)}"
            f"{_drivers(section)}"
            f"{_claims(section, index, expanded=expanded)}"
            f"{_caveats(section)}"
            "</section>"
        )

    findings = "".join(f"<li>{_esc(f)}</li>" for f in (report.get("key_findings") or []))
    questions = "".join(f"<li>{_esc(q)}</li>" for q in (report.get("open_questions") or []))
    tier_summary = " · ".join(
        f"{count} {TIER_LABEL.get(tier, tier).lower()}"
        for tier, count in sorted(tier_counts.items(), key=lambda kv: -kv[1])
    ) or "none"
    created = (report.get("created_at") or "")[:10]
    edited = " · user edited" if report.get("user_edited") else ""

    runbar = "".join(
        f'<div><span class="runbar__label">{label}</span>'
        f'<span class="runbar__value">{_esc(value)}</span></div>'
        for label, value in (
            ("Papers", query.get("paper_count") or 0),
            ("Claims", total_claims),
            ("Clusters", len(sections)),
            ("Contradictions", contradictions),
            ("Tiers", tier_summary),
            ("Model", report.get("llm_model_used") or "—"),
            ("Run", created or "—"),
        )
    )

    rail = (
        '<nav class="rail" aria-label="Evidence clusters, ranked">'
        "<h2>Clusters by strength</h2>"
        f'<ol>{"".join(toc)}</ol></nav>'
    )
    concept_chips = "".join(f'<span class="concept">{_esc(c)}</span>' for c in concepts)

    return (
        '<header class="masthead"><div class="masthead__inner">'
        f'<p class="eyebrow">Nodus evidence report · three-axis synthesis{edited}</p>'
        f"<h1>{_esc(report.get('title'))}</h1>"
        f'<p class="question"><b>Research question:</b> {_esc(query.get("raw_query"))}</p>'
        f'<div class="concepts">{concept_chips}</div>'
        f'<div class="runbar">{runbar}</div>'
        "</div></header>"
        f'<div class="shell">{rail}<main class="doc">'
        '<div><div class="summary"><h2>Executive summary</h2>'
        f'<div class="prose">{_paragraphs(report.get("executive_summary"))}</div></div>'
        f'<div class="findings"><h2>Key findings</h2><ol>{findings}</ol></div></div>'
        f'{"".join(body)}'
        f'<div class="questions"><h2>Open questions</h2><ol>{questions}</ol></div>'
        '<div class="method"><p>Papers were retrieved from Semantic Scholar and re-ranked by '
        "citation impact, influential citations, recency and relevance position. Claims were "
        "extracted per paper, embedded, and grouped by greedy leader clustering; each cluster "
        "was then analysed for stance, lineage and quality.</p>"
        "<p>Quality tiers are computed deterministically from study design, sample size, "
        "corroboration, extraction confidence and a conflict penalty — every input is shown "
        "under “How this tier was computed”, and tiers are user-overridable. Lineage is "
        "reconstructed from publication chronology and claim stance, not citation edges, so "
        "“origin” means earliest in this cluster rather than historically first.</p></div>"
        "</main></div>"
    )


def render_report_html(report: Report, query: Query, *, variant: str = "screen") -> str:
    """A standalone HTML document for the report.

    `variant="print"` forces the light palette and page-break rules — Chromium
    reads `prefers-color-scheme` from the host when printing, and a dark PDF is
    never what anyone wants.
    """
    if variant not in {"screen", "print"}:
        raise ValueError(f"unknown render variant: {variant!r}")

    payload = export.to_dict(report, query)
    css = _BASE_CSS + (_PRINT_CSS if variant == "print" else "")
    theme = ' data-theme="light"' if variant == "print" else ""
    return (
        f'<!doctype html><html lang="en"{theme}><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>{_esc(report.title)}</title>"
        f"<style>{css}</style></head><body>"
        f"{render_body(payload, variant=variant)}"
        "</body></html>"
    )
