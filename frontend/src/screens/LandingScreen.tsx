/** The landing page — the front door.
 *
 *  Implements `Nodus Landing.dc.html` from the Claude Design project. It is the
 *  one screen that renders outside the shell: a visitor who has not opened a
 *  query yet has nothing to navigate, so the sidebar would be ten dead rows.
 *
 *  Every sentence here is a claim about the product, so each one is taken from
 *  the code rather than from the mockup: the ranking weights from
 *  `services/ranking.py`, how a lineage is built and labelled from
 *  `services/lineage.py`, the eight driver categories from `DriverType`, the
 *  quality weights, scales and thresholds from `services/quality.py`, and the
 *  controls from what the screens actually send. The worked example's lineage
 *  and quality figures were produced by running `build_lineage_tree` and
 *  `assess_cluster` on the inputs shown, not typed in — change an input and they
 *  have to be recomputed.
 *
 *  Each axis section describes that axis and nothing else. A lineage label is a
 *  paper's stance on the cluster's assertion, not its relation to the paper
 *  before it — "contradicts" does not mean "contradicts the origin" — and the
 *  copy has to say which, because the chain invites the other reading.
 */

import { Fragment, type CSSProperties, type ReactElement, type ReactNode } from 'react'

import { HeroField } from '../components/HeroField'
import {
  ControlIcon,
  DeploymentArt,
  LineageTimeline,
  PipelineArt,
  ProblemArt,
  ScoreBar,
  StanceMap,
  type ChainPoint,
  type ControlIconName,
} from '../components/LandingArt'
import { Mark } from '../components/Mark'
import { useStore } from '../state/store'

const REPO = 'https://github.com/raunak-shr/nodus-research'
const README = `${REPO}#readme`

/** The cluster every axis is read against: six papers, one claim each, from
 *  the demo run a visitor sees on opening the app without a backend. */
const EXAMPLE_THEME = 'effect sizes shrink in trials with blinded outcome assessment'

/** The example's lineage as `build_lineage_tree` orders and labels it: by year,
 *  the earliest as origin, and every later paper by its own claim's stance on
 *  the cluster's assertion — neutral surfaces as `extends`. The origin's label
 *  replaces its stance, so the stance is carried separately. */
const CHAIN: (ChainPoint & { cite: string; claim: string })[] = [
  {
    rel: 'origin',
    stance: 'supports',
    year: 2009,
    short: 'Krogh 2009',
    cite: 'Krogh et al. — the DEMO trial',
    claim: 'Aerobic exercise did not lower blinded depression ratings more than relaxation did.',
  },
  {
    rel: 'supports',
    stance: 'supports',
    year: 2012,
    short: 'Chalder 2012',
    cite: 'Chalder et al. — the TREAD trial',
    claim: 'Facilitated physical activity did not improve blinded depression scores at four months.',
  },
  {
    rel: 'supports',
    stance: 'supports',
    year: 2013,
    short: 'Cooney 2013',
    cite: 'Cooney et al. — Cochrane review',
    claim: 'Restricted to trials with blinded assessment and intention-to-treat analysis, the pooled effect became small.',
  },
  {
    rel: 'contradicts',
    stance: 'contradicts',
    year: 2016,
    short: 'Schuch 2016',
    cite: 'Schuch et al. — meta-analysis adjusting for publication bias',
    claim: 'Correcting for publication bias left a substantial effect in place.',
  },
  {
    rel: 'extends',
    stance: 'neutral',
    year: 2017,
    short: 'Krogh 2017',
    cite: 'Krogh et al. — review with trial sequential analysis',
    claim: 'The blinded trials so far are too few to settle the question either way.',
  },
  {
    rel: 'contradicts',
    stance: 'contradicts',
    year: 2024,
    short: 'Noetel 2024',
    cite: 'Noetel et al. — network meta-analysis',
    claim: 'Pooled 218 trials and found moderate effects, with risk of bias assessed for each.',
  },
]

/** The example's stance counts, counted off the chain rather than typed, so the
 *  figure, the drawing and the penalty cannot disagree about them. */
const STANCES: { key: 'sup' | 'neu' | 'con'; label: string; count: number }[] = [
  { key: 'sup', label: 'support', count: CHAIN.filter((c) => c.stance === 'supports').length },
  { key: 'neu', label: 'neutral', count: CHAIN.filter((c) => c.stance === 'neutral').length },
  { key: 'con', label: 'contradict', count: CHAIN.filter((c) => c.stance === 'contradicts').length },
]

/** `DriverType` in `app/schemas/analysis.py`, in its own order. */
const DRIVER_TYPES = [
  'methodology',
  'population',
  'metric definition',
  'temporal',
  'sample size',
  'analysis',
  'publication bias',
  'other',
]

/** A driver is a type and a description — nothing else. The papers are named
 *  inside the description, which is where the agent is told to put them. */
const DRIVERS: { cat: string; text: string }[] = [
  {
    cat: 'methodology',
    text: 'Krogh 2009, Chalder 2012 and Cooney 2013 rest on trials with blinded outcome assessment; Schuch 2016 and Noetel 2024 keep unblinded trials in the pool and adjust for bias statistically instead.',
  },
  {
    cat: 'sample size',
    text: 'The blinded-only estimates draw on a handful of small trials, against dozens to hundreds in the full pools, so the sceptical estimate carries the wider interval.',
  },
]

/** `assess_cluster` on the example: types rct ×2, systematic_review ×2,
 *  meta_analysis ×2; largest n 14,170; six papers; confidences 0.92, 0.95,
 *  0.94, 0.90, 0.89, 0.87; three supporting, two contradicting, one neutral.
 *  Contributions are the products, so the column adds up to the total. */
const COMPONENTS: { term: string; input: string; value: string; weight: string; contrib: string }[] = [
  { term: 'Study design', input: '2 RCTs · 2 systematic reviews · 2 meta-analyses', value: '0.98', weight: '40%', contrib: '0.392' },
  { term: 'Sample size', input: 'largest reported n = 14,170', value: '1.00', weight: '20%', contrib: '0.200' },
  { term: 'Corroboration', input: '6 separate papers', value: '1.00', weight: '20%', contrib: '0.200' },
  { term: 'Extraction confidence', input: 'mean of 6 claims', value: '0.91', weight: '20%', contrib: '0.182' },
]
const EXAMPLE_SCORE = '0.914'
/** 0.15 × 2 contradicting of 5 non-neutral claims. */
const EXAMPLE_PENALTY = '0.060'
/** The component names, short enough to sit inside their own bar segment. */
const SCORE_LABEL: Record<string, string> = {
  'Study design': 'design',
  'Sample size': 'sample',
  Corroboration: 'corrob.',
  'Extraction confidence': 'conf.',
}

/** `_STUDY_TYPE_WEIGHT`, best first. */
const DESIGN_LADDER: [string, string][] = [
  ['meta-analysis', '1.00'],
  ['systematic review', '0.95'],
  ['RCT', '0.90'],
  ['cohort', '0.70'],
  ['observational', '0.60'],
  ['cross-sectional', '0.55'],
  ['review', '0.50'],
  ['qualitative', '0.40'],
  ['unknown', '0.35'],
  ['case study, preprint', '0.30'],
]

/** The four provenance marks, as `lib/evidence.ts` defines them. */
const PROV_MARKS: { glyph: string; text: string }[] = [
  { glyph: '¶', text: 'quote found in the full text' },
  { glyph: '≈', text: 'found approximately — the span may be off' },
  { glyph: '§', text: 'abstract only — no full text behind it' },
  { glyph: '—', text: 'quote could not be located' },
]

/** What a reader can actually do, by when they can do it. Each entry is
 *  something a screen sends or shows — nothing the API has that no screen uses. */
const CONTROLS: { when: string; title: string; text: string; icon: ControlIconName }[] = [
  {
    when: 'Before a run',
    title: 'Check the question',
    icon: 'interpret',
    text: 'Interpret shows how the question was read — its topic, its outcome, the concepts it will search on — and says whether it is specific enough to be worth a run, with sharper versions if not. It is advice: you can still run it as typed.',
  },
  {
    when: 'Before a run',
    title: 'Choose the papers',
    icon: 'upload',
    text: 'Search Semantic Scholar, or upload two to twenty PDFs of your own, up to 10 MB each. An upload run reads exactly those files, in the order you gave them, and nothing is fetched to stand in for them.',
  },
  {
    when: 'While it runs',
    title: 'Watch it, or stop it',
    icon: 'run',
    text: 'Progress arrives as each paper is read, each cluster analysed and each section written. A paper that cannot be read is marked and skipped, and the run carries on. Cancel at any point.',
  },
  {
    when: 'After it finishes',
    title: 'Check a claim at its source',
    icon: 'source',
    text: 'Open the passage a claim was extracted from, with the quote located in it and marked by how exactly it was found — or marked as abstract-only, or not locatable, when that is the truth.',
  },
  {
    when: 'After it finishes',
    title: 'Correct the analysis',
    icon: 'edit',
    text: "Change a claim's stance, rename a cluster (its report heading follows), set a cluster's tier by hand, or rewrite the executive summary. The Edits screen lists this session's changes, each beside what it replaced.",
  },
  {
    when: 'After it finishes',
    title: 'Ask the report',
    icon: 'chat',
    text: 'Questions are answered from this report and its clusters alone, citing the section each answer used. When the report cannot settle a question, the answer says so and offers a follow-up run instead of guessing.',
  },
  {
    when: 'After it finishes',
    title: 'Follow up',
    icon: 'followup',
    text: 'A follow-up starts a new run on your next question, read in the context of the first, and stays linked to it.',
  },
  {
    when: 'After it finishes',
    title: 'See it as a graph',
    icon: 'graph',
    text: 'The same run as a field of nodes, in four views: clusters, papers, authors, and the lineage chains.',
  },
  {
    when: 'After it finishes',
    title: 'Take it with you',
    icon: 'export',
    text: 'Export Markdown, JSON or HTML, or download a PDF that is the print layout of the report on screen, so the two cannot drift apart.',
  },
]

const COMPARISON: { q: string; llm: string; tools: string; nodus: string }[] = [
  {
    q: 'Which paper is this sentence from?',
    llm: 'Sometimes cited, sometimes invented',
    tools: 'Citation list per answer',
    nodus: 'Each claim opens the passage it came from, marked by how exactly it was found',
  },
  {
    q: 'How did this evidence build up?',
    llm: 'A narrative from memory',
    tools: 'Papers listed by relevance',
    nodus: 'Papers behind each claim in date order, each marked supports, contradicts or extends',
  },
  {
    q: 'Why do these papers disagree?',
    llm: 'Prose guess, unstructured',
    tools: 'Conflict noted, reason rarely typed',
    nodus: 'A stance on every claim, and drivers in eight categories that name the papers',
  },
  {
    q: 'How was quality decided?',
    llm: "Model's opinion",
    tools: 'Model or metadata heuristic',
    nodus: 'A fixed formula, with every input, weight and threshold shown',
  },
  {
    q: 'Can I correct it?',
    llm: 'Re-prompt and hope',
    tools: 'Rarely',
    nodus: 'Stances, cluster names, tiers and the summary — a tier override keeps the computed one beside it',
  },
  {
    q: 'Where does my data live?',
    llm: "Vendor's servers",
    tools: "Vendor's servers",
    nodus: "This deployment's database, or your own Postgres if you run it yourself",
  },
]

const FAQ: { q: string; a: string }[] = [
  {
    q: 'Where do the papers come from?',
    a: "Semantic Scholar supplies the search, the metadata and the citation counts. Full text comes from the publisher's PDF where one is linked, then from arXiv when the title and authors match; failing both, a paper is read from its abstract. Or skip search entirely and upload your own PDFs.",
  },
  {
    q: 'Where does a language model make the call?',
    a: "In turning your question into a search, in reading each paper for its study type, sample and claims, in judging each claim's stance and the disagreement drivers, and in writing the report prose and chat answers. It does not set quality tiers — those are arithmetic over what it read — and chat answers only from the report, never from the model's own knowledge.",
  },
  {
    q: 'Can it run without a cloud model?',
    a: 'Self-hosted with Ollama for both the model and the embeddings, yes. A run over uploaded PDFs then needs nothing outside your machine and your database. A search run still needs Semantic Scholar, and full text still comes from the publisher or arXiv.',
  },
  {
    q: 'What does it not do?',
    a: 'It does not build a citation graph: lineage is date order plus stance, and says so. A report covers the 25 largest clusters, and the run says how many claims fell outside them. And it does not replace reading the paper — it tells you which papers to read, and what to check when you do.',
  },
  {
    q: 'How long does a run take?',
    a: 'Minutes. Twenty papers, up to twelve claims each, then clustering and a section per cluster. On a free-tier model key much of that is waiting on rate limits. Progress streams the whole way.',
  },
  {
    q: 'Do I need an account?',
    a: 'No. Your history is tied to a token this browser keeps, so another visitor cannot list your runs. Clearing site data loses the history — the runs are not deleted, they just stop being reachable from here.',
  },
]

export function LandingScreen(): ReactElement {
  const store = useStore()
  const open = (): void => store.go('query')
  const decided = STANCES.filter((s) => s.key !== 'neu').reduce((sum, s) => sum + s.count, 0)
  const total = STANCES.reduce((sum, s) => sum + s.count, 0)

  return (
    <div className="landing">
      <header className="lp-head">
        <div className="lp-wrap lp-head-row">
          <span className="lp-brand">
            <Mark size={34} />
            Nodus
          </span>
          <nav className="lp-nav">
            <a href="#axes">Three axes</a>
            <a href="#controls">What you control</a>
            <a href="#pipeline">How it works</a>
            <a href="#deploy">Run your own</a>
            <a href="#faq">FAQ</a>
          </nav>
          <span className="lp-actions">
            <Repo className="btn btn-secondary">View the source</Repo>
            <button type="button" className="btn btn-primary" onClick={open}>
              Open the app
            </button>
          </span>
        </div>
      </header>

      {/* The hero band: the three axes, and the cluster they converge on. */}
      <section className="lp-void">
        <div className="lp-wrap lp-void-inner">
          <p className="lp-statement">
            Three questions, asked of <mark>every finding</mark>: where it came from, who disputes
            it, how far to trust it.
          </p>
          <div className="lp-field-holder">
            <HeroField theme={store.theme} />
          </div>
          <div className="lp-legend">
            <span>
              <i style={{ width: 18, height: 2.5, background: 'var(--l-void-ink)', display: 'block' }} />
              Lineage
            </span>
            <span>
              <i style={{ width: 18, display: 'flex', gap: 3 }}>
                {[0, 1, 2].map((k) => (
                  <i
                    key={k}
                    style={{
                      width: 4,
                      height: 2,
                      background: 'color-mix(in srgb, var(--l-void-ink) 72%, transparent)',
                      display: 'block',
                    }}
                  />
                ))}
              </i>
              Disagreement
            </span>
            <span>
              <i style={{ width: 18, display: 'flex', flexDirection: 'column', gap: 2, alignItems: 'center' }}>
                {[14, 18, 11].map((bar) => (
                  <i
                    key={bar}
                    style={{
                      width: bar,
                      height: 1.5,
                      background: 'color-mix(in srgb, var(--l-void-ink) 56%, transparent)',
                      display: 'block',
                    }}
                  />
                ))}
              </i>
              Quality weighting
            </span>
            <span style={{ color: 'color-mix(in srgb, var(--l-void-ink) 82%, transparent)' }}>
              <i style={{ width: 9, height: 9, background: 'var(--color-accent)', display: 'block' }} />
              Claim cluster
            </span>
          </div>
        </div>
      </section>

      {/* 01 — what it is, beside what one extracted claim carries. */}
      <section className="lp-band">
        <div
          className="lp-wrap lp-split"
          style={{ paddingTop: 'clamp(32px, 4vw, 64px)', paddingBottom: 'clamp(40px, 5vw, 72px)' }}
        >
          <div className="lp-hero-copy" style={{ paddingBottom: 32 }}>
            <p className="lp-eyebrow">01 — Research-paper analysis</p>
            <h1 className="lp-h1" style={{ maxWidth: '19ch' }}>
              Trace every claim
              <br />
              back to its paper.
            </h1>
            <p className="lp-lead pretty" style={{ maxWidth: '54ch' }}>
              Ask a research question and Nodus finds up to twenty papers on Semantic Scholar — or
              reads the PDFs you upload instead. It pulls up to twelve claims from each paper, each
              tied to the passage it came from, groups the claims that say the same thing, and writes
              a report with one section per group. Each section shows where its evidence came from,
              where the papers disagree, and how far it can be trusted.
            </p>
            <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', alignItems: 'center' }}>
              <button
                type="button"
                className="btn btn-primary"
                onClick={open}
                style={{ padding: '12px 20px', fontSize: 15 }}
              >
                Open the app
              </button>
              <a
                className="btn btn-secondary"
                href={README}
                target="_blank"
                rel="noreferrer"
                style={{ padding: '12px 18px', fontSize: 15 }}
              >
                Read the docs
              </a>
            </div>
            <p className="lp-mono" style={{ fontSize: 12.5, lineHeight: 1.7, color: 'var(--n-faint)', margin: '22px 0 0', maxWidth: '48ch' }}>
              Semantic Scholar or your own PDFs · Gemini, Anthropic or Ollama · report as PDF,
              Markdown, JSON or HTML
            </p>
          </div>

          <figure className="lp-hero-art">
            <div className="lp-fig-head">
              <span className="lp-label">One extracted claim</span>
              <span className="lp-fig-meta">Noetel et al. 2024</span>
            </div>
            <p style={{ fontSize: 16, lineHeight: 1.45, margin: '18px 0 20px', fontWeight: 500, maxWidth: '44ch' }}>
              {CHAIN[CHAIN.length - 1].claim}
            </p>
            <div className="lp-ledger">
              <div>
                <span>source</span>
                <b>¶ results · quote found in the full text</b>
              </div>
              <div>
                <span>study type</span>
                <b>meta-analysis</b>
              </div>
              <div>
                <span>sample</span>
                <b>n = 14,170</b>
              </div>
              <div>
                <span>extraction confidence</span>
                <b>0.87</b>
              </div>
              <div>
                <span>stance in its cluster</span>
                <b>contradicts</b>
              </div>
            </div>
            <span className="lp-label" style={{ display: 'block', margin: '22px 0 0', paddingTop: 16, borderTop: '2px solid var(--l-rule)' }}>
              How a source is marked
            </span>
            <div className="lp-marks">
              {PROV_MARKS.map((mark) => (
                <div key={mark.glyph}>
                  <span className="g">{mark.glyph}</span>
                  <span>{mark.text}</span>
                </div>
              ))}
            </div>
          </figure>
        </div>
      </section>

      {/* 02 — the problem. */}
      <section className="lp-wrap lp-sec">
        <p className="lp-eyebrow">02 — The problem</p>
        <h2 className="lp-h2" style={{ maxWidth: '28ch', marginBottom: 32 }}>
          A summary of twenty papers takes a minute. Defending it takes a week.
        </h2>
        <div className="lp-cols">
          <p className="lp-body pretty" style={{ borderTop: '2px solid var(--l-rule)', paddingTop: 18 }}>
            Most tools answer the easy question. You get a fluent paragraph with a row of citations
            under it, and then a colleague asks which paper a specific sentence came from, and you
            are back in the PDFs.
          </p>
          <p className="lp-body pretty" style={{ borderTop: '2px solid var(--l-rule)', paddingTop: 18 }}>
            Three questions decide whether a finding survives review:{' '}
            <em className="lp-term">where did this evidence come from</em>,{' '}
            <em className="lp-term">why do these papers disagree</em>, and{' '}
            <em className="lp-term">how much should I trust it</em>. Those are Nodus's three axes,
            and each answer comes with its working, so you can check it line by line.
          </p>
        </div>
        <figure className="lp-art lp-art-scroll" style={{ '--art-min': '760px' } as CSSProperties}>
          <ProblemArt />
        </figure>
      </section>

      {/* 03 — the three axes, one row each, all read off one example cluster.
          Each row is about its own axis only. */}
      <section id="axes" className="lp-wrap">
        <p className="lp-eyebrow">03 — Three axes</p>
        <p className="lp-body pretty" style={{ maxWidth: '64ch', marginBottom: 'clamp(32px, 4vw, 52px)' }}>
          Every cluster in a report is read along the same three axes. The figures follow one
          example cluster from the app's demo run — six papers on whether{' '}
          <em className="lp-term">{EXAMPLE_THEME}</em> — along each in turn.
        </p>

        <div className="lp-row" style={{ paddingBottom: 'clamp(40px, 5vw, 72px)' }}>
          <div className="txt">
            <h3 className="lp-h3">Lineage</h3>
            <p className="lp-axis-q">Where did this evidence come from?</p>
            <p className="lp-body-sm pretty" style={{ maxWidth: '46ch', marginBottom: 12 }}>
              Each cluster lists the papers behind it in publication order. The earliest is the
              origin — a tie goes to the more-cited paper — and the span from first to last is
              shown, so you can tell a claim resting on one recent study from one built over fifteen
              years.
            </p>
            <p className="lp-body-sm pretty" style={{ maxWidth: '46ch', marginBottom: 12 }}>
              Every later paper is labelled by where its claim stands on the cluster's assertion:{' '}
              <em className="lp-term">supports</em>, <em className="lp-term">contradicts</em>, or{' '}
              <em className="lp-term">extends</em> — bears on it without taking a side. Read down
              the chain and you can see whether the evidence built up in one direction or split, and
              when.
            </p>
            <p className="lp-body-sm pretty" style={{ maxWidth: '46ch' }}>
              It is not a citation graph. Semantic Scholar's search returns no citation links, so
              the chain is rebuilt from publication dates and stances — and the report, its exports
              and the Graph's lineage view all say so.
            </p>
          </div>
          <figure className="art lp-fig">
            <div className="lp-fig-head">
              <span className="lp-label">Lineage · example cluster</span>
              <span className="lp-fig-meta">
                {CHAIN[0].year}–{CHAIN[CHAIN.length - 1].year} · {CHAIN.length} papers
              </span>
            </div>
            <div className="lp-art-scroll" style={{ '--art-min': '440px' } as CSSProperties}>
              <LineageTimeline chain={CHAIN} />
            </div>
            <ol className="lp-chain">
              {CHAIN.map((link) => (
                <li key={link.cite}>
                  <span className={`node node-${link.rel}`} aria-hidden="true" />
                  <div style={{ display: 'flex', gap: 10, alignItems: 'baseline', flexWrap: 'wrap', marginBottom: 5 }}>
                    <span className={`rel rel-${link.rel}`}>{link.rel}</span>
                    <span className="yr">{link.year}</span>
                  </div>
                  <p className="cite">{link.cite}</p>
                  <p className="claim">{link.claim}</p>
                </li>
              ))}
            </ol>
            <p className="lp-mono" style={{ fontSize: 11.5, lineHeight: 1.6, color: 'var(--n-faint)', margin: '22px 0 0' }}>
              basis: chronological + stance. One claim stands for each paper — a supporting one if
              it has one, otherwise its most confident.
            </p>
          </figure>
        </div>

        <div className="lp-rule" />

        <div className="lp-row" style={{ paddingBlock: 'clamp(40px, 5vw, 72px)' }}>
          <div className="txt">
            <h3 className="lp-h3">Disagreement</h3>
            <p className="lp-axis-q">Where do the papers part, and why?</p>
            <p className="lp-body-sm pretty" style={{ maxWidth: '46ch', marginBottom: 12 }}>
              Within a cluster, every claim is read against the cluster's shared assertion and
              marked supports, contradicts or neutral, and the counts are kept. A split of three
              against two stays three against two, instead of becoming the word "mixed".
            </p>
            <p className="lp-body-sm pretty" style={{ maxWidth: '46ch', marginBottom: 12 }}>
              The same reading names what is driving the split. Each driver is typed into one of
              eight categories and says what differs between the papers, by name. Claims that
              genuinely agree get no drivers rather than an invented one, and a short summary says
              where the papers agree and where they part.
            </p>
            <p className="lp-body-sm pretty" style={{ maxWidth: '46ch', marginBottom: 18 }}>
              This is the axis that rests on a language model's judgement — one reading per cluster —
              so it is the one laid open for correction: each stance sits beside its claim, and you
              can change it.
            </p>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
              {DRIVER_TYPES.map((type) => (
                <span key={type} className="tag tag-outline lp-mono" style={{ fontSize: 11 }}>
                  {type}
                </span>
              ))}
            </div>
          </div>
          <figure className="art lp-fig">
            <div className="lp-fig-head">
              <span className="lp-label">Disagreement · example cluster</span>
              <span className="lp-fig-meta">
                {total} claims · {DRIVERS.length} drivers
              </span>
            </div>
            <div className="lp-art-scroll" style={{ '--art-min': '440px' } as CSSProperties}>
              <StanceMap chain={CHAIN} assertion={['effect sizes shrink when', 'assessment is blinded']} />
            </div>
            <p className="lp-mono" style={{ fontSize: 12.5, color: 'var(--n-dim)', margin: '10px 0 22px' }}>
              {STANCES.map((stance) => `${stance.count} ${stance.label}`).join(' · ')}
            </p>
            {DRIVERS.map((driver) => (
              <div key={driver.cat} className="lp-driver">
                <div style={{ marginBottom: 10 }}>
                  <span className="cat">{driver.cat}</span>
                </div>
                <p className="lp-body-sm pretty" style={{ fontSize: 15, lineHeight: 1.55 }}>
                  {driver.text}
                </p>
              </div>
            ))}
          </figure>
        </div>

        <div className="lp-rule" />

        <div className="lp-row" style={{ paddingBlock: 'clamp(40px, 5vw, 72px)' }}>
          <div className="txt">
            <h3 className="lp-h3">Quality weighting</h3>
            <p className="lp-axis-q">How far can it be trusted?</p>
            <p className="lp-body-sm pretty" style={{ maxWidth: '46ch', marginBottom: 12 }}>
              A cluster's tier comes from a fixed formula, not from asking a model how good the
              evidence is. Four components are weighted — study design 40%, sample size 20%,
              corroboration 20%, extraction confidence 20% — and a penalty for contradiction is
              taken off.
            </p>
            <p className="lp-body-sm pretty" style={{ maxWidth: '46ch', marginBottom: 12 }}>
              Design ranks each paper's study type and blends the best with the average — 0.6 ×
              best + 0.4 × mean — so one strong trial lifts a cluster without hiding the rest. Sample
              size takes the largest reported and log-scales it: n = 10 scores 0, 10,000 or more
              scores 1. Corroboration counts separate papers, not claims: one scores 0, five or more
              score 1. The penalty is 0.15 × the share of supporting-or-contradicting claims that
              contradict, so disagreement lowers a score but cannot sink it.
            </p>
            <p className="lp-body-sm pretty" style={{ maxWidth: '46ch' }}>
              Every input is shown on the cluster with its weight and the thresholds, so you can
              redo the sum. If you know something the formula does not, set the tier yourself — the
              computed tier stays on record beside yours.
            </p>
          </div>
          <figure className="art lp-fig">
            <div className="lp-fig-head">
              <span className="lp-label">Quality · example cluster</span>
              <span className="lp-fig-meta">
                {CHAIN.length} papers · {total} claims
              </span>
            </div>
            <div className="lp-art-scroll" style={{ '--art-min': '440px' } as CSSProperties}>
              <ScoreBar
                parts={COMPONENTS.map((row) => ({
                  label: SCORE_LABEL[row.term] ?? row.term,
                  value: Number(row.contrib),
                }))}
                penalty={Number(EXAMPLE_PENALTY)}
                score={Number(EXAMPLE_SCORE)}
              />
            </div>
            <div className="lp-calc" style={{ marginTop: 18 }}>
              <span className="h lp-label-sm">Component</span>
              <span className="h n lp-label-sm">Value</span>
              <span className="h n lp-label-sm">Wt</span>
              <span className="h n lp-label-sm">Contrib</span>

              {COMPONENTS.map((row) => (
                <Fragment key={row.term}>
                  <span className="c term">
                    {row.term}
                    <span className="in">{row.input}</span>
                  </span>
                  <span className="c n" style={{ color: 'var(--n-dim)' }}>
                    {row.value}
                  </span>
                  <span className="c n" style={{ color: 'var(--n-faint)' }}>
                    {row.weight}
                  </span>
                  <span className="c n">{row.contrib}</span>
                </Fragment>
              ))}

              <span className="c term last" style={{ color: 'var(--l-accent-ink)' }}>
                Conflict penalty
                <span className="in">
                  {STANCES.find((s) => s.key === 'con')?.count} of {decided} non-neutral claims contradict
                </span>
              </span>
              <span className="c last" />
              <span className="c last" />
              <span className="c n last" style={{ color: 'var(--l-accent-ink)' }}>
                −{EXAMPLE_PENALTY}
              </span>
            </div>
            <div className="lp-total">
              <span className="lp-total-score">{EXAMPLE_SCORE}</span>
              <span className="lp-mono" style={{ fontSize: 12.5, color: 'var(--n-faint)' }}>
                threshold ≥ 0.70
              </span>
              <span className="lp-badge" style={{ marginLeft: 'auto' }}>
                Tier high
              </span>
            </div>
            <span className="lp-label" style={{ display: 'block', margin: '22px 0 0', paddingTop: 18, borderTop: '2px solid var(--l-rule)' }}>
              Thresholds
            </span>
            <div className="lp-tiers">
              <div className="on">
                <span className="k">high</span>
                <span>≥ 0.70</span>
                <span style={{ marginLeft: 'auto', fontSize: 12 }}>this cluster · {EXAMPLE_SCORE}</span>
              </div>
              <div>
                <span className="k">medium</span>
                <span>≥ 0.45</span>
              </div>
              <div>
                <span className="k">low</span>
                <span>&lt; 0.45</span>
              </div>
            </div>
            <span className="lp-label" style={{ display: 'block', margin: '22px 0 10px', paddingTop: 18, borderTop: '2px solid var(--l-rule)' }}>
              Study design ladder
            </span>
            <div className="lp-ladder">
              {DESIGN_LADDER.map(([type, weight]) => (
                <span key={type}>
                  {type} <b>{weight}</b>
                </span>
              ))}
            </div>
          </figure>
        </div>
      </section>

      {/* 04 — what a reader can do, and the override beside the computation
          it disagrees with. */}
      <section id="controls" className="lp-band-top">
        <div className="lp-wrap lp-sec">
          <div className="lp-row" style={{ marginBottom: 'clamp(36px, 4vw, 56px)' }}>
            <div className="txt">
              <p className="lp-eyebrow">04 — What you control</p>
              <h2 className="lp-h2" style={{ maxWidth: '22ch' }}>
                The model does the reading. You have the last word.
              </h2>
              <p className="lp-body pretty" style={{ maxWidth: '52ch' }}>
                Nodus retrieves, reads and makes the first pass at every judgement. All of it is on
                screen, and the parts that are judgement rather than arithmetic — a claim's stance,
                a cluster's name, a tier you disagree with — are yours to change.
              </p>
            </div>
            <div
              className="art"
              style={{
                display: 'flex',
                flexWrap: 'wrap',
                alignItems: 'stretch',
                borderTop: '2px solid var(--l-rule)',
                borderBottom: '2px solid var(--l-rule)',
              }}
            >
              <figure style={{ flex: '1 1 190px', minWidth: 0, margin: 0, padding: 20 }}>
                <span className="lp-label-sm" style={{ display: 'block', marginBottom: 16, fontSize: 12 }}>
                  Computed
                </span>
                <div style={{ display: 'flex', alignItems: 'baseline', gap: 12, marginBottom: 14 }}>
                  <span style={{ fontFamily: 'var(--font-heading)', fontWeight: 800, fontSize: 34, lineHeight: 1, letterSpacing: '-.03em' }}>
                    medium
                  </span>
                  <span className="lp-mono" style={{ fontSize: 13, color: 'var(--n-faint)' }}>
                    0.624
                  </span>
                </div>
                <p className="lp-mono" style={{ fontSize: 12, lineHeight: 1.7, color: 'var(--n-dim)', margin: 0 }}>
                  design 0.67 · sample 0.76
                  <br />
                  corrob. 0.50 · conf. 0.78
                  <br />
                  penalty −0.050
                </p>
              </figure>
              <figure
                style={{
                  flex: '1 1 190px',
                  minWidth: 0,
                  margin: 0,
                  padding: 20,
                  borderLeft: '2px solid var(--l-rule)',
                  background: 'var(--n-panel)',
                }}
              >
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 16 }}>
                  <span className="lp-label" style={{ color: 'var(--l-accent-ink)' }}>
                    Yours
                  </span>
                  <span className="lp-badge-sm" style={{ marginLeft: 'auto' }}>
                    override
                  </span>
                </div>
                <div style={{ display: 'flex', alignItems: 'baseline', gap: 12, marginBottom: 14 }}>
                  <span style={{ fontFamily: 'var(--font-heading)', fontWeight: 800, fontSize: 34, lineHeight: 1, letterSpacing: '-.03em', color: 'var(--l-accent-ink)' }}>
                    low
                  </span>
                  <span className="lp-mono" style={{ fontSize: 13, color: 'var(--n-faint)' }}>
                    set by hand
                  </span>
                </div>
                <p style={{ fontSize: 12.5, lineHeight: 1.6, color: 'var(--n-dim)', margin: 0 }}>
                  The computed tier stays in the cluster's record beside yours, and Revert puts it
                  back.
                </p>
              </figure>
              <p className="lp-mono" style={{ flex: '1 1 100%', fontSize: 11.5, lineHeight: 1.6, color: 'var(--n-faint)', margin: 0, padding: '12px 20px', borderTop: '1px solid var(--l-hair)' }}>
                Another cluster: three papers — a cohort, an observational study and a
                cross-sectional survey — two supporting, one contradicting.
              </p>
            </div>
          </div>

          <div className="lp-controls">
            {CONTROLS.map((control) => (
              <div key={control.title}>
                <ControlIcon name={control.icon} />
                <span className="lp-label-sm">{control.when}</span>
                <h4 className="lp-h4">{control.title}</h4>
                <p className="lp-body-sm pretty">{control.text}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* 05 — the pipeline. */}
      <section id="pipeline" className="lp-band-top">
        <div className="lp-wrap lp-sec">
          <p className="lp-eyebrow">05 — How it works</p>
          <h2 className="lp-h2" style={{ maxWidth: '26ch' }}>
            Three stages, a few minutes
          </h2>
          <p className="lp-body pretty" style={{ maxWidth: '58ch', marginBottom: 44 }}>
            Progress streams as the run goes: each paper as it is read, each cluster as it is
            analysed, each section as it is written. It is fetching and reading real papers, so
            expect minutes rather than seconds.
          </p>
          <figure
            className="lp-art-scroll"
            style={{ '--art-min': '860px', margin: '0 0 clamp(40px, 5vw, 64px)' } as CSSProperties}
          >
            <PipelineArt />
          </figure>
          <div className="lp-stages">
            <div>
              <p className="lp-label" style={{ fontFamily: 'var(--font-heading)', fontSize: 13, letterSpacing: '.1em', margin: '0 0 12px', paddingBottom: 12, borderBottom: '2px solid var(--l-rule)' }}>
                Stage 1
              </p>
              <h4 className="lp-h4">Find the papers</h4>
              <p className="lp-body-sm pretty" style={{ marginBottom: 18 }}>
                Your question is turned into a structured search — its topic, its outcome and the
                concepts to search on. Semantic Scholar is queried, and the results are ranked by a
                composite score whose weights are written down. The top twenty are kept.
              </p>
              <div className="lp-ledger">
                <div>
                  <span>normalized citations</span>
                  <b>40%</b>
                </div>
                <div>
                  <span>influential citations</span>
                  <b>30%</b>
                </div>
                <div>
                  <span>recency</span>
                  <b>20%</b>
                </div>
                <div>
                  <span>search relevance</span>
                  <b>10%</b>
                </div>
                <div style={{ fontFamily: 'var(--font-body)', lineHeight: 1.55, color: 'var(--n-faint)', display: 'block' }}>
                  An upload run skips the search and the ranking: your PDFs, in your order,
                  unscored.
                </div>
              </div>
            </div>
            <div>
              <p className="lp-label" style={{ fontFamily: 'var(--font-heading)', fontSize: 13, letterSpacing: '.1em', margin: '0 0 12px', paddingBottom: 12, borderBottom: '2px solid var(--l-rule)' }}>
                Stage 2
              </p>
              <h4 className="lp-h4">Read each paper</h4>
              <p className="lp-body-sm pretty" style={{ marginBottom: 18 }}>
                Each paper is read from its full text where one can be found, and from its abstract
                otherwise. Its study type, design and sample are recorded, then up to twelve claims
                are taken from its results, discussion, conclusions and limitations, each with the
                verbatim quote behind it.
              </p>
              <div className="lp-ledger">
                <div>
                  <span>full text</span>
                  <span style={{ color: 'var(--n-faint)' }}>publisher PDF → arXiv → abstract</span>
                </div>
                <div>
                  <span>claims per paper</span>
                  <b>up to 12</b>
                </div>
                <div>
                  <span>papers read at once</span>
                  <b>10</b>
                </div>
                <div style={{ fontFamily: 'var(--font-body)', lineHeight: 1.55, color: 'var(--n-faint)', display: 'block' }}>
                  An arXiv copy is used only if its title and authors match. A paper that cannot be
                  read is marked and skipped; the run carries on.
                </div>
              </div>
            </div>
            <div>
              <p className="lp-label" style={{ fontFamily: 'var(--font-heading)', fontSize: 13, letterSpacing: '.1em', margin: '0 0 12px', paddingBottom: 12, borderBottom: '2px solid var(--l-rule)' }}>
                Stage 3
              </p>
              <h4 className="lp-h4">Cluster, weigh, write</h4>
              <p className="lp-body-sm pretty" style={{ marginBottom: 18 }}>
                Claims that say the same thing are grouped across papers by meaning. Each group is
                read for stance and disagreement, its lineage is built and its quality scored, and
                one report section is written per group — citing papers as [Author, Year], with the
                caveats a reviewer would raise.
              </p>
              <div className="lp-ledger">
                <div>
                  <span>claims</span>
                  <span style={{ color: 'var(--n-faint)' }}>→ up to 25 clusters</span>
                </div>
                <div>
                  <span>cluster</span>
                  <span style={{ color: 'var(--n-faint)' }}>→ lineage · disagreement · tier</span>
                </div>
                <div>
                  <span>cluster</span>
                  <span style={{ color: 'var(--n-faint)' }}>→ one report section</span>
                </div>
                <div style={{ fontFamily: 'var(--font-body)', lineHeight: 1.55, color: 'var(--n-faint)', display: 'block' }}>
                  An executive summary, key findings and open questions frame the whole.
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* 06 — this deployment, and running your own. */}
      <section id="deploy" className="lp-band-top">
        <div className="lp-wrap lp-sec">
          <div className="lp-row">
            <div className="txt">
              <p className="lp-eyebrow">06 — Use it here, or run your own</p>
              <h2 className="lp-h2" style={{ maxWidth: '22ch' }}>
                A working deployment, and the code behind it
              </h2>
              <p className="lp-body pretty" style={{ maxWidth: '52ch', marginBottom: 12 }}>
                This site is a working deployment: open the app and run a question, no account needed.
                It is shared, so it limits how many runs it takes at once, and may cap them per day.
              </p>
              <p className="lp-body pretty" style={{ maxWidth: '52ch', marginBottom: 12 }}>
                The source is public. Run it yourself and papers, claims, clusters and reports live in
                your own Postgres, with the models you choose: Gemini, Anthropic or Ollama for the
                language model; Cloudflare Workers AI, Gemini, Ollama or a local lexical fallback for
                the embeddings.
              </p>
              <p className="lp-body pretty" style={{ maxWidth: '52ch' }}>
                With Ollama for both and a set of uploaded PDFs, a run calls nothing outside your own
                machine and database — the configuration for unpublished or embargoed work.
              </p>
            </div>
            <figure id="quickstart" className="art lp-shell">
              <div className="lp-shell-head">
                <span className="lp-label">Quickstart</span>
                <span className="lp-fig-meta">Python 3.11 · Postgres 15 + pgvector · Node</span>
              </div>
              <div className="lp-shell-body">
                <div className="cm"># clone and install</div>
                <div>
                  <span className="pr">$</span> git clone {REPO}.git
                </div>
                <div>
                  <span className="pr">$</span> cd nodus-research {'&&'} uv sync
                </div>
                <div>
                  <span className="pr">$</span> uv run playwright install chromium
                </div>
                <div className="cm cm-gap"># configure the models and the database</div>
                <div>
                  <span className="pr">$</span> cp .env.example .env
                </div>
                <div className="env">LLM_PROVIDER=gemini</div>
                <div className="env">EMBEDDING_PROVIDER=cloudflare</div>
                <div className="env">DATABASE_URL=postgresql+asyncpg://…</div>
                <div className="cm cm-gap"># once, on the database: create extension if not exists vector;</div>
                <div>
                  <span className="pr">$</span> uv run alembic upgrade head
                </div>
                <div>
                  <span className="pr">$</span> uv run uvicorn app.main:app
                </div>
                <div className="cm cm-gap"># the reading surface</div>
                <div>
                  <span className="pr">$</span> cd frontend {'&&'} npm install {'&&'} npm run dev
                </div>
              </div>
            </figure>
          </div>
          <figure className="lp-art lp-art-scroll" style={{ '--art-min': '860px' } as CSSProperties}>
            <DeploymentArt />
          </figure>
        </div>
      </section>

      {/* 07 — the comparison, by question rather than by product. */}
      <section className="lp-wrap" style={{ paddingBottom: 'clamp(48px, 6vw, 88px)' }}>
        <p className="lp-eyebrow">07 — Compared with the alternatives</p>
        <div style={{ overflowX: 'auto' }}>
          <table className="lp-table">
            <thead>
              <tr>
                <th style={{ width: '28%' }}>Question you get asked</th>
                <th>General LLM chat</th>
                <th>Search-and-summarize tools</th>
                <th className="us">Nodus</th>
              </tr>
            </thead>
            <tbody>
              {COMPARISON.map((row) => (
                <tr key={row.q}>
                  <td className="q">{row.q}</td>
                  <td className="weak">{row.llm}</td>
                  <td className="mid">{row.tools}</td>
                  <td>{row.nodus}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="lp-mono" style={{ fontSize: 12, lineHeight: 1.6, color: 'var(--n-faint)', margin: '16px 0 0', maxWidth: '66ch' }}>
          Categories, not products. Individual tools in these categories vary, and some do parts of
          this well.
        </p>
      </section>

      {/* 08 — FAQ. */}
      <section id="faq" className="lp-band-top">
        <div className="lp-wrap lp-sec">
          <p className="lp-eyebrow" style={{ marginBottom: 30 }}>
            08 — FAQ
          </p>
          <div className="lp-faq">
            {FAQ.map((entry) => (
              <div key={entry.q}>
                <h4
                  className="lp-h4"
                  style={{ fontSize: 20, lineHeight: 1.15, paddingBottom: 12, borderBottom: '2px solid var(--l-rule)' }}
                >
                  {entry.q}
                </h4>
                <p className="lp-body-sm pretty" style={{ maxWidth: '48ch' }}>
                  {entry.a}
                </p>
              </div>
            ))}
          </div>
        </div>
      </section>

      <section className="lp-slab">
        <div className="lp-wrap" style={{ paddingBlock: 'clamp(52px, 6vw, 96px)' }}>
          <h2 style={{ fontSize: 'clamp(34px, 4.6vw, 68px)', lineHeight: .98, letterSpacing: '-.035em', margin: '0 0 20px', maxWidth: '22ch' }}>
            Read the code, then decide
          </h2>
          <p className="lp-slab-lead pretty">
            The source is public. Ranking, lineage and quality weighting are each one short file —
            read them, then check them against what the app shows you.
          </p>
          <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', alignItems: 'center' }}>
            <button
              type="button"
              className="btn btn-on-accent"
              onClick={open}
              style={{ padding: '13px 22px', fontSize: 15 }}
            >
              Open the app
            </button>
            <Repo className="btn btn-off-accent" style={{ padding: '13px 20px', fontSize: 15 }}>
              View the source
            </Repo>
          </div>
        </div>
      </section>

      <footer className="lp-wrap" style={{ paddingBlock: 'clamp(36px, 4vw, 56px) 32px' }}>
        <div style={{ maxWidth: 520, paddingBottom: 32 }}>
          {/* The design had an email capture here. There is no list to add an
              address to, and a field that silently discards one is a promise
              the page cannot keep. Nor are there tagged releases to point at —
              the repository itself is the one feed that exists. */}
          <p className="lp-body-sm pretty" style={{ fontSize: 14, marginBottom: 14 }}>
            No account and no mailing list. To follow changes,{' '}
            <a href={REPO} target="_blank" rel="noreferrer">
              watch the repository
            </a>{' '}
            on GitHub.
          </p>
        </div>
        <div className="lp-foot-row">
          <span style={{ display: 'flex', alignItems: 'center', gap: 9 }}>
            <Mark size={22} />
            <span style={{ fontFamily: 'var(--font-heading)', fontWeight: 800, fontSize: 18, letterSpacing: '-.03em', color: 'var(--n-text)' }}>
              Nodus
            </span>
          </span>
          <span>Research-paper analysis</span>
          <a href={REPO} target="_blank" rel="noreferrer">
            github.com/raunak-shr/nodus-research
          </a>
          <span style={{ marginLeft: 'auto' }}>Papers via Semantic Scholar</span>
        </div>
      </footer>
    </div>
  )
}

/** A link to the repository. Every "source" affordance on the page goes to the
 *  same place, so it is stated once. */
function Repo({
  children,
  className,
  style,
}: {
  children: ReactNode
  className?: string
  style?: CSSProperties
}): ReactElement {
  return (
    <a className={className} style={style} href={REPO} target="_blank" rel="noreferrer">
      {children}
    </a>
  )
}
