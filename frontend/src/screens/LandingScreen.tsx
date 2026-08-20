/** The landing page — the front door.
 *
 *  Implements `Nodus Landing.dc.html` from the Claude Design project. It is the
 *  one screen that renders outside the shell: a visitor who has not opened a
 *  query yet has nothing to navigate, so the sidebar would be ten dead rows.
 *
 *  Every number on this page is a claim about the pipeline, so each one is taken
 *  from the code rather than from the mockup: the quality weights and tier
 *  thresholds from `app/services/quality.py`, the ranking weights and the
 *  twenty-paper cut from the retrieval service, the twelve-claim cap from
 *  `settings.max_claims_per_paper`, and the eight driver categories from
 *  `DriverType`. The design's four-letter tier ladder (A–D at 0.75/0.60/0.45)
 *  is not what the code computes; a page inviting you to redo the arithmetic
 *  cannot get the arithmetic wrong, so it shows the real three.
 */

import { Fragment, type CSSProperties, type ReactElement, type ReactNode } from 'react'

import { HeroField } from '../components/HeroField'
import { useStore } from '../state/store'

const REPO = 'https://github.com/raunak-shr/nodus-research'
const README = `${REPO}#readme`
const RELEASES = `${REPO}/releases`

/** The lineage of one real cluster, as the cluster screen shows it. */
const CHAIN: { rel: 'origin' | 'supports' | 'contradicts' | 'extends'; meta: string; cite: string }[] = [
  {
    rel: 'origin',
    meta: '1999 · 156 cites',
    cite: 'Blumenthal et al. — Effects of exercise training on older patients with major depression',
  },
  {
    rel: 'supports',
    meta: '2007 · 892 cites',
    cite: 'Babyak et al. — Exercise and pharmacotherapy in the treatment of major depressive disorder',
  },
  {
    rel: 'contradicts',
    meta: '2013 · 604 cites',
    cite: 'Cooney et al. — Exercise for depression: Cochrane review of 39 trials',
  },
  {
    rel: 'extends',
    meta: '2018 · 411 cites',
    cite: 'Schuch et al. — Physical activity and incident depression: meta-analysis of prospective cohorts',
  },
  {
    rel: 'supports',
    meta: '2024 · 218 cites',
    cite: 'Noetel et al. — Effect of exercise for depression: systematic review and network meta-analysis',
  },
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

const DRIVERS: { cat: string; pair: string; text: string }[] = [
  {
    cat: 'methodology',
    pair: 'Cooney 2013 ↔ Noetel 2024',
    text: 'One review restricts to trials with blinded outcome assessment and finds a small effect; the other pools unblinded trials in a network model and finds a moderate one.',
  },
  {
    cat: 'population',
    pair: 'Blumenthal 1999 ↔ Schuch 2018',
    text: 'Clinically diagnosed older adults in a supervised trial against a general adult cohort self-reporting activity levels.',
  },
  {
    cat: 'metric definition',
    pair: 'Babyak 2007 ↔ Cooney 2013',
    text: 'Remission rate on HAM-D versus standardised mean difference in continuous symptom scores — the same trials, two effect measures.',
  },
]

/** The four weighted components of a cluster's quality score, and the penalty.
 *  Contributions are the products, so the column adds up to the total below. */
const COMPONENTS: { term: string; value: string; weight: string; contrib: string }[] = [
  { term: 'Study design', value: '0.86', weight: '40%', contrib: '0.344' },
  { term: 'Sample size', value: '0.74', weight: '20%', contrib: '0.148' },
  { term: 'Corroboration', value: '0.80', weight: '20%', contrib: '0.160' },
  { term: 'Extraction confidence', value: '0.91', weight: '20%', contrib: '0.182' },
]

const COMPARISON: { q: string; llm: string; tools: string; nodus: string }[] = [
  {
    q: 'Which paper is this claim from?',
    llm: 'Sometimes cited, sometimes invented',
    tools: 'Citation list per answer',
    nodus: 'Chronological chain of every paper in the cluster',
  },
  {
    q: 'Why do these two papers disagree?',
    llm: 'Prose guess, unstructured',
    tools: 'Conflict noted, reason rarely typed',
    nodus: 'Typed drivers across eight categories, naming the papers',
  },
  {
    q: 'How was quality decided?',
    llm: "Model's opinion",
    tools: 'Model or metadata heuristic',
    nodus: 'Published formula with every input exposed',
  },
  {
    q: 'Can I correct it?',
    llm: 'Re-prompt and hope',
    tools: 'Edits usually lost on re-run',
    nodus: 'Override recorded beside the computation, pinned across re-analysis',
  },
  {
    q: 'Where does my data live?',
    llm: "Vendor's servers",
    tools: "Vendor's servers",
    nodus: 'Your Postgres; fully local with Ollama',
  },
]

const FAQ: { q: string; a: string }[] = [
  {
    q: 'Where do the papers come from?',
    a: 'Semantic Scholar. Retrieval, citation counts and influential-citation counts all come from its API.',
  },
  {
    q: 'Can it run offline?',
    a: 'The pipeline can, via Ollama — extraction, clustering and synthesis all run locally. Retrieval needs Semantic Scholar, so papers already in your database can be re-analysed offline while new queries cannot.',
  },
  {
    q: 'What does it not do?',
    a: 'It does not judge quality with a language model — tiers are arithmetic. It does not replace reading the paper: it tells you which papers to read and what to check when you do.',
  },
  {
    q: 'How long does a run take?',
    a: 'Minutes. Twenty papers, up to twelve claims each, embedding and clustering, then synthesis — progress streams phase by phase while it works.',
  },
]

export function LandingScreen(): ReactElement {
  const store = useStore()

  return (
    <div className="landing">
      <header className="lp-head">
        <div className="lp-wrap lp-head-row">
          <span className="lp-brand">
            <Mark size={34} />
            Nodus
          </span>
          <nav className="lp-nav">
            <a href="#axes">What it shows</a>
            <a href="#pipeline">How it works</a>
            <a href="#deploy">Deployment</a>
            <a href="#faq">FAQ</a>
          </nav>
          <span className="lp-actions">
            <button type="button" className="btn btn-secondary" onClick={() => store.go('query')}>
              Open the app
            </button>
            <Repo className="btn btn-primary">View the source</Repo>
          </span>
        </div>
      </header>

      {/* The hero band: the three axes, and the point they converge on. */}
      <section className="lp-void">
        <div className="lp-wrap lp-void-inner">
          <p className="lp-statement">
            Forty papers, three axes, <mark>one cluster</mark> you can defend.
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
              Convergence
            </span>
          </div>
        </div>
      </section>

      {/* 01 — what it is, beside one worked score. */}
      <section className="lp-band">
        <div
          className="lp-wrap lp-split"
          style={{ paddingTop: 'clamp(32px, 4vw, 64px)', paddingBottom: 'clamp(40px, 5vw, 72px)' }}
        >
          <div className="lp-hero-copy" style={{ paddingBottom: 32 }}>
            <p className="lp-eyebrow">01 — Self-hosted research analysis</p>
            <h1 className="lp-h1" style={{ maxWidth: '19ch' }}>
              Trace every claim
              <br />
              back to its paper.
            </h1>
            <p className="lp-lead pretty" style={{ maxWidth: '54ch' }}>
              Nodus retrieves around twenty papers for a research question, extracts up to twelve
              claims from each, and clusters equivalent claims into a cited report. Every cluster
              carries the lineage of the papers behind it, the typed reason they disagree, and a
              quality tier computed from a published formula you can read.
            </p>
            <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', alignItems: 'center' }}>
              <Repo className="btn btn-primary" style={{ padding: '12px 20px', fontSize: 15 }}>
                Clone the repository
              </Repo>
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
              Your own Postgres · Gemini, Anthropic or Ollama · fully local option
            </p>
          </div>

          <figure className="lp-hero-art">
            <div className="lp-fig-head">
              <span className="lp-label">Cluster quality</span>
              <span className="lp-fig-meta">c2 · 6 papers</span>
            </div>
            <p style={{ fontSize: 16, lineHeight: 1.45, margin: '18px 0 22px', fontWeight: 500, maxWidth: '44ch' }}>
              Aerobic exercise reduces depressive symptoms with a moderate effect size in adults.
            </p>
            <div className="lp-calc">
              <span className="h lp-label-sm">Component</span>
              <span className="h n lp-label-sm">Value</span>
              <span className="h n lp-label-sm">Wt</span>
              <span className="h n lp-label-sm">Contrib</span>

              {COMPONENTS.map((row) => (
                <Fragment key={row.term}>
                  <span className="c term">{row.term}</span>
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
                Conflict penalty · 2 papers
              </span>
              <span className="c last" />
              <span className="c last" />
              <span className="c n last" style={{ color: 'var(--l-accent-ink)' }}>
                −0.060
              </span>
            </div>
            <div className="lp-total">
              <span className="lp-total-score">0.774</span>
              <span className="lp-mono" style={{ fontSize: 12.5, color: 'var(--n-faint)' }}>
                threshold ≥ 0.70
              </span>
              <span className="lp-badge" style={{ marginLeft: 'auto' }}>
                Tier high
              </span>
            </div>
          </figure>
        </div>
      </section>

      {/* 02 — the problem. */}
      <section className="lp-wrap lp-sec">
        <p className="lp-eyebrow">02 — The problem</p>
        <h2 className="lp-h2" style={{ maxWidth: '28ch', marginBottom: 32 }}>
          A summary of forty papers takes a minute. Defending it takes a week.
        </h2>
        <div className="lp-cols">
          <p className="lp-body pretty" style={{ borderTop: '2px solid var(--l-rule)', paddingTop: 18 }}>
            Existing tools answer the easy question. You get a fluent paragraph with a row of
            citations under it, and then a colleague asks which paper a specific sentence came from,
            and you are back in the PDFs.
          </p>
          <p className="lp-body pretty" style={{ borderTop: '2px solid var(--l-rule)', paddingTop: 18 }}>
            Three questions decide whether a finding survives review:{' '}
            <em className="lp-term">which paper is this actually from</em>,{' '}
            <em className="lp-term">why do these two disagree</em>, and{' '}
            <em className="lp-term">how much should I trust it</em>. Nodus is built to answer those
            three, in a form you can check line by line.
          </p>
        </div>
      </section>

      {/* 03 — the three axes, one row each. */}
      <section id="axes" className="lp-wrap">
        <p className="lp-eyebrow">03 — Three axes</p>

        <div className="lp-row" style={{ paddingBottom: 'clamp(40px, 5vw, 72px)' }}>
          <div className="txt">
            <h3 className="lp-h3">Lineage</h3>
            <p className="lp-body-sm pretty" style={{ maxWidth: '46ch', marginBottom: 12 }}>
              Every cluster carries the chronological chain of papers behind it: the originating
              paper and its year, the span of years the claim survived, and how each later paper
              relates to it.
            </p>
            <p className="lp-body-sm pretty" style={{ maxWidth: '46ch' }}>
              Relationships are typed — origin, supports, contradicts, extends — so you can see
              whether the evidence accumulated or split apart.
            </p>
          </div>
          <figure className="art lp-fig">
            <div className="lp-fig-head">
              <span className="lp-label">Lineage · cluster c2</span>
              <span className="lp-fig-meta">1999–2024 · 6 papers</span>
            </div>
            <ol className="lp-chain">
              {CHAIN.map((link) => (
                <li key={link.cite}>
                  <span className={`node node-${link.rel}`} aria-hidden="true" />
                  <div style={{ display: 'flex', gap: 10, alignItems: 'baseline', flexWrap: 'wrap', marginBottom: 5 }}>
                    <span className={`rel rel-${link.rel}`}>{link.rel}</span>
                    <span className="yr">{link.meta}</span>
                  </div>
                  <p className="cite">{link.cite}</p>
                </li>
              ))}
            </ol>
          </figure>
        </div>

        <div className="lp-rule" />

        <div className="lp-row" style={{ paddingBlock: 'clamp(40px, 5vw, 72px)' }}>
          <div className="txt">
            <h3 className="lp-h3">Disagreement</h3>
            <p className="lp-body-sm pretty" style={{ maxWidth: '46ch', marginBottom: 18 }}>
              Spotting a conflict is easy. Nodus records what is driving it. Each cluster gets typed
              disagreement drivers across eight categories, and every driver names the specific
              papers involved.
            </p>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
              {DRIVER_TYPES.map((type) => (
                <span key={type} className="tag tag-outline lp-mono" style={{ fontSize: 11 }}>
                  {type}
                </span>
              ))}
            </div>
          </div>
          <div className="art">
            {DRIVERS.map((driver) => (
              <div key={driver.cat} className="lp-driver">
                <div style={{ display: 'flex', gap: 12, alignItems: 'baseline', flexWrap: 'wrap', marginBottom: 10 }}>
                  <span className="cat">{driver.cat}</span>
                  <span className="pair">{driver.pair}</span>
                </div>
                <p className="lp-body-sm pretty" style={{ fontSize: 15, lineHeight: 1.55 }}>
                  {driver.text}
                </p>
              </div>
            ))}
          </div>
        </div>

        <div className="lp-rule" />

        <div className="lp-row" style={{ paddingBlock: 'clamp(40px, 5vw, 72px)' }}>
          <div className="txt">
            <h3 className="lp-h3">Quality weighting</h3>
            <p className="lp-mono" style={{ fontSize: 12, letterSpacing: '.04em', color: 'var(--l-accent-ink)', margin: '0 0 12px' }}>
              Tiers are arithmetic, not opinion
            </p>
            <p className="lp-body-sm pretty" style={{ maxWidth: '46ch', marginBottom: 12 }}>
              A tier comes from a published formula: study design 40%, sample size 20%,
              corroboration 20%, extraction confidence 20%, minus a conflict penalty of up to 15%.
              No language model rates the evidence.
            </p>
            <p className="lp-body-sm pretty" style={{ maxWidth: '46ch' }}>
              Every input is shown, so you can redo the sum yourself. If you disagree, override the
              tier by hand; the computed value stays on the record next to yours.
            </p>
          </div>
          <figure className="art lp-fig">
            <span className="lp-label" style={{ display: 'block', paddingBottom: 12, borderBottom: '2px solid var(--l-rule)', marginBottom: 18 }}>
              The formula
            </span>
            <div className="lp-mono" style={{ fontSize: 13.5, lineHeight: 1.95, color: 'var(--n-dim)' }}>
              <div>
                <span style={{ color: 'var(--l-accent-ink)', fontWeight: 700 }}>score</span> = 0.40·design
                + 0.20·sample
              </div>
              <div style={{ paddingLeft: '6.5ch' }}>+ 0.20·corroboration</div>
              <div style={{ paddingLeft: '6.5ch' }}>+ 0.20·confidence − penalty</div>
            </div>
            <p className="lp-body-sm" style={{ fontSize: 12.5, lineHeight: 1.6, color: 'var(--n-faint)', margin: '14px 0 0' }}>
              <code className="lp-mono">design</code> is itself 0.6 × the best study design in the
              cluster + 0.4 × the mean, so one strong trial cannot carry a weak cluster on its own.
            </p>
            <span className="lp-label" style={{ display: 'block', margin: '22px 0 0', paddingTop: 18, borderTop: '2px solid var(--l-rule)' }}>
              Thresholds
            </span>
            <div className="lp-tiers">
              <div className="on">
                <span className="k">high</span>
                <span>≥ 0.70</span>
                <span style={{ marginLeft: 'auto', fontSize: 12 }}>this cluster · 0.774</span>
              </div>
              <div>
                <span className="k">medium</span>
                <span>≥ 0.45</span>
              </div>
              <div>
                <span className="k">low</span>
                <span>&lt; 0.45</span>
              </div>
              <div>
                <span className="k">unrated</span>
                <span>no scorable claim</span>
              </div>
            </div>
          </figure>
        </div>
      </section>

      {/* 04 — the pipeline. */}
      <section id="pipeline" className="lp-band lp-band-top">
        <div className="lp-wrap lp-sec">
          <p className="lp-eyebrow">04 — How it works</p>
          <h2 className="lp-h2" style={{ maxWidth: '26ch' }}>
            Three stages, a few minutes
          </h2>
          <p className="lp-body pretty" style={{ maxWidth: '58ch', marginBottom: 44 }}>
            A run streams its progress phase by phase. It is fetching and reading actual papers, so
            expect minutes rather than seconds.
          </p>
          <div className="lp-stages">
            <div>
              <p className="lp-label" style={{ fontFamily: 'var(--font-heading)', fontSize: 13, letterSpacing: '.1em', margin: '0 0 12px', paddingBottom: 12, borderBottom: '2px solid var(--l-rule)' }}>
                Stage 1
              </p>
              <h4 className="lp-h4">Retrieve and rank</h4>
              <p className="lp-body-sm pretty" style={{ marginBottom: 18 }}>
                Around twenty papers come from Semantic Scholar, ranked by a composite score whose
                weights are written down.
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
                  <span>relevance</span>
                  <b>10%</b>
                </div>
              </div>
            </div>
            <div>
              <p className="lp-label" style={{ fontFamily: 'var(--font-heading)', fontSize: 13, letterSpacing: '.1em', margin: '0 0 12px', paddingBottom: 12, borderBottom: '2px solid var(--l-rule)' }}>
                Stage 2
              </p>
              <h4 className="lp-h4">Extract and cluster claims</h4>
              <p className="lp-body-sm pretty" style={{ marginBottom: 18 }}>
                Up to twelve claims per paper are extracted, embedded, and grouped with equivalent
                claims from other papers. The cluster keeps each source claim, its stance, and its
                extraction confidence.
              </p>
              <div className="lp-ledger">
                <div>
                  <span>20 papers</span>
                  <span style={{ color: 'var(--n-faint)' }}>→ up to 240 claims</span>
                </div>
                <div>
                  <span>claims</span>
                  <span style={{ color: 'var(--n-faint)' }}>→ clusters</span>
                </div>
                <div>
                  <span>cluster</span>
                  <span style={{ color: 'var(--n-faint)' }}>→ lineage + drivers + tier</span>
                </div>
              </div>
            </div>
            <div>
              <p className="lp-label" style={{ fontFamily: 'var(--font-heading)', fontSize: 13, letterSpacing: '.1em', margin: '0 0 12px', paddingBottom: 12, borderBottom: '2px solid var(--l-rule)' }}>
                Stage 3
              </p>
              <h4 className="lp-h4">Analyse and synthesise</h4>
              <p className="lp-body-sm pretty" style={{ marginBottom: 18 }}>
                Sections assemble as they finish, each citing the clusters behind it. Follow-up
                questions are scoped to a previous query and linked to their parent, so the
                refinement chain stays inspectable.
              </p>
              <div className="lp-ledger">
                <div>Export → PDF · Markdown · JSON · HTML</div>
                <div style={{ fontFamily: 'var(--font-body)', lineHeight: 1.55, color: 'var(--n-faint)', display: 'block' }}>
                  The PDF is the print variant of the document on screen, so it cannot drift from it.
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* 05 — the override, beside the computation it disagrees with. */}
      <section className="lp-wrap lp-sec lp-row">
        <div style={{ flex: '1 1 320px', minWidth: 0 }}>
          <p className="lp-eyebrow">05 — Human in the loop</p>
          <h2 className="lp-h2" style={{ maxWidth: '24ch' }}>
            Your corrections sit beside the numbers
          </h2>
          <p className="lp-body pretty" style={{ maxWidth: '52ch', marginBottom: 12 }}>
            You know things the formula does not: that a trial's registry entry was amended, that a
            cohort double-counts. Override the tier and give a reason. Both values stay visible.
          </p>
          <p className="lp-body pretty" style={{ maxWidth: '52ch' }}>
            Edited clusters and reports are pinned. Re-analyse the question and your work survives
            instead of being overwritten by the next run.
          </p>
        </div>
        <div
          style={{
            flex: '1 1 420px',
            minWidth: 0,
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
                0.689
              </span>
            </div>
            <p className="lp-mono" style={{ fontSize: 12, lineHeight: 1.7, color: 'var(--n-dim)', margin: 0 }}>
              design 0.72 · sample 0.55
              <br />
              corrob. 0.80 · conf. 0.88
              <br />
              penalty −0.045
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
                Override
              </span>
              <span className="lp-badge-sm" style={{ marginLeft: 'auto' }}>
                pinned
              </span>
            </div>
            <div style={{ display: 'flex', alignItems: 'baseline', gap: 12, marginBottom: 14 }}>
              <span style={{ fontFamily: 'var(--font-heading)', fontWeight: 800, fontSize: 34, lineHeight: 1, letterSpacing: '-.03em', color: 'var(--l-accent-ink)' }}>
                low
              </span>
              <span className="lp-mono" style={{ fontSize: 13, color: 'var(--n-faint)' }}>
                manual
              </span>
            </div>
            <p style={{ fontSize: 12.5, lineHeight: 1.6, color: 'var(--n-dim)', margin: 0 }}>
              “Two of the four corroborating cohorts draw on the same registry — corroboration is
              overstated.”
            </p>
          </figure>
        </div>
      </section>

      {/* 06 — deployment, and the commands that get there. */}
      <section id="deploy" className="lp-band-top">
        <div className="lp-wrap lp-sec lp-row">
          <div className="txt">
            <p className="lp-eyebrow">06 — Deployment and privacy</p>
            <h2 className="lp-h2" style={{ maxWidth: '22ch' }}>
              Runs on your hardware, with your model
            </h2>
            <p className="lp-body pretty" style={{ maxWidth: '52ch', marginBottom: 12 }}>
              Nodus is self-hosted. Papers, claims, clusters and reports live in your own Postgres —
              there is no hosted service holding them.
            </p>
            <p className="lp-body pretty" style={{ maxWidth: '52ch' }}>
              The model is swappable: Gemini, Anthropic, or Ollama. With Ollama the
              whole pipeline runs locally and nothing leaves the machine, which is the configuration
              to use for unpublished or embargoed work.
            </p>
          </div>
          <figure id="quickstart" className="art lp-shell">
            <div className="lp-shell-head">
              <span className="lp-label">Quickstart</span>
              <span className="lp-fig-meta">Python 3.11 · Postgres 15 + pgvector</span>
            </div>
            <div className="lp-shell-body">
              <div className="cm"># clone and install</div>
              <div>
                <span className="pr">$</span> git clone {REPO}.git
              </div>
              <div>
                <span className="pr">$</span> cd nodus-research {'&&'} uv sync --native-tls
              </div>
              <div className="cm cm-gap"># configure the model and the database</div>
              <div>
                <span className="pr">$</span> cp .env.example .env
              </div>
              <div className="env">LLM_PROVIDER=gemini</div>
              <div className="env">EMBEDDING_PROVIDER=gemini</div>
              <div className="env">DATABASE_URL=postgresql+asyncpg://…</div>
              <div className="cm cm-gap"># migrate and serve</div>
              <div>
                <span className="pr">$</span> uv run alembic upgrade head
              </div>
              <div>
                <span className="pr">$</span> uv run uvicorn app.main:app
              </div>
            </div>
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
            Nodus is self-hosted and open. Clone it, read the ranking and quality code, and check the
            arithmetic yourself.
          </p>
          <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', alignItems: 'center' }}>
            <Repo className="btn btn-on-accent" style={{ padding: '13px 22px', fontSize: 15 }}>
              Clone the repository
            </Repo>
            <a
              className="btn btn-off-accent"
              href={README}
              target="_blank"
              rel="noreferrer"
              style={{ padding: '13px 20px', fontSize: 15 }}
            >
              Read the docs
            </a>
          </div>
        </div>
      </section>

      <footer className="lp-wrap" style={{ paddingBlock: 'clamp(36px, 4vw, 56px) 32px' }}>
        <div style={{ maxWidth: 520, paddingBottom: 32 }}>
          {/* The design had an email capture here. There is no list to add an
              address to, and a field that silently discards one is a promise
              the page cannot keep — so it points at the releases feed, which
              is the notification that actually exists. */}
          <p className="lp-body-sm pretty" style={{ fontSize: 14, marginBottom: 14 }}>
            There is no hosted version and no accounts. Releases are published on the repository —{' '}
            <a href={RELEASES} target="_blank" rel="noreferrer">
              watch it
            </a>{' '}
            to hear about new ones.
          </p>
        </div>
        <div className="lp-foot-row">
          <span style={{ display: 'flex', alignItems: 'center', gap: 9 }}>
            <Mark size={22} />
            <span style={{ fontFamily: 'var(--font-heading)', fontWeight: 800, fontSize: 18, letterSpacing: '-.03em', color: 'var(--n-text)' }}>
              Nodus
            </span>
          </span>
          <span>Self-hosted research-paper analysis</span>
          <a href={REPO} target="_blank" rel="noreferrer">
            github.com/raunak-shr/nodus-research
          </a>
          <span style={{ marginLeft: 'auto' }}>Papers via Semantic Scholar</span>
        </div>
      </footer>
    </div>
  )
}

/** A link to the repository. Every "clone" and "source" affordance on the page
 *  goes to the same place, so it is stated once. */
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

/** The mark, solid: two nodes and the edge between them, knocked out of the
 *  accent square. Scales with `size` — 34px in the header, 22px in the footer. */
function Mark({ size }: { size: number }): ReactElement {
  const dot = Math.round(size * 0.21)
  const inset = Math.round(size * 0.18)
  const edge = Math.round(size * 0.56)
  return (
    <span
      aria-hidden="true"
      style={{
        width: size,
        height: size,
        flex: `0 0 ${size}px`,
        background: 'var(--color-accent)',
        position: 'relative',
        display: 'block',
      }}
    >
      <span style={{ position: 'absolute', left: inset, top: inset, width: dot, height: dot, background: 'var(--n-bg)', display: 'block' }} />
      <span style={{ position: 'absolute', right: inset, bottom: inset, width: dot, height: dot, background: 'var(--n-bg)', display: 'block' }} />
      <span
        style={{
          position: 'absolute',
          left: inset + dot / 2,
          top: inset + dot / 2,
          width: edge,
          height: 2,
          background: 'var(--n-bg)',
          transform: 'rotate(45deg)',
          transformOrigin: 'left center',
          display: 'block',
        }}
      />
    </span>
  )
}
