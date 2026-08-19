import type { ReactElement } from 'react'

import { useStore } from '../state/store'

const EXAMPLES = [
  'Does aerobic exercise reduce depression severity?',
  'Is exercise good?',
  'Does intermittent fasting improve HbA1c in type 2 diabetes?',
]

export function QueryScreen(): ReactElement {
  const store = useStore()
  const { question, structured, clarify } = store

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

        <div
          className="elev-sm"
          style={{
            border: '1px solid var(--n-line2)',
            background: 'var(--n-panel)',
            padding: 2,
          }}
        >
          <textarea
            className="bare"
            value={question}
            onChange={(event) => store.setQuestion(event.target.value)}
            rows={2}
            spellCheck={false}
            maxLength={400}
            style={{
              fontSize: 22,
              lineHeight: 1.4,
              letterSpacing: '-.01em',
              padding: '20px 22px 8px',
            }}
          />
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              padding: '10px 16px 12px 22px',
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
                  onClick={() => {
                    store.setQuestion(example)
                    store.editQuestion()
                  }}
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
                onClick={store.interpret}
                disabled={question.trim().length < 3}
                style={{ whiteSpace: 'nowrap', fontSize: 13, padding: '8px 16px' }}
              >
                Interpret
              </button>
            </div>
          </div>
        </div>

        {structured && !clarify ? (
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
                  {structured.search_keywords.join(' · ')}
                </span>
              </Field>
              <Field label="outcome_measure">{structured.outcome_measure ?? 'not fixed'}</Field>
            </div>
            <div style={{ display: 'flex', gap: 12, alignItems: 'center', marginTop: 26, flexWrap: 'wrap' }}>
              <button
                type="button"
                className="btn btn-primary"
                onClick={store.startRun}
                style={{ whiteSpace: 'nowrap', fontSize: 14, padding: '10px 20px' }}
              >
                Run analysis
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
                ~{store.config?.top_k_papers ?? 20} papers · est. 3–5 min
                {store.config
                  ? ` · ${Math.max(0, store.config.runs.limit - store.config.runs.active)} of ${store.config.runs.limit} pipeline slots free`
                  : ''}
              </span>
            </div>
          </div>
        ) : null}

        {clarify ? (
          <div
            style={{
              marginTop: 34,
              animation: 'n-in .3s ease both',
              border: '1px solid var(--n-line2)',
              borderLeft: '2px solid var(--color-accent)',
              background: 'var(--n-panel)',
              padding: '22px 24px',
              maxWidth: 720,
            }}
          >
            <div
              className="kicker"
              style={{ color: 'var(--color-accent-400)', marginBottom: 10 }}
            >
              clarification_needed
            </div>
            <div style={{ fontSize: 17, lineHeight: 1.45, marginBottom: 6 }}>
              “{question.trim() || 'That'}” is too broad to retrieve against.
            </div>
            <p className="dim" style={{ fontSize: 14, margin: '0 0 18px' }}>
              The structurer could not fix an outcome measure or a population. It will still run, but
              ranking will be near-random and clusters will mix unrelated endpoints. Three things
              would fix it:
            </p>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 10, marginBottom: 20 }}>
              <Numbered n="01">Name the outcome — mortality, depression severity, VO₂max?</Numbered>
              <Numbered n="02">
                Name the population — adults with a diagnosis, athletes, older adults?
              </Numbered>
              <Numbered n="03">
                Name the exposure — aerobic, resistance, any physical activity?
              </Numbered>
            </div>
            <div style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap' }}>
              <button
                type="button"
                className="btn btn-primary"
                onClick={() => store.useSuggestedQuestion('Does aerobic exercise reduce depression severity?')}
                style={{ whiteSpace: 'nowrap', fontSize: 13 }}
              >
                Use “Does aerobic exercise reduce depression severity?”
              </button>
              <button
                type="button"
                className="btn btn-ghost dim"
                onClick={store.startRun}
                style={{ whiteSpace: 'nowrap', fontSize: 13 }}
              >
                Run anyway
              </button>
            </div>
          </div>
        ) : null}
      </div>
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

function Numbered({ n, children }: { n: string; children: React.ReactNode }): ReactElement {
  return (
    <div style={{ display: 'flex', gap: 10, fontSize: 14 }}>
      <span className="faint num">{n}</span>
      <span>{children}</span>
    </div>
  )
}
