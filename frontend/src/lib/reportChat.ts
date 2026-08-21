/** Answering from the report without a model — the demo and offline path.
 *
 *  `chat.ask` is one LLM call on the server, and with no backend to reach there
 *  is no model here to stand in for it. So this does the one thing that is still
 *  honest: it finds the sentences in the report and its clusters that best match
 *  the question and hands them back as quotations, attributed to the section
 *  they came from. Nothing is generated, nothing is paraphrased, and a question
 *  the report does not touch comes back uncovered rather than smoothed over.
 *
 *  The screen labels these answers as matched rather than written, because a
 *  reader must never have to guess which of the two they are looking at.
 */

import type {
  ChatAnswerRead,
  ChatCitation,
  ChatGrounding,
  ClaimClusterDetail,
  ReportRead,
} from './types'
import { driverView } from './viewmodels'

const STOPWORDS = new Set(
  `a about after again against all also am an and any are as at be because been before being below
   between both but by can could did do does doing down during each few for from further had has
   have having he her here hers him his how i if in into is it its itself just me more most my no
   nor not of off on once only or other our out over own same she should so some such than that the
   their them then there these they this those through to too under until up very was we were what
   when where which while who whom why will with would you your`.split(/\s+/),
)

interface Passage {
  text: string
  citation: ChatCitation
}

function terms(text: string): string[] {
  const words = text.toLowerCase().match(/[a-z0-9][a-z0-9\-']+/g) ?? []
  return [...new Set(words.filter((word) => word.length > 2 && !STOPWORDS.has(word)))]
}

/** Sentence-ish split. Kept crude on purpose: the pieces are quoted verbatim,
 *  so a clumsy boundary costs a reader a few extra words, never accuracy. */
function sentences(text: string | null | undefined): string[] {
  if (!text) return []
  return text
    .split(/(?<=[.!?])\s+(?=[A-Z(])/)
    .map((part) => part.trim())
    .filter((part) => part.length > 24)
}

function passagesFor(report: ReportRead, clusters: ClaimClusterDetail[]): Passage[] {
  const front: ChatCitation = {
    label: 'R',
    kind: 'front_matter',
    heading: report.title,
    cluster_id: null,
  }
  const passages: Passage[] = [
    ...sentences(report.executive_summary).map((text) => ({ text, citation: front })),
    ...(report.key_findings ?? []).map((text) => ({ text, citation: front })),
    ...(report.open_questions ?? []).map((text) => ({ text, citation: front })),
  ]

  const sections = report.sections ?? []
  sections.forEach((section, index) => {
    const citation: ChatCitation = {
      label: `S${index + 1}`,
      kind: 'section',
      heading: section.heading,
      cluster_id: section.cluster_id,
    }
    passages.push({ text: section.central_theme, citation })
    sentences(section.narrative).forEach((text) => passages.push({ text, citation }))
    ;(section.caveats ?? []).forEach((text) => passages.push({ text, citation }))
    ;(section.disagreement_drivers ?? []).forEach((driver) => {
      // `driver_type` on the wire, `type` in the LLM's own output — driverView
      // is what already knows that, and reading the wrong one printed
      // "Papers disagree on undefined" into an answer.
      const view = driverView(driver)
      passages.push({ text: `Papers disagree on ${view.type}: ${view.description}`, citation })
    })
  })

  // Clusters the section cap dropped: still this query's evidence, and the
  // report is silent about them only because it was trimmed.
  const covered = new Set(sections.map((section) => section.cluster_id))
  clusters
    .filter((cluster) => !covered.has(cluster.id))
    .forEach((cluster, index) => {
      const citation: ChatCitation = {
        label: `C${index + 1}`,
        kind: 'cluster',
        heading: cluster.central_theme,
        cluster_id: cluster.id,
      }
      passages.push({ text: cluster.central_theme, citation })
      sentences(cluster.consensus_summary).forEach((text) => passages.push({ text, citation }))
    })

  return passages.filter((passage) => Boolean(passage.text?.trim()))
}

function grounding(report: ReportRead, clusters: ClaimClusterDetail[], sent: number): ChatGrounding {
  const sections = report.sections ?? []
  const covered = new Set(sections.map((section) => section.cluster_id))
  return {
    report_title: report.title,
    sections_total: sections.length,
    clusters_total: clusters.length,
    clusters_without_section: clusters.filter((cluster) => !covered.has(cluster.id)).length,
    blocks_sent: sent,
    truncated: false,
  }
}

const MATCHES = 3

/** The best-matching passages of this report, quoted and attributed. */
export function answerFromReport(
  question: string,
  report: ReportRead,
  clusters: ClaimClusterDetail[],
): ChatAnswerRead {
  const asked = terms(question)
  const scored = passagesFor(report, clusters)
    .map((passage) => {
      const haystack = `${passage.citation.heading} ${passage.text}`.toLowerCase()
      return { passage, score: asked.filter((term) => haystack.includes(term)).length }
    })
    .filter((entry) => entry.score > 0)
    .sort((a, b) => b.score - a.score)

  const base = {
    query_id: report.query_id,
    question,
    llm_model_used: null,
  }

  if (scored.length === 0) {
    const headings = (report.sections ?? []).map((section) => section.heading)
    return {
      ...base,
      covered: false,
      answer:
        'Nothing in this report matches that question. What it does cover: ' +
        (headings.length ? `${headings.slice(0, 4).join('; ')}.` : 'no sections at all.') +
        '\n\nAsking it something the papers behind it never measured needs a new run, not this thread.',
      citations: [],
      grounding: grounding(report, clusters, 0),
    }
  }

  const kept = scored.slice(0, MATCHES)
  const citations: ChatCitation[] = []
  kept.forEach((entry) => {
    if (!citations.some((citation) => citation.label === entry.passage.citation.label)) {
      citations.push(entry.passage.citation)
    }
  })

  return {
    ...base,
    covered: true,
    answer: kept
      .map((entry) => `${entry.passage.text.trim()} [${entry.passage.citation.label}]`)
      .join('\n\n'),
    citations,
    grounding: grounding(report, clusters, citations.length),
  }
}
