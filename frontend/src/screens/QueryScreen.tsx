import { useRef, useEffect, useState, type ReactElement } from 'react'

import type { QueryVerdict } from '../lib/types'
import { resolveSocketUrl } from '../lib/ws'
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
          Nodus extracts claims, clusters equivalent claims across papers, and reports where they
          agree, where they conflict, and how far each finding can be trusted. Retrieve the
          literature, or hand it your own PDFs.
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
              {/* Only on the search path. Interpret judges a question against
                  what a literature *search* can answer, and an uploaded corpus
                  was not searched for — the verdict would be about a retrieval
                  that is not going to happen. */}
              {store.paperSource === 'search' ? (
                <button
                  type="button"
                  className="btn btn-primary"
                  onClick={() => store.interpret()}
                  disabled={question.trim().length < 3 || interpreting}
                  style={{ whiteSpace: 'nowrap', fontSize: 13, padding: '8px 16px' }}
                >
                  {interpreting ? 'Interpreting…' : 'Interpret'}
                </button>
              ) : null}
            </div>
          </div>
        </div>


        <PaperSource />

        {store.paperSource === 'upload' ? <UploadPanel /> : null}

        {store.paperSource === 'search' && interpreting ? (
          <div className="dim" style={{ marginTop: 30, fontSize: 13.5 }}>
            Reading the question back and checking it against what a literature search can
            answer&hellip;
          </div>
        ) : null}

        {store.paperSource === 'search' && interpretation && !interpreting ? (
          <Verdict />
        ) : null}

        {store.paperSource === 'search' && structured && !interpreting ? (
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

        {store.paperSource === 'search' && interpretation && !interpreting ? (
          <RunControls />
        ) : null}

      </div>
    </div>
  )
}

/** Which corpus this question gets run against.
 *
 *  Two tabs rather than a dropdown, because the choice changes the whole rest
 *  of the screen: search leads to Interpret and a structured reading, upload
 *  leads to a drop zone and no retrieval step at all.
 */
function PaperSource(): ReactElement {
  const store = useStore()
  const ready = store.uploads.filter((file) => file.status === 'ready').length
  const max = store.config?.upload_max_papers ?? 20

  return (
    <div style={{ marginTop: 32 }}>
      <div className="kicker" style={{ marginBottom: 12 }}>
        Papers from
      </div>
      <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
        <button
          type="button"
          className={`src-tab${store.paperSource === 'search' ? ' on' : ''}`}
          onClick={() => store.setPaperSource('search')}
        >
          Search the literature
        </button>
        <button
          type="button"
          className={`src-tab${store.paperSource === 'upload' ? ' on' : ''}`}
          onClick={() => store.setPaperSource('upload')}
          // Still clickable when the server cannot take files: the panel behind
          // it is where the reason lives, and a dead tab explains nothing.
          title={store.uploadsSupported === false ? 'This backend does not accept uploads' : undefined}
        >
          <span>Use my own PDFs</span>
          <span className="count">
            {store.uploadsSupported === false ? 'unavailable' : `${ready} / ${max}`}
          </span>
        </button>
      </div>

      {store.paperSource === 'search' && !store.interpretation && !store.interpreting ? (
        <div
          style={{
            marginTop: 26,
            borderTop: '2px solid var(--n-line2)',
            paddingTop: 18,
            maxWidth: 640,
            animation: 'n-in .3s ease both',
          }}
        >
          <div className="dim" style={{ fontSize: 14, lineHeight: 1.5 }}>
            Nodus will structure the question into topic, concepts, keywords and an outcome measure
            before it retrieves anything. Press Interpret to see that structure, or edit the
            question first.
          </div>
        </div>
      ) : null}
    </div>
  )
}

/** The drop zone, the queue, and the one button that starts an upload run.
 *
 *  Every refusal keeps its file in the list with the reason attached. A file
 *  that disappears when it is refused is a file the reader drops again — and
 *  the reasons here are all actionable ones (too long, not a PDF, no text
 *  layer), so they are worth reading rather than clearing away.
 */
function UploadPanel(): ReactElement {
  const store = useStore()
  const [over, setOver] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)

  // Asked once, before a single file is chosen. Finding this out per file is
  // what turns one answerable fact — this server cannot take uploads — into a
  // list of identical protocol errors, one per paper, with no way to act on
  // any of them.
  if (store.uploadsSupported === null) {
    return (
      <div className="dim" style={{ marginTop: 26, fontSize: 13.5 }}>
        Waiting for the server to say what it can do&hellip;
      </div>
    )
  }
  if (store.uploadsSupported === false) return <UploadsUnavailable />

  const ready = store.uploads.filter((file) => file.status === 'ready')
  const rejected = store.uploads.filter((file) => file.status === 'rejected')
  // Pages *read*, not pages held: that is what the run will actually see, and
  // it is the number the note beside the button is promising.
  const pages = ready.reduce((total, file) => total + (file.pagesRead || file.pages), 0)
  const maxPapers = store.config?.upload_max_papers ?? 20
  const maxPages = store.config?.upload_max_pages ?? 10
  const minPapers = store.config?.upload_min_papers ?? 2
  const runnable = ready.length >= minPapers && !store.uploading && asked(store).length > 0

  const note = store.uploading
    ? 'reading the files…'
    : ready.length < minPapers
      ? `Add at least ${minPapers} papers to run — clustering compares claims across papers.`
      : !asked(store)
        ? 'Write the question above, then run.'
        : `${ready.length} papers · ${pages} pages · no retrieval step`

  return (
    <div style={{ marginTop: 26, animation: 'n-in .3s ease both' }}>
      <div
        className={`drop-zone${over ? ' over' : ''}`}
        onDragOver={(event) => {
          event.preventDefault()
          if (!over) setOver(true)
        }}
        onDragLeave={() => setOver(false)}
        onDrop={(event) => {
          event.preventDefault()
          setOver(false)
          store.addUploads(event.dataTransfer.files)
        }}
      >
        <div>
          <div style={{ fontSize: 17, letterSpacing: '-.01em', marginBottom: 6 }}>
            Drop PDFs here
          </div>
          <div className="faint" style={{ fontSize: 12.5 }}>
            {maxPapers} papers max · up to {maxPages} pages each · the first{' '}
            {store.config?.max_pages_read ?? 10} pages of each are read, and a row says so when
            that is less than the whole paper
          </div>
        </div>
        <label className="drop-pick">
          <input
            ref={inputRef}
            type="file"
            accept="application/pdf,.pdf"
            multiple
            onChange={(event) => {
              if (event.target.files) store.addUploads(event.target.files)
              // Cleared so re-picking the same file fires `change` again.
              event.target.value = ''
            }}
          />
          Choose files
        </label>
      </div>

      {store.uploads.length ? (
        <div style={{ marginTop: 24, border: '1px solid var(--n-line2)', background: 'var(--n-panel)' }}>
          <div
            style={{
              display: 'flex',
              alignItems: 'baseline',
              justifyContent: 'space-between',
              gap: 16,
              padding: '12px 16px',
              borderBottom: '2px solid var(--n-line2)',
            }}
          >
            <div
              className="faint"
              style={{ display: 'flex', gap: 22, alignItems: 'baseline', fontSize: 12 }}
            >
              <span>
                accepted{' '}
                <span
                  className="num"
                  style={{
                    color: ready.length >= maxPapers ? 'var(--color-accent)' : 'var(--n-text)',
                  }}
                >
                  {ready.length} / {maxPapers}
                </span>
              </span>
              <span>
                pages read{' '}
                <span className="num" style={{ color: 'var(--n-text)' }}>
                  {pages}
                </span>
              </span>
              <span>
                refused{' '}
                <span className="num" style={{ color: 'var(--n-text)' }}>{rejected.length}</span>
              </span>
            </div>
            <button type="button" className="upload-drop" onClick={store.clearUploads}>
              Clear all
            </button>
          </div>
          <div className="n-scroll" style={{ maxHeight: 290, overflowY: 'auto', padding: '0 16px' }}>
            {store.uploads.map((file) => (
              <div key={file.key} className={`upload-row ${file.status}`}>
                <div style={{ minWidth: 0 }}>
                  <div
                    style={{
                      fontSize: 14,
                      overflow: 'hidden',
                      textOverflow: 'ellipsis',
                      whiteSpace: 'nowrap',
                    }}
                  >
                    {file.name}
                  </div>
                  {file.reason ? (
                    <div className="faint" style={{ fontSize: 11.5, marginTop: 3 }}>
                      {file.reason}
                    </div>
                  ) : null}
                </div>
                <div className="dim num" style={{ fontSize: 12 }}>
                  {size(file.size)}
                  {file.pages ? ` · ${file.pages} page${file.pages === 1 ? '' : 's'}` : ''}
                </div>
                <div className="status">
                  {file.status === 'checking' ? 'reading' : file.status}
                </div>
                <button
                  type="button"
                  className="upload-drop"
                  title="Remove"
                  onClick={() => store.removeUpload(file.key)}
                >
                  ×
                </button>
              </div>
            ))}
          </div>
        </div>
      ) : null}

      <div style={{ display: 'flex', gap: 14, alignItems: 'center', marginTop: 24, flexWrap: 'wrap' }}>
        <button
          type="button"
          className="btn btn-primary"
          onClick={store.runUploads}
          disabled={!runnable}
          style={{
            whiteSpace: 'nowrap',
            fontSize: 14,
            padding: '10px 20px',
            ...(runnable ? {} : { opacity: 0.45 }),
          }}
        >
          Run on my papers
        </button>
        <span className="faint" style={{ fontSize: 12 }}>
          {note}
        </span>
      </div>
    </div>
  )
}

/** The server on the other end cannot take files.
 *
 *  Either it is older than `papers.upload` — which is what a frontend pointed
 *  at a deployment that has not been updated yet is talking to — or uploads are
 *  switched off on it. Both are the same fact to a reader, and the useful thing
 *  is to name the connection, because the fix is almost always to point it
 *  somewhere else.
 */
function UploadsUnavailable(): ReactElement {
  const store = useStore()
  const demo = store.mode === 'demo'

  return (
    <div
      style={{
        marginTop: 26,
        border: '1px solid var(--n-line2)',
        borderLeft: '2px solid var(--color-accent)',
        background: 'var(--n-panel)',
        padding: '22px 24px',
        maxWidth: 720,
        animation: 'n-in .3s ease both',
      }}
    >
      <div className="kicker" style={{ color: 'var(--color-accent-400)', marginBottom: 10 }}>
        uploads unavailable here
      </div>
      <div style={{ fontSize: 17, lineHeight: 1.45, marginBottom: 8 }}>
        {demo
          ? 'The demo corpus has no server to upload to.'
          : 'The backend this app is connected to does not accept uploaded papers.'}
      </div>
      <p className="dim pretty" style={{ fontSize: 14, margin: 0, lineHeight: 1.55 }}>
        {demo
          ? 'Demo mode runs on a fixture corpus with no socket open, so there is nothing to hand a file to. Point the app at a backend to run over your own PDFs.'
          : 'Either it is running a build from before uploads existed, or UPLOADS_ENABLED is off on it. Search the literature instead, or point the app at a backend that offers papers.upload.'}
      </p>
      {!demo ? (
        <div className="faint num" style={{ fontSize: 11.5, marginTop: 16, lineHeight: 1.6 }}>
          connected to {socketOrigin()}
        </div>
      ) : null}
    </div>
  )
}

/** Where this app is actually pointed — the one thing worth printing here.
 *
 *  A frontend run locally against the hosted deployment looks exactly like a
 *  local backend until something it does not have is asked for.
 */
function socketOrigin(): string {
  try {
    return new URL(resolveSocketUrl()).host
  } catch {
    return 'an unknown host'
  }
}

function asked(store: ReturnType<typeof useStore>): string {
  return store.question.trim()
}

function size(bytes: number): string {
  return bytes > 1_048_576
    ? `${(bytes / 1_048_576).toFixed(1)} MB`
    : `${Math.max(1, Math.round(bytes / 1024))} kB`
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
