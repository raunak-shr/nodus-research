import { useEffect, useState, type ReactElement } from 'react'

import type { QueryVerdict } from '../lib/types'
import { useStore } from '../state/store'

const EXAMPLES = [
  'Does aerobic exercise reduce depression severity in adults with major depression?',
  'Is exercise good?',
  'Does intermittent fasting improve HbA1c in type 2 diabetes?',
]

const PLACEHOLDER =
  'Ask one question — name the intervention or subject, the outcome, and the population it is measured in.'

/** What the empty box types to itself.
 *
 *  Only well-formed questions: the placeholder is the shape of a good question
 *  demonstrated rather than described, so 'Is exercise good?' — which is in
 *  EXAMPLES on purpose, to show what the Interpret check pushes back on —
 *  has no business here. Each one names an intervention, an outcome and a
 *  population, which is what the sentence under the heading asks for.
 */
const TYPED = [
  'Does aerobic exercise reduce depression severity in adults with major depression?',
  'Does intermittent fasting improve HbA1c in type 2 diabetes?',
  'Does vitamin D supplementation lower fracture risk in adults over 65?',
]

const TYPE_MS = 34
const ERASE_MS = 16
const HOLD_MS = 2100
const GAP_MS = 380

/** Type the phrases out one character at a time, erase, move to the next.
 *
 *  `active` is "the box is empty" — a placeholder nobody can see is not worth
 *  a timer, and stopping means the animation is not competing with the question
 *  someone is in the middle of writing. Returns null when there is nothing to
 *  animate, which is the caller's cue to show the static placeholder instead:
 *  under prefers-reduced-motion this is every render.
 */
function useTypedPlaceholder(phrases: string[], active: boolean): string | null {
  const [reduced] = useState(
    () => window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ?? false,
  )
  const [typed, setTyped] = useState('')

  useEffect(() => {
    if (!active || reduced || phrases.length === 0) return

    let phrase = 0
    let cut = 0
    let erasing = false
    let timer = 0

    const step = (): void => {
      const full = phrases[phrase]
      if (!erasing) {
        cut += 1
        setTyped(full.slice(0, cut))
        erasing = cut >= full.length
        timer = window.setTimeout(step, erasing ? HOLD_MS : TYPE_MS)
        return
      }
      cut -= 1
      setTyped(full.slice(0, cut))
      if (cut > 0) {
        timer = window.setTimeout(step, ERASE_MS)
        return
      }
      erasing = false
      phrase = (phrase + 1) % phrases.length
      timer = window.setTimeout(step, GAP_MS)
    }

    timer = window.setTimeout(step, GAP_MS)
    return () => window.clearTimeout(timer)
  }, [active, phrases, reduced])

  if (!active || reduced) return null
  return typed
}

/** How each verdict is presented. Only `ready` is quiet: the rest are a warning
 *  or a redirection, and none of them is a refusal — every one of these still
 *  leads to a button that runs the question as typed. */
const VERDICTS: Record<QueryVerdict, { kicker: string; headline: string; accent: boolean }> = {
  ready: { kicker: 'worth running', headline: 'This is a question the literature can answer.', accent: false },
  suggested: { kicker: 'nodus suggested this', headline: 'Ready to run.', accent: false },
  workable: { kicker: 'runnable, but loose', headline: 'This will run, and the report will be vague.', accent: true },
  unsuitable: { kicker: 'not worth a run', headline: 'No body of papers answers this one.', accent: true },
  unassessed: { kicker: 'not assessed', headline: 'Nodus could not check this question.', accent: false },
}

export function QueryScreen(): ReactElement {
  const store = useStore()
  const { question, structured, interpretation, interpreting } = store
  const [focused, setFocused] = useState(false)
  const typed = useTypedPlaceholder(TYPED, question.length === 0)

  // The block is what makes it read as typing rather than as text that is
  // already there, so it goes only where there is no real caret to confuse it
  // with: the field's own caret sits at the start of the placeholder, and two
  // cursors in one box is one too many.
  const placeholder =
    typed === null ? PLACEHOLDER : focused ? typed : `${typed}▌`

  return (
    <div style={{ padding: '0 0 90px' }}>
      <div style={{ padding: '104px 88px 0', maxWidth: 940 }}>
        <div className="kicker" style={{ marginBottom: 20 }}>
          New query
        </div>
        <h1
          className="pretty"
          style={{
            fontSize: 38,
            lineHeight: 1.14,
            letterSpacing: '-.02em',
            margin: '0 0 10px',
            maxWidth: 660,
          }}
        >
          Ask one question that a body of literature could answer.
        </h1>
        <p className="dim" style={{ maxWidth: 560, margin: '0 0 34px' }}>
          Nodus retrieves papers, extracts claims, clusters equivalent claims across papers, and
          reports where they agree, where they conflict, and how far each finding can be trusted.
        </p>

        {/* The one thing this screen wants. It is drawn as the loudest element on
            the page — accent edge, 2px frame, a ring when it takes focus — and
            it types an example to itself while it is empty, because the shape of
            a good question is easier to show than to describe. */}
        <div className="ask-box elev-sm">
          <textarea
            className="bare"
            value={question}
            onChange={(event) => store.setQuestion(event.target.value)}
            onFocus={() => setFocused(true)}
            onBlur={() => setFocused(false)}
            placeholder={placeholder}
            rows={3}
            spellCheck={false}
            maxLength={400}
            style={{
              fontSize: 24,
              lineHeight: 1.4,
              letterSpacing: '-.015em',
              padding: '26px 26px 10px',
            }}
          />
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              padding: '10px 18px 16px 26px',
              gap: 12,
              flexWrap: 'wrap',
            }}
          >
            <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
              {EXAMPLES.map((example) => (
                <button
                  key={example}
                  type="button"
                  className="chip-btn"
                  onClick={() => store.setQuestion(example)}
                >
                  {example}
                </button>
              ))}
            </div>
            <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
              <span className="faint num" style={{ fontSize: 11 }}>
                {question.length} / 400
              </span>
              <button
                type="button"
                className="btn btn-primary"
                onClick={() => store.interpret()}
                disabled={question.trim().length < 3 || interpreting}
                style={{ whiteSpace: 'nowrap', fontSize: 13, padding: '8px 16px' }}
              >
                {interpreting ? 'Interpreting…' : 'Interpret'}
              </button>
            </div>
          </div>
        </div>


        {interpreting ? (
          <div className="dim" style={{ marginTop: 30, fontSize: 13.5 }}>
            Reading the question back and checking it against what a literature search can
            answer&hellip;
          </div>
        ) : null}

        {interpretation && !interpreting ? (
          <Verdict />
        ) : null}

        {structured && !interpreting ? (
          <div style={{ marginTop: 34, animation: 'n-in .3s ease both' }}>
            <div style={{ display: 'flex', alignItems: 'baseline', gap: 10, marginBottom: 16 }}>
              <span className="kicker">query_structured</span>
              <span className="faint" style={{ fontSize: 11 }}>
                the structurer&rsquo;s reading of the question
              </span>
            </div>
            <div
              style={{
                display: 'grid',
                gridTemplateColumns: '150px 1fr',
                gap: 1,
                borderTop: '2px solid var(--n-line2)',
                fontSize: 14,
              }}
            >
              <Field label="topic" first>
                {structured.topic}
              </Field>
              <Field label="core_concepts">
                <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                  {(structured.core_concepts ?? []).map((concept) => (
                    <span key={concept} className="tag tag-outline">
                      {concept}
                    </span>
                  ))}
                </div>
              </Field>
              <Field label="search_keywords">
                <span className="dim" style={{ fontSize: 13 }}>
                  {structured.search_keywords.join(' \u00b7 ')}
                </span>
              </Field>
              <Field label="outcome_measure">{structured.outcome_measure ?? 'not fixed'}</Field>
            </div>
          </div>
        ) : null}

        {interpretation && !interpreting ? <RunControls /> : null}

      </div>
    </div>
  )
}

/** The answer to the Interpret button.
 *
 *  It reports and redirects; it never blocks. A person who has read "this will
 *  run, and the report will be vague" and wants to run it anyway is entitled
 *  to — they now know what they are getting, which is the only thing the
 *  button was ever able to give them.
 */
function Verdict(): ReactElement | null {
  const store = useStore()
  const interpretation = store.interpretation
  if (!interpretation) return null

  const { kicker, headline, accent } = VERDICTS[interpretation.verdict]

  return (
    <div
      style={{
        marginTop: 34,
        animation: 'n-in .3s ease both',
        border: '1px solid var(--n-line2)',
        borderLeft: `2px solid ${accent ? 'var(--color-accent)' : 'var(--n-line2)'}`,
        background: 'var(--n-panel)',
        padding: '22px 24px',
        maxWidth: 720,
      }}
    >
      <div
        className="kicker"
        style={{ color: accent ? 'var(--color-accent-400)' : 'var(--n-faint)', marginBottom: 10 }}
      >
        {kicker}
      </div>
      <div style={{ fontSize: 17, lineHeight: 1.45, marginBottom: 8 }}>{headline}</div>
      <p className="dim pretty" style={{ fontSize: 14, margin: 0, lineHeight: 1.55 }}>
        {interpretation.reason}
      </p>

      {interpretation.suggestions.length ? (
        <>
          <div className="kicker" style={{ margin: '22px 0 10px' }}>
            run one of these instead
          </div>
          <div style={{ display: 'flex', flexDirection: 'column' }}>
            {interpretation.suggestions.map((suggestion) => (
              <div key={suggestion} className="suggestion">
                <button
                  type="button"
                  className="suggestion-text pretty"
                  onClick={() => store.useSuggestedQuestion(suggestion)}
                  title="Put this in the box"
                >
                  {suggestion}
                </button>
                <button
                  type="button"
                  className="btn btn-primary suggestion-run"
                  onClick={() => store.startRun(suggestion)}
                >
                  Run
                </button>
              </div>
            ))}
          </div>
          <div className="faint" style={{ fontSize: 11.5, marginTop: 10 }}>
            Run starts the analysis on that question straight away. Clicking the question itself
            puts it in the box instead, still ready to run — Nodus wrote these to be specific
            enough, so neither path asks it to interpret one of its own suggestions.
          </div>
        </>
      ) : null}
    </div>
  )
}

/** Start the run, or go back and change the question.
 *
 *  Which one is the primary button follows the verdict: a question the check
 *  called loose does not get a button styled like the obvious next step, but it
 *  does still get a button.
 */
function RunControls(): ReactElement | null {
  const store = useStore()
  const interpretation = store.interpretation
  if (!interpretation) return null

  const runs = store.config?.runs

  return (
    <div
      style={{
        display: 'flex',
        gap: 12,
        alignItems: 'center',
        marginTop: 26,
        flexWrap: 'wrap',
        animation: 'n-in .3s ease both',
      }}
    >
      <button
        type="button"
        className={interpretation.worth_running ? 'btn btn-primary' : 'btn btn-secondary'}
        onClick={() => store.startRun()}
        style={{
          whiteSpace: 'nowrap',
          fontSize: interpretation.worth_running ? 14 : 13,
          padding: interpretation.worth_running ? '10px 20px' : '8px 16px',
          color: interpretation.worth_running ? undefined : 'var(--n-text)',
          borderColor: interpretation.worth_running ? undefined : 'var(--n-line2)',
        }}
      >
        {interpretation.worth_running ? 'Run analysis' : 'Run it anyway'}
      </button>
      <button
        type="button"
        className="btn btn-ghost dim"
        onClick={store.editQuestion}
        style={{ whiteSpace: 'nowrap', fontSize: 13 }}
      >
        Edit question
      </button>
      <span className="faint" style={{ fontSize: 12, marginLeft: 6 }}>
        ~{store.config?.top_k_papers ?? 20} papers &middot; est. 3&ndash;5 min
        {runs ? ` \u00b7 ${Math.max(0, runs.limit - runs.active)} of ${runs.limit} pipeline slots free` : ''}
      </span>
    </div>
  )
}

function Field({
  label,
  children,
  first = false,
}: {
  label: string
  children: React.ReactNode
  first?: boolean
}): ReactElement {
  const border = first ? undefined : '2px solid var(--n-line2)'
  return (
    <>
      <div
        className="faint"
        style={{ padding: '12px 0', fontSize: 12, letterSpacing: '.04em', borderTop: border }}
      >
        {label}
      </div>
      <div style={{ padding: '12px 0', borderTop: border }}>{children}</div>
    </>
  )
}
