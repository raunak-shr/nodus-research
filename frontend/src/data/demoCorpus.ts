/** The demo corpus: one finished run, shaped exactly like the API returns it.
 *
 *  It exists so every screen — including the failure and degenerate states — can
 *  be read without a backend, and so the UI is developed against the same types
 *  the socket delivers. Nothing here is inferred at render time; the fixtures
 *  carry the provenance, quality arithmetic and lineage the pipeline would.
 */

import type {
  ClaimClusterDetail,
  ClaimSourceFields,
  ClaimSourceRead,
  ClusterClaimRead,
  QualityRationale,
} from '../lib/types'

export const DEMO_QUERY_ID = '8f2c4100-0000-4000-8000-000000000001'

export interface DemoPaper {
  id: string
  rank: number
  score: number
  title: string
  authors: string
  year: number
  journal: string
  type: string
  method: string
  n: number
  claims: number
  cites: number
}

export const DEMO_PAPERS: DemoPaper[] = [
  { id: 'p01', rank: 1, score: 0.94, title: 'Exercise and Pharmacotherapy in the Treatment of Major Depressive Disorder', authors: 'Blumenthal, Babyak, Doraiswamy et al.', year: 2007, journal: 'Psychosomatic Medicine', type: 'RCT', method: '4-arm parallel RCT, supervised aerobic exercise vs sertraline vs home exercise vs placebo, 16 wk, HAM-D', n: 202, claims: 9, cites: 1204 },
  { id: 'p02', rank: 2, score: 0.92, title: 'Exercise for depression', authors: 'Cooney, Dwan, Greig et al.', year: 2013, journal: 'Cochrane Database of Systematic Reviews', type: 'Systematic review', method: '39 trials, random-effects meta-analysis, risk-of-bias restricted sensitivity analysis', n: 2326, claims: 12, cites: 2410 },
  { id: 'p03', rank: 3, score: 0.91, title: 'Exercise as a treatment for depression: a meta-analysis adjusting for publication bias', authors: 'Schuch, Vancampfort, Richards et al.', year: 2016, journal: 'Journal of Psychiatric Research', type: 'Meta-analysis', method: '25 RCTs, trim-and-fill and PET-PEESE adjustment for small-study effects', n: 1487, claims: 11, cites: 1866 },
  { id: 'p04', rank: 4, score: 0.89, title: 'Exercise for patients with major depression: a systematic review with meta-analysis and trial sequential analysis', authors: 'Krogh, Hjorthøj, Speyer et al.', year: 2017, journal: 'BMJ Open', type: 'Systematic review', method: '35 trials, trial sequential analysis, blinded-outcome subgroup', n: 2498, claims: 10, cites: 512 },
  { id: 'p05', rank: 5, score: 0.87, title: 'Exercise treatment for depression: efficacy and dose response', authors: 'Dunn, Trivedi, Kampert et al.', year: 2005, journal: 'American Journal of Preventive Medicine', type: 'Dose-response RCT', method: '5-arm RCT of energy expenditure 7.0 vs 17.5 kcal/kg/wk at 3 or 5 days/wk', n: 80, claims: 8, cites: 930 },
  { id: 'p06', rank: 6, score: 0.86, title: 'Effectiveness of physical activity interventions for improving depression, anxiety and distress', authors: 'Singh, Olds, Curtis et al.', year: 2023, journal: 'British Journal of Sports Medicine', type: 'Umbrella review', method: '97 reviews of 1039 trials, median effect pooling across populations', n: 128119, claims: 12, cites: 704 },
  { id: 'p07', rank: 7, score: 0.86, title: 'Effect of exercise for depression: systematic review and network meta-analysis of randomised controlled trials', authors: 'Noetel, Sanders, Gallardo-Gómez et al.', year: 2024, journal: 'BMJ', type: 'Network meta-analysis', method: '218 trials, arm-level network model by modality and intensity, GRADE', n: 14170, claims: 12, cites: 389 },
  { id: 'p08', rank: 8, score: 0.81, title: 'Exercise and pharmacotherapy in patients with major depression: one-year follow-up of the SMILE study', authors: 'Hoffman, Babyak, Craighead et al.', year: 2011, journal: 'Psychosomatic Medicine', type: 'RCT follow-up', method: '12-month naturalistic follow-up of the SMILE cohort, self-reported activity', n: 202, claims: 7, cites: 411 },
  { id: 'p09', rank: 9, score: 0.8, title: 'The antidepressive effects of exercise: a meta-analysis of randomized trials', authors: 'Rethorst, Wipfli, Landers', year: 2009, journal: 'Sports Medicine', type: 'Meta-analysis', method: '58 trials, moderator analysis by duration, frequency and supervision', n: 2325, claims: 9, cites: 1052 },
  { id: 'p10', rank: 10, score: 0.78, title: 'Physical exercise intervention in depressive disorders: meta-analysis and systematic review', authors: 'Josefsson, Lindwall, Archer', year: 2014, journal: 'Scandinavian Journal of Medicine & Science in Sports', type: 'Meta-analysis', method: '13 RCTs restricted to clinical diagnosis and no-treatment controls', n: 977, claims: 8, cites: 688 },
  { id: 'p11', rank: 11, score: 0.77, title: 'Exercise as a treatment for depression: a meta-analysis', authors: 'Kvam, Kleppe, Nordhus, Hovland', year: 2016, journal: 'Journal of Affective Disorders', type: 'Meta-analysis', method: '23 RCTs, comparison against antidepressants and combined treatment arms', n: 977, claims: 9, cites: 920 },
  { id: 'p12', rank: 12, score: 0.75, title: 'Physical exercise for late-life major depression', authors: 'Belvederi Murri, Amore, Menchetti et al.', year: 2015, journal: 'British Journal of Psychiatry', type: 'RCT', method: 'Sertraline plus progressive aerobic exercise in adults 65+, 24 wk, HAM-D', n: 121, claims: 8, cites: 266 },
  { id: 'p13', rank: 13, score: 0.72, title: 'Moderate exercise improves depression parameters in treatment-resistant patients with major depressive disorder', authors: 'Mota-Pereira, Silverio, Carvalho et al.', year: 2011, journal: 'Journal of Psychiatric Research', type: 'RCT', method: 'Adjunct 30–45 min walking 5 days/wk added to stable pharmacotherapy', n: 33, claims: 6, cites: 298 },
  { id: 'p14', rank: 14, score: 0.71, title: 'Facilitated physical activity as a treatment for depressed adults: randomised controlled trial (TREAD)', authors: 'Chalder, Wiles, Campbell et al.', year: 2012, journal: 'BMJ', type: 'Pragmatic RCT', method: 'Primary-care activity facilitation plus usual care, blinded BDI at 4 months', n: 361, claims: 9, cites: 479 },
  { id: 'p15', rank: 15, score: 0.69, title: 'The effect of exercise in clinically depressed adults (the DEMO trial)', authors: 'Krogh, Saltin, Gluud, Nordentoft', year: 2009, journal: 'Journal of Clinical Psychiatry', type: 'RCT', method: 'Aerobic vs relaxation, 4 months, blinded HAM-D₁₇ assessors', n: 165, claims: 7, cites: 342 },
  { id: 'p16', rank: 16, score: 0.66, title: 'Physical exercise and internet-based cognitive–behavioural therapy in the treatment of depression', authors: 'Hallgren, Kraepelien, Öjehagen et al.', year: 2015, journal: 'British Journal of Psychiatry', type: 'RCT', method: 'Three-arm: exercise vs iCBT vs treatment as usual, 12 wk, MADRS-S', n: 946, claims: 8, cites: 301 },
  { id: 'p17', rank: 17, score: 0.63, title: 'Aerobic exercise or basic body awareness therapy for patients with major depression', authors: 'Danielsson, Papoulias, Petersson et al.', year: 2014, journal: 'Journal of Affective Disorders', type: 'RCT', method: '10-week physiotherapy-led aerobic arm vs body awareness vs advice only', n: 62, claims: 6, cites: 157 },
  { id: 'p18', rank: 18, score: 0.58, title: 'Exercise leads to better clinical outcomes in those receiving medication plus cognitive behavioural therapy', authors: 'Gourgouvelis, Yielder, Clarke et al.', year: 2018, journal: 'Frontiers in Psychiatry', type: 'Quasi-experimental', method: 'Non-randomised allocation to 8-week exercise adjunct, BDI-II and BDNF', n: 16, claims: 5, cites: 88 },
  { id: 'p19', rank: 19, score: 0.55, title: 'Exercise is an effective treatment for positive valence symptoms in major depression', authors: 'Toups, Carmody, Greer et al.', year: 2017, journal: 'Journal of Affective Disorders', type: 'RCT secondary analysis', method: 'Secondary endpoint analysis of the TREAD-US dose trial, positive valence items', n: 122, claims: 6, cites: 96 },
  { id: 'p20', rank: 20, score: 0.52, title: 'Aerobic exercise or stretching as add-on to inpatient treatment of depression', authors: 'Imboden, Gerber, Beck et al.', year: 2020, journal: 'Journal of Affective Disorders', type: 'RCT', method: 'Inpatient 6-week aerobic vs stretching add-on, HAM-D and actigraphy', n: 42, claims: 5, cites: 74 },
]

/** Papers the run could not read. The report is built on the rest and says so. */
export const DEMO_FAILURES: Record<string, string> = {
  p05: 'PDF unreachable — publisher returned 403 twice',
  p12: 'Two-column scan; text layer unparseable',
  p18: 'Paywalled: abstract only, below claim threshold',
}

export const DEMO_SECTION_HEADINGS = [
  'Aerobic exercise produces a moderate reduction in depression severity',
  'Effect sizes shrink in trials with blinded outcome assessment',
  'Three or more sessions per week outperforms lower frequency',
  'Effects in adults over 65 are comparable to younger cohorts',
  'Exercise as an adjunct in treatment-resistant depression',
  'Attrition weakens twelve-month follow-up estimates',
]

// -- provenance -------------------------------------------------------------

interface DemoProv {
  match: ClaimSourceFields['source_match']
  origin: ClaimSourceFields['source_origin']
  section: string | null
  page: number | null
  pdf: boolean
  available: boolean
  quote: string
  reason?: string
  /** [before, quote, after] — the panel highlights by offset, never by search. */
  ctx?: [string, string, string]
}

const PROV: Record<string, DemoProv> = {
  cl_1042: {
    match: 'exact', origin: 'full_text', section: 'results', page: 4, pdf: true, available: true,
    quote: 'Remission rates were 45% in the supervised aerobic exercise group and 47% in the sertraline group at 16 weeks.',
    ctx: [
      'At the end of the 16-week intervention period, HAM-D scores had fallen in all three active conditions. ',
      'Remission rates were 45% in the supervised aerobic exercise group and 47% in the sertraline group at 16 weeks.',
      ' The placebo condition reached 31%, a difference that did not reach significance against either active arm.',
    ],
  },
  cl_1188: {
    match: 'normalized', origin: 'full_text', section: 'results', page: 6, pdf: true, available: true,
    quote: 'The overall effect of exercise on depression across the 58 included trials was large (d = −0.80).',
    ctx: [
      'Random-effects pooling was performed on all trials reporting a continuous depression outcome. ',
      'The  overall  effect of exercise on depression across the 58 included trials\nwas LARGE (d = −0.80).',
      ' Restricting to trials with a non-exercise control condition attenuated the estimate only slightly.',
    ],
  },
  cl_1301: {
    match: 'exact', origin: 'full_text', section: 'conclusion', page: 2, pdf: true, available: true,
    quote: 'Exercise is moderately more effective than a control intervention for reducing symptoms of depression (SMD −0.62).',
    ctx: [
      'Twenty-five of the thirty-nine included trials contributed to the primary comparison. ',
      'Exercise is moderately more effective than a control intervention for reducing symptoms of depression (SMD −0.62).',
      ' Sensitivity analyses restricted to trials at low risk of bias reduced this figure substantially.',
    ],
  },
  cl_1466: {
    match: 'fuzzy', origin: 'full_text', section: 'results', page: 9, pdf: true, available: true,
    quote: 'after trim-and-fill adjustment the pooled SMD was −0.62 (95% CI −0.81 to −0.42)',
    reason: 'Located by fuzzy match, so the span boundaries are approximate — the extracted text ran two lines together here and the highlight may end past the sentence. Check the page before quoting.',
    ctx: [
      'Funnel plot asymmetry was present for the primary outcome, and ',
      'after trim-and-fill adjustment the pooled SMD was −0.62 (95% CI −0.81 to −0.42). PET-PEESE produced a',
      ' comparable estimate, indicating the effect is not an artefact of small-study bias alone.',
    ],
  },
  cl_1902: {
    match: 'normalized', origin: 'full_text', section: 'results', page: 11, pdf: true, available: true,
    quote: 'Walking or jogging produced a moderate reduction in depression versus active control (SMD −0.62).',
    ctx: [
      'Node-level estimates from the network model ranked exercise modalities against active control conditions. ',
      'Walking or jogging produced a moderate reduction in depression\nversus active control (SMD −0.62).',
      ' Yoga and strength training showed comparable point estimates with wider credible intervals.',
    ],
  },
  cl_1204: {
    match: 'exact', origin: 'full_text', section: 'results', page: 5, pdf: true, available: true,
    quote: 'The difference in blinded HAM-D₁₇ score between aerobic exercise and relaxation at four months was 0.4 points (p = 0.79).',
    ctx: [
      'The primary outcome was assessed by raters blind to allocation. ',
      'The difference in blinded HAM-D₁₇ score between aerobic exercise and relaxation at four months was 0.4 points (p = 0.79).',
      ' Unblinded self-report measures favoured exercise over the same interval.',
    ],
  },
  cl_1288: {
    match: 'exact', origin: 'full_text', section: 'results', page: 7, pdf: true, available: true,
    quote: 'There was no evidence of improvement in blinded BDI score at four months in the intervention group compared with usual care alone.',
    ctx: [
      'Three hundred and sixty-one participants were randomised and followed for twelve months. ',
      'There was no evidence of improvement in blinded BDI score at four months in the intervention group compared with usual care alone.',
      ' Self-reported physical activity did increase in the intervention arm, indicating the intervention was delivered as intended.',
    ],
  },
  cl_1312: {
    match: 'exact', origin: 'full_text', section: 'results', page: 14, pdf: true, available: true,
    quote: 'When we restricted analysis to trials with adequate allocation concealment, blinding of outcome assessment and intention-to-treat analysis, the pooled SMD fell to −0.18.',
    ctx: [
      'Risk of bias was assessed across six domains. ',
      'When we restricted analysis to trials with adequate allocation concealment, blinding of outcome assessment and intention-to-treat analysis, the pooled SMD fell to −0.18.',
      ' Only four trials met all three criteria, so this estimate is imprecise.',
    ],
  },
  cl_1590: {
    match: 'fuzzy', origin: 'full_text', section: 'methods', page: 3, pdf: true, available: true,
    quote: 'trial sequential analysis did not reach the required information size and could not exclude a null effect',
    reason: 'Located by fuzzy match, so the span boundaries are approximate — the sentence is broken by a figure caption in the extracted text and the highlight may run past its end. Check the page before quoting.',
    ctx: [
      'We applied trial sequential analysis to the blinded-outcome subset to establish whether the accumulated evidence was conclusive. The cumulative Z-curve did not cross the monitoring boundary: ',
      'trial sequential analysis did not reach the required information size and could not exclude a null effect. Further adequately',
      ' blinded trials are therefore required.',
    ],
  },
  cl_1470: {
    match: 'normalized', origin: 'full_text', section: 'discussion', page: 12, pdf: true, available: true,
    quote: 'Bias-adjusted pooling retained a moderate effect (SMD −0.62), so assessor blinding alone does not explain the estimate away.',
    ctx: [
      'Our adjustment methods address small-study effects directly rather than by exclusion. ',
      'Bias-adjusted pooling retained a moderate effect (SMD −0.62), so assessor\nblinding alone does NOT explain the estimate away.',
      ' We regard restriction to four blinded trials as discarding usable information.',
    ],
  },
  cl_1911: {
    match: 'none', origin: 'full_text', section: 'discussion', page: null, pdf: false, available: false,
    quote: 'Effects persisted after controlling for risk of bias, although certainty of evidence was rated low to moderate.',
    reason: 'No open-access full text. The publisher copy is paywalled, so only the abstract and reference metadata were retrieved and there is no paragraph to point at.',
  },
  cl_1655: {
    match: 'normalized', origin: 'abstract', section: null, page: null, pdf: false, available: false,
    quote: 'Blinded subgroups comprise few and small trials, and their smaller pooled effect lies within sampling error of the full pool.',
    reason: 'Quoted from the abstract. The paper body was never available, so there is no page and no surrounding paragraph.',
  },
}

/** Claims outside the hand-written set still need provenance, and it has to be
 *  stable across renders — so it is derived from the id, not randomised. */
function derivedProv(claimId: string, claimText: string): DemoProv {
  const hash = [...claimId].reduce((total, ch) => total + ch.charCodeAt(0), 0)
  const kinds = ['exact', 'normalized', 'fuzzy', 'none', 'normalized', 'abstract'] as const
  const kind = kinds[hash % kinds.length]
  const section = ['results', 'methods', 'discussion', 'conclusion', 'limitations'][hash % 5]

  if (kind === 'abstract') {
    return {
      match: 'normalized', origin: 'abstract', section: null, page: null, pdf: false, available: false,
      quote: claimText,
      reason: 'Quoted from the abstract. The paper body was never available, so there is no page and no surrounding paragraph.',
    }
  }
  if (kind === 'none') {
    return {
      match: 'none', origin: 'full_text', section, page: null, pdf: false, available: false,
      quote: claimText,
      reason: 'Full text was truncated during extraction, so there is no paragraph to point at.',
    }
  }
  return {
    match: kind, origin: 'full_text', section, page: 2 + (hash % 13), pdf: true, available: true,
    quote: claimText,
    reason: kind === 'fuzzy'
      ? 'Located by fuzzy match, so the span boundaries are approximate — check the page before quoting.'
      : undefined,
    ctx: ['… ', claimText, ' The surrounding paragraph continues from the same page of the retrieved full text.'],
  }
}

function provFor(claimId: string, claimText: string): DemoProv {
  return PROV[claimId] ?? derivedProv(claimId, claimText)
}

function sourceFields(claimId: string, claimText: string): ClaimSourceFields {
  const prov = provFor(claimId, claimText)
  const start = prov.ctx ? prov.ctx[0].length : null
  return {
    source_match: prov.match,
    source_quote: prov.quote,
    source_origin: prov.origin,
    source_section: prov.section,
    source_page: prov.page,
    source_start: start,
    source_end: start === null ? null : start + (prov.ctx?.[1].length ?? 0),
  }
}

/** What `claims.source` would return for a demo claim. */
export function demoClaimSource(claim: {
  claim_id: string
  paper_id: string
  claim_text: string
  citation: string
}): ClaimSourceRead {
  const prov = provFor(claim.claim_id, claim.claim_text)
  const context = prov.ctx ? prov.ctx.join('') : null
  const highlightStart = prov.ctx ? prov.ctx[0].length : null
  const paper = DEMO_PAPERS.find((p) => p.id === claim.paper_id)
  return {
    claim_id: claim.claim_id,
    paper_id: claim.paper_id,
    paper_title: paper?.title ?? claim.citation,
    citation: claim.citation,
    claim_text: claim.claim_text,
    available: Boolean(prov.available && prov.ctx),
    match: prov.match,
    origin: prov.origin,
    reason: prov.reason ??
      'Located in the retrieved full text; the highlight uses the offsets the API returned for this paragraph.',
    quote: prov.quote,
    section: prov.section,
    page: prov.page,
    start: highlightStart,
    end: highlightStart === null ? null : highlightStart + (prov.ctx?.[1].length ?? 0),
    context,
    context_start: 0,
    highlight_start: highlightStart,
    highlight_end: highlightStart === null ? null : highlightStart + (prov.ctx?.[1].length ?? 0),
    pdf_url: prov.pdf ? `https://example.org/${claim.paper_id}.pdf` : null,
  }
}

// -- clusters ---------------------------------------------------------------

interface DemoClaimSeed {
  id: string
  paper: string
  text: string
  cite: string
  stance: ClusterClaimRead['stance']
  conf: number
  sim: number
  n: number
}

function claims(seeds: DemoClaimSeed[]): ClusterClaimRead[] {
  return seeds.map((seed) => ({
    claim_id: seed.id,
    paper_id: seed.paper,
    claim_text: seed.text,
    citation: seed.cite,
    stance: seed.stance,
    similarity_score: seed.sim,
    confidence_score: seed.conf,
    sample_size: `n = ${seed.n.toLocaleString('en-US')}`,
    ...sourceFields(seed.id, seed.text),
  }))
}

function rationale(
  components: Record<string, number>,
  penalty: number,
  inputs: Partial<QualityRationale>,
): QualityRationale {
  const weights = { design: 0.4, sample: 0.2, corroboration: 0.2, extraction: 0.2 }
  const weightedSum = Object.entries(components).reduce(
    (total, [key, value]) => total + value * (weights[key as keyof typeof weights] ?? 0),
    0,
  )
  const score = Math.max(0, weightedSum - penalty)
  return {
    components,
    weights,
    weighted_sum: weightedSum,
    conflict_penalty: penalty,
    score,
    tier: score >= 0.75 ? 'high' : score >= 0.45 ? 'medium' : 'low',
    ...inputs,
  }
}

export const DEMO_CLUSTERS: ClaimClusterDetail[] = [
  {
    id: 'c1',
    query_id: DEMO_QUERY_ID,
    central_theme: 'Aerobic exercise produces a moderate reduction in depression severity',
    consensus_summary:
      'Eleven papers estimate the effect of supervised aerobic exercise against non-exercise control conditions in adults meeting diagnostic criteria for depression. Pooled standardised mean differences cluster between −0.62 and −0.79, a moderate effect comparable in magnitude to that reported for first-line pharmacotherapy in the same populations. The estimate is stable across pooling method: trim-and-fill adjustment moves it to −0.62, and the network meta-analysis with the largest sample recovers −0.79 for the walking and jogging node.',
    lineage_tree: {
      root_paper_id: 'p01', root_year: 2007, span_years: 17, paper_count: 5,
      chain: [
        { paper_id: 'p01', claim_id: 'cl_1042', title: 'Exercise and Pharmacotherapy in the Treatment of Major Depressive Disorder', year: 2007, citation_count: 1204, relationship: 'origin' },
        { paper_id: 'p09', claim_id: 'cl_1188', title: 'The antidepressive effects of exercise: a meta-analysis of randomized trials', year: 2009, citation_count: 1052, relationship: 'supports' },
        { paper_id: 'p02', claim_id: 'cl_1301', title: 'Exercise for depression (Cochrane)', year: 2013, citation_count: 2410, relationship: 'extends' },
        { paper_id: 'p03', claim_id: 'cl_1466', title: 'Exercise as a treatment for depression: a meta-analysis adjusting for publication bias', year: 2016, citation_count: 1866, relationship: 'supports' },
        { paper_id: 'p07', claim_id: 'cl_1902', title: 'Effect of exercise for depression: network meta-analysis', year: 2024, citation_count: 389, relationship: 'extends' },
      ],
    },
    support_count: 9,
    neutral_count: 1,
    contradiction_count: 1,
    disagreement_drivers: [
      { driver_type: 'methodology', description: 'Waitlist controls produce effects roughly 0.25 SMD larger than active-control comparisons, and the two are pooled together in five of the eleven papers.' },
      { driver_type: 'analysis', description: 'Random-effects pooling with high heterogeneity (I² = 63–81%) widens intervals that the narrative summaries report as point estimates.' },
    ],
    quality_tier: 'high',
    quality_score: 0.884,
    quality_rationale: rationale({ design: 0.92, sample: 0.88, corroboration: 0.95, extraction: 0.9 }, 0.02, {
      study_types: '6 meta-analyses, 1 network meta-analysis, 4 RCTs',
      largest_sample_size: 14170, paper_count: 11, support_count: 9, contradiction_count: 1,
    }),
    user_edited: false,
    created_at: '2026-08-18T09:45:00Z',
    claims: claims([
      { id: 'cl_1042', paper: 'p01', text: 'Supervised aerobic exercise reduced HAM-D scores at 16 weeks comparably to sertraline (remission 45% vs 47%).', cite: 'Blumenthal et al. 2007, Psychosom Med', stance: 'supports', conf: 0.94, sim: 1.0, n: 202 },
      { id: 'cl_1188', paper: 'p09', text: 'Pooled effect of exercise on depression across 58 trials was large before adjustment (d = −0.80).', cite: 'Rethorst et al. 2009, Sports Med', stance: 'supports', conf: 0.88, sim: 0.91, n: 2325 },
      { id: 'cl_1301', paper: 'p02', text: 'Exercise is moderately more effective than no therapy at reducing depression symptoms (SMD −0.62).', cite: 'Cooney et al. 2013, Cochrane', stance: 'supports', conf: 0.93, sim: 0.94, n: 2326 },
      { id: 'cl_1466', paper: 'p03', text: 'After adjusting for publication bias the effect remains moderate and significant (SMD −0.62, 95% CI −0.81 to −0.42).', cite: 'Schuch et al. 2016, J Psychiatr Res', stance: 'supports', conf: 0.91, sim: 0.89, n: 1487 },
      { id: 'cl_1902', paper: 'p07', text: 'Walking or jogging showed a moderate reduction versus active control in the network model (SMD −0.62).', cite: 'Noetel et al. 2024, BMJ', stance: 'supports', conf: 0.9, sim: 0.87, n: 14170 },
    ]),
  },
  {
    id: 'c2',
    query_id: DEMO_QUERY_ID,
    central_theme: 'Effect sizes shrink in trials with blinded outcome assessment',
    consensus_summary:
      'Four papers report that restricting analysis to trials with blinded outcome assessors and intention-to-treat data reduces the pooled effect to a small, sometimes non-significant value. Three papers disagree, holding that the reduction is an artefact of restricting to a handful of small trials, or that bias-adjusted estimates remain clinically meaningful. The disagreement is not about the data — the same trials appear on both sides — but about which subset licenses a conclusion.',
    lineage_tree: {
      root_paper_id: 'p15', root_year: 2009, span_years: 15, paper_count: 6,
      chain: [
        { paper_id: 'p15', claim_id: 'cl_1204', title: 'The effect of exercise in clinically depressed adults (DEMO)', year: 2009, citation_count: 342, relationship: 'origin' },
        { paper_id: 'p14', claim_id: 'cl_1288', title: 'Facilitated physical activity as a treatment for depressed adults (TREAD)', year: 2012, citation_count: 479, relationship: 'supports' },
        { paper_id: 'p02', claim_id: 'cl_1312', title: 'Exercise for depression (Cochrane)', year: 2013, citation_count: 2410, relationship: 'supports' },
        { paper_id: 'p03', claim_id: 'cl_1470', title: 'Exercise as a treatment for depression: adjusting for publication bias', year: 2016, citation_count: 1866, relationship: 'contradicts' },
        { paper_id: 'p04', claim_id: 'cl_1590', title: 'Exercise for patients with major depression: trial sequential analysis', year: 2017, citation_count: 512, relationship: 'extends' },
        { paper_id: 'p07', claim_id: 'cl_1911', title: 'Effect of exercise for depression: network meta-analysis', year: 2024, citation_count: 389, relationship: 'contradicts' },
      ],
    },
    support_count: 4,
    neutral_count: 0,
    contradiction_count: 3,
    disagreement_drivers: [
      { driver_type: 'methodology', description: 'Krogh and Cooney restrict to blinded-assessor, ITT trials; Schuch and Noetel adjust statistically instead and retain unblinded trials in the pool. The two strategies cannot be reconciled by re-weighting.' },
      { driver_type: 'metric_definition', description: '“Clinically meaningful” is defined as a 3-point HAM-D difference by one team and as SMD ≥ 0.5 by another, so the same estimate is called negligible and moderate.' },
      { driver_type: 'sample_size', description: 'Blinded-only subgroups draw on 4–8 trials (n = 391–1122) against 23–39 trials in the full pools; the sceptical estimate carries the wider interval.' },
      { driver_type: 'publication_bias', description: 'Funnel asymmetry is treated as evidence of small-study bias by three papers and as genuine heterogeneity in dose by two others.' },
    ],
    quality_tier: 'medium',
    quality_score: 0.5,
    quality_rationale: rationale({ design: 0.71, sample: 0.52, corroboration: 0.44, extraction: 0.86 }, 0.15, {
      study_types: '3 systematic reviews, 2 meta-analyses, 2 RCTs',
      largest_sample_size: 2498, paper_count: 7, support_count: 4, contradiction_count: 3,
    }),
    user_edited: false,
    created_at: '2026-08-18T09:45:00Z',
    claims: claims([
      { id: 'cl_1204', paper: 'p15', text: 'Aerobic exercise did not reduce blinded HAM-D₁₇ scores more than relaxation at four months (difference 0.4 points, p = 0.79).', cite: 'Krogh et al. 2009, J Clin Psychiatry', stance: 'supports', conf: 0.92, sim: 0.96, n: 165 },
      { id: 'cl_1288', paper: 'p14', text: 'Facilitated physical activity produced no improvement in blinded BDI score at four months versus usual care alone.', cite: 'Chalder et al. 2012, BMJ', stance: 'supports', conf: 0.95, sim: 0.93, n: 361 },
      { id: 'cl_1312', paper: 'p02', text: 'Restricting to trials with adequate allocation concealment, blinding and ITT analysis reduced the pooled effect to SMD −0.18.', cite: 'Cooney et al. 2013, Cochrane', stance: 'supports', conf: 0.94, sim: 0.99, n: 1122 },
      { id: 'cl_1590', paper: 'p04', text: 'Trial sequential analysis of blinded-outcome trials could not exclude a null effect; the required information size was not reached.', cite: 'Krogh et al. 2017, BMJ Open', stance: 'supports', conf: 0.89, sim: 0.9, n: 2498 },
      { id: 'cl_1470', paper: 'p03', text: 'Bias-adjusted pooling retained a moderate effect (SMD −0.62), so blinding alone does not explain the estimate away.', cite: 'Schuch et al. 2016, J Psychiatr Res', stance: 'contradicts', conf: 0.9, sim: 0.84, n: 1487 },
      { id: 'cl_1911', paper: 'p07', text: 'Effects persisted in the network model after controlling for risk of bias, though certainty was rated low to moderate.', cite: 'Noetel et al. 2024, BMJ', stance: 'contradicts', conf: 0.87, sim: 0.81, n: 14170 },
      { id: 'cl_1655', paper: 'p11', text: 'Blinded subgroups comprise few, small trials; their smaller effect is within sampling error of the full pool.', cite: 'Kvam et al. 2016, J Affect Disord', stance: 'contradicts', conf: 0.78, sim: 0.77, n: 977 },
    ]),
  },
  {
    id: 'c3',
    query_id: DEMO_QUERY_ID,
    central_theme: 'Three or more sessions per week outperforms lower frequency',
    consensus_summary:
      'Dose is the one moderator that survives across papers. The single dedicated dose-response trial found public-health-dose exercise (17.5 kcal/kg/week) clearly superior to a low dose that performed like the placebo control, and three pooled analyses recover frequency or intensity as a moderator. Session frequency is confounded with supervision in every paper: higher-frequency arms were also the supervised ones.',
    lineage_tree: {
      root_paper_id: 'p05', root_year: 2005, span_years: 19, paper_count: 4,
      chain: [
        { paper_id: 'p05', claim_id: 'cl_1001', title: 'Exercise treatment for depression: efficacy and dose response', year: 2005, citation_count: 930, relationship: 'origin' },
        { paper_id: 'p09', claim_id: 'cl_1190', title: 'The antidepressive effects of exercise: moderator analysis', year: 2009, citation_count: 1052, relationship: 'supports' },
        { paper_id: 'p06', claim_id: 'cl_1801', title: 'Effectiveness of physical activity interventions (umbrella review)', year: 2023, citation_count: 704, relationship: 'extends' },
        { paper_id: 'p07', claim_id: 'cl_1920', title: 'Effect of exercise for depression: dose nodes in the network model', year: 2024, citation_count: 389, relationship: 'supports' },
      ],
    },
    support_count: 4,
    neutral_count: 1,
    contradiction_count: 0,
    disagreement_drivers: [
      { driver_type: 'population', description: 'The dose trial recruited mild-to-moderate outpatients; pooled moderator analyses include inpatient samples where baseline severity limits achievable dose.' },
    ],
    quality_tier: 'medium',
    quality_score: 0.648,
    quality_rationale: rationale({ design: 0.68, sample: 0.48, corroboration: 0.72, extraction: 0.88 }, 0.0, {
      study_types: '1 dose-response RCT, 3 meta-analyses, 1 umbrella review',
      largest_sample_size: 128119, paper_count: 5, support_count: 4, contradiction_count: 0,
    }),
    user_edited: false,
    created_at: '2026-08-18T09:45:00Z',
    claims: claims([
      { id: 'cl_1001', paper: 'p05', text: 'Public-health-dose exercise (17.5 kcal/kg/week) achieved 47% response versus 30% at low dose and 29% for placebo control.', cite: 'Dunn et al. 2005, Am J Prev Med', stance: 'supports', conf: 0.91, sim: 0.98, n: 80 },
      { id: 'cl_1190', paper: 'p09', text: 'Trials with more than three sessions per week showed larger effects in moderator analysis.', cite: 'Rethorst et al. 2009, Sports Med', stance: 'supports', conf: 0.82, sim: 0.88, n: 2325 },
      { id: 'cl_1801', paper: 'p06', text: 'Higher-intensity interventions produced larger reductions in depression across populations.', cite: 'Singh et al. 2023, BJSM', stance: 'supports', conf: 0.85, sim: 0.83, n: 128119 },
      { id: 'cl_1920', paper: 'p07', text: 'Vigorous-intensity nodes ranked above light-intensity nodes, but interval overlap prevents ordering the doses.', cite: 'Noetel et al. 2024, BMJ', stance: 'neutral', conf: 0.8, sim: 0.79, n: 14170 },
    ]),
  },
  {
    id: 'c4',
    query_id: DEMO_QUERY_ID,
    central_theme: 'Effects in adults over 65 are comparable to younger cohorts',
    consensus_summary:
      'Three papers touch late-life depression. One randomised trial of sertraline plus progressive aerobic exercise in adults 65 and older reports larger remission in the exercise arm, and two pooled analyses report age as a non-significant moderator. Age-stratified estimates are not reported separately in either pooled paper, so “comparable” rests on the absence of a moderator effect rather than on a measured one.',
    lineage_tree: {
      root_paper_id: 'p12', root_year: 2015, span_years: 9, paper_count: 3,
      chain: [
        { paper_id: 'p12', claim_id: 'cl_1401', title: 'Physical exercise for late-life major depression', year: 2015, citation_count: 266, relationship: 'origin' },
        { paper_id: 'p11', claim_id: 'cl_1489', title: 'Exercise as a treatment for depression: a meta-analysis', year: 2016, citation_count: 920, relationship: 'supports' },
        { paper_id: 'p07', claim_id: 'cl_1930', title: 'Effect of exercise for depression: age as a moderator', year: 2024, citation_count: 389, relationship: 'supports' },
      ],
    },
    support_count: 2,
    neutral_count: 1,
    contradiction_count: 0,
    disagreement_drivers: [],
    quality_tier: 'low',
    quality_score: 0.406,
    quality_rationale: rationale({ design: 0.44, sample: 0.22, corroboration: 0.3, extraction: 0.71 }, 0.0, {
      study_types: '1 RCT, 2 meta-analyses',
      largest_sample_size: 2325, paper_count: 3, support_count: 2, contradiction_count: 0,
    }),
    user_edited: false,
    created_at: '2026-08-18T09:45:00Z',
    claims: claims([
      { id: 'cl_1401', paper: 'p12', text: 'Adding progressive aerobic exercise to sertraline raised remission at 24 weeks in adults 65+ (81% vs 45%).', cite: 'Belvederi Murri et al. 2015, Br J Psychiatry', stance: 'supports', conf: 0.86, sim: 0.95, n: 121 },
      { id: 'cl_1489', paper: 'p11', text: 'Mean participant age was not a significant moderator of effect size.', cite: 'Kvam et al. 2016, J Affect Disord', stance: 'supports', conf: 0.74, sim: 0.72, n: 977 },
      { id: 'cl_1930', paper: 'p07', text: 'Age subgroups did not differ credibly, though older-adult trials were few.', cite: 'Noetel et al. 2024, BMJ', stance: 'neutral', conf: 0.77, sim: 0.7, n: 14170 },
    ]),
  },
  {
    id: 'c5',
    query_id: DEMO_QUERY_ID,
    central_theme: 'Exercise as an adjunct in treatment-resistant depression',
    consensus_summary:
      'One small trial addresses treatment-resistant depression directly: 33 patients on stable pharmacotherapy, half assigned to 30–45 minutes of walking five days a week. The exercise arm improved on HAM-D, BDI and GAF where the control arm did not. Nothing in the retrieved set replicates or contests it, so the cluster has no corroboration term to score and Nodus leaves the tier unrated rather than inferring one.',
    lineage_tree: null,
    support_count: 1,
    neutral_count: 0,
    contradiction_count: 0,
    disagreement_drivers: [],
    quality_tier: 'unrated',
    quality_score: null,
    quality_rationale: { paper_count: 1, corroboration_note: 'not computable — no second paper' },
    user_edited: false,
    created_at: '2026-08-18T09:45:00Z',
    claims: claims([
      { id: 'cl_1233', paper: 'p13', text: 'Adjunct moderate exercise improved HAM-D, BDI and GAF in treatment-resistant patients over 12 weeks, while the control arm did not change.', cite: 'Mota-Pereira et al. 2011, J Psychiatr Res', stance: 'supports', conf: 0.83, sim: 1.0, n: 33 },
    ]),
  },
  {
    id: 'c6',
    query_id: DEMO_QUERY_ID,
    central_theme: 'Attrition weakens twelve-month follow-up estimates',
    consensus_summary:
      'Whether the benefit persists past the intervention period is the least settled question in the retrieved set. The one-year SMILE follow-up reports continued advantage for those who kept exercising, which two papers read as selection rather than effect: adherence at twelve months was self-reported and unrandomised. A fourth paper finds no maintenance signal at all.',
    lineage_tree: {
      root_paper_id: 'p08', root_year: 2011, span_years: 13, paper_count: 4,
      chain: [
        { paper_id: 'p08', claim_id: 'cl_1250', title: 'One-year follow-up of the SMILE study', year: 2011, citation_count: 411, relationship: 'origin' },
        { paper_id: 'p02', claim_id: 'cl_1330', title: 'Exercise for depression (Cochrane) — long-term outcomes', year: 2013, citation_count: 2410, relationship: 'contradicts' },
        { paper_id: 'p16', claim_id: 'cl_1444', title: 'Physical exercise and internet-based CBT in the treatment of depression', year: 2015, citation_count: 301, relationship: 'contradicts' },
        { paper_id: 'p07', claim_id: 'cl_1940', title: 'Effect of exercise for depression: durability of effect', year: 2024, citation_count: 389, relationship: 'extends' },
      ],
    },
    support_count: 1,
    neutral_count: 1,
    contradiction_count: 2,
    disagreement_drivers: [
      { driver_type: 'temporal', description: 'Follow-up windows are 4, 6, 12 and 24 months; the longest window carries the largest attrition and the strongest reported effect.' },
      { driver_type: 'analysis', description: 'The follow-up advantage is a post-hoc comparison of self-selected adherers, not a randomised contrast.' },
    ],
    quality_tier: 'medium',
    quality_score: 0.51,
    quality_rationale: rationale({ design: 0.55, sample: 0.61, corroboration: 0.4, extraction: 0.79 }, 0.09, {
      study_types: '1 RCT follow-up, 2 meta-analyses, 1 RCT',
      largest_sample_size: 2326, paper_count: 4, support_count: 1, contradiction_count: 2,
    }),
    user_edited: false,
    created_at: '2026-08-18T09:45:00Z',
    claims: claims([
      { id: 'cl_1250', paper: 'p08', text: 'Participants who continued regular exercise had lower depression scores at twelve months than those who did not.', cite: 'Hoffman et al. 2011, Psychosom Med', stance: 'supports', conf: 0.84, sim: 0.94, n: 202 },
      { id: 'cl_1330', paper: 'p02', text: 'Few trials reported outcomes beyond the intervention period, and those that did showed no maintained benefit.', cite: 'Cooney et al. 2013, Cochrane', stance: 'contradicts', conf: 0.88, sim: 0.86, n: 2326 },
      { id: 'cl_1444', paper: 'p16', text: 'Group differences had disappeared at twelve-month follow-up across all three arms.', cite: 'Hallgren et al. 2015, Br J Psychiatry', stance: 'contradicts', conf: 0.85, sim: 0.82, n: 946 },
      { id: 'cl_1940', paper: 'p07', text: 'Durability could not be assessed: too few trials reported post-intervention follow-up to model.', cite: 'Noetel et al. 2024, BMJ', stance: 'neutral', conf: 0.81, sim: 0.75, n: 14170 },
    ]),
  },
]

export const DEMO_CAVEATS: Record<string, string[]> = {
  c1: [
    'Nine of eleven papers pool trials that also appear in each other, so the papers are not independent evidence.',
    'Control conditions range from waitlist to active stretching; the larger effects come from waitlist comparisons.',
  ],
  c2: [
    'The blinded-only subgroups contain 4 to 8 trials, so subgroup estimates are themselves imprecise.',
    'Two papers share an author team, which weakens the appearance of independent corroboration on the sceptical side.',
  ],
  c3: [
    'No paper randomises frequency independently of supervision or session length.',
    'The dose trial has 80 participants across five arms, so per-arm precision is low.',
  ],
  c4: [
    'No paper reports an age-stratified effect size; the claim is inferred from null moderator tests.',
    'The one dedicated trial has 121 participants and no blinded assessment of the exercise arm.',
  ],
  c5: [
    'Single study, 33 participants, no blinding of outcome assessment.',
    'Treatment resistance was defined by the trial team rather than by a standard staging method.',
  ],
  c6: [
    'Long-term arms lost 22–41% of participants; no paper reports a tipping-point analysis.',
    '“Maintenance” is measured against different baselines across the four papers.',
  ],
}
