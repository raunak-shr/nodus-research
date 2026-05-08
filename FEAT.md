# Why Nodus?

Nodus is a credibility-first system that produces research outputs that can be interrogated, disagreed with, and defended — instead of merely read. Not just a concrete report generation framework, Nodus aligns more towards credibility rather than novel insights or elegant framing. Instead of solving research, it solves research rejection. It focuses on inspection, defensibility and review friction.

It will not:

- Generate new hypotheses
- Replace domain expertise
- Perform true meta-analysis
- Resolve deep scientific disputes
- Convince someone who already distrusts AI

Its more of an aid to academicians rather than replacement. That was never the goal.

## What's new here ?

Any research application out there - Consensus, Elicit, Scite, do one task really well - finding papers, summarizations, referencing, citation-grounding. Nodus stands out in terms of what acamedicians want beyond these.

Nodus grounds its work with the help of 3 Axes that back its output and credibility:

[1]. **Traceable Claim–Evidence–Reasoning Lineage** (“Why do you say this?”)

[2]. **Explicit Uncertainty & Disagreement Modeling** (“Who disagrees and why?”)

[3]. **Methodological Quality & Evidence Weighting** (“How seriously should I take this evidence?”)

Imagine a skeptical reviewer reading a Nodus-generated section.

Reviewer asks:

> “Why do you claim X?”

Axis 1 answers it.

Reviewer asks:

> “But I recall papers that contradict this.”

Axis 2 answers it.

Reviewer asks:

> “Are these good studies or just many studies?”

Axis 3 answers it.

---

# Axis 1: Traceable Claim–Evidence–Reasoning Lineage

*“Why do you say this?”*

---

## Ask

* *For every non-trivial claim in an output, can I see exactly which evidence supports it, how it was interpreted, and where uncertainty or disagreement exists?*
* *Why should I believe this specific sentence?*

## Give

* Paragraph-by-paragraph scrutiny
* Reviewer-style interrogation
* Institutional defensibility

## For Every Paragraph

```
Claim C1

* Supported by: Paper A (Result X), Paper B (Method Y)
* Interpreted as: Causal / Correlational / Speculative
* Confidence: High / Medium / Low
* Known counter-evidence: Paper D
```

How will this help ?

* Trust is non-linear, you need evidence
* One opaque claim can invalidate the entire document

# Axis 2: Explicit Uncertainty & Disagreement Modeling

*“Who disagrees and why?”*

---

## Ask

* *The evidence is mixed. How is it mixed, and why?*
* *Where do studies disagree, and what drives that disagreement?*
* *Is uncertainty coming from data, methods, assumptions, or interpretation?*

## Give

* Explicit exposure of disagreement
* Structured uncertainty instead of narrative smoothing
* Reviewer-visible fault lines in the literature

## For Every Non-Trivial Claim


```
Claim C2

Evidence Landscape

* Supporting studies: N (study types, typical sample sizes)
* Neutral / null studies: M
* Contradicting studies: K

Disagreement Drivers

* Methodological differences (RCT vs observational)
* Dataset bias or population mismatch
* Metric or outcome definition variance
* Temporal or contextual effects

 Uncertainty Type

* Epistemic (lack of evidence)
* Methodological (study design limits)
* Interpretive (conflicting conclusions)

Overall certainty: High / Medium / Low
```

How will this help ?

* Collapsing disagreement creates false certainty
* Researchers trust transparent uncertainty over confident answers
* Explicit disagreement prevents overclaiming
* One unacknowledged conflict can invalidate downstream decisions


# Axis 3: Methodological Quality & Evidence Weighting

*“How seriously should I take this evidence?”*

---

## Ask

* *Not all papers are equal — how much should this evidence actually count?*
* *Is this claim driven by strong studies or just many weak ones?*
* *Would a reviewer immediately down-rank this evidence?*

## Give

* Method-aware evaluation of evidence
* Weighting instead of raw paper counts
* Reviewer-aligned skepticism baked into synthesis

## For Every Non-Trivial Claim

```
Claim C3

Supporting Evidence Breakdown

* High-quality studies:  N (e.g., RCTs, large-scale meta-analyses)
* Medium-quality studies: M (well-designed observational studies)
* Low-quality studies: K (small N, weak controls, preprints)

Quality Signals Considered

* Study design type
* Sample size and statistical power
* Presence of control or baseline
* Peer-reviewed vs preprint
* Reproducibility indicators

Weighted Evidence Score

* Strong / Moderate / Weak

#### Down-weighting Reasons (if any)

* Small sample sizes
* Selection or reporting bias
* Inadequate controls
* Conflicts of interest
```

How will this help ?

* One weak but flashy paper can dominate narratives
* Raw citation counts mislead synthesis
* Researchers already do this mentally — tools do not
* Explicit weighting aligns outputs with peer-review standards

---

Individually:

- Each axis is incremental
- Each can be dismissed

Together: They close each other’s loopholes

Examples:

- Axis 1 without Axis 3 → weak evidence looks strong
- Axis 3 without Axis 2 → disagreement is buried
- Axis 2 without Axis 1 → conflict lacks grounding

All three or nothing
