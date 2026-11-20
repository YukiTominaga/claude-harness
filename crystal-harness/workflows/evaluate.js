export const meta = {
  name: 'evaluate',
  description: 'Parallel evaluation of one harness round: one evaluator per lens, then an independent reproduction of each blocking issue',
  whenToUse: 'Started by /crystal-harness:build when harness.parallelEvaluation is true. Not meant to be run by hand.',
  phases: [
    { title: 'Lenses', detail: 'code alongside tests → api → screen' },
    { title: 'Reproduce', detail: 'one fresh evaluator per blocking issue, one at a time' },
  ],
}

// The orchestrating command passes everything this script needs; it has no access
// to the filesystem, so the facts of the round arrive as args and the results
// leave as files the lens evaluators write under <roundDir>/lenses/.
const a = args || {}
for (const key of ['roundDir', 'phase', 'round', 'commit']) {
  if (a[key] === undefined || a[key] === null || a[key] === '') {
    throw new Error(`evaluate: missing required arg "${key}"`)
  }
}
const PLUGIN = a.agentPrefix || 'crystal-harness'
const EVALUATOR = `${PLUGIN}:harness-evaluator`
const SKILL = `${PLUGIN}:evaluation-lenses`
const browser = a.browser === true
const reproduce = a.reproduce !== false
const EFFORT = Object.assign(
  { tests: 'medium', api: 'high', screen: 'high', code: 'high', reproduce: 'medium' },
  a.effort || {},
)

const ISSUES = {
  type: 'array',
  items: {
    type: 'object',
    required: ['id', 'repro', 'observed', 'expected'],
    properties: {
      id: { type: 'string' },
      repro: { type: 'array', items: { type: 'string' } },
      observed: { type: 'string' },
      expected: { type: 'string' },
    },
  },
}
const LENS_RESULT = {
  type: 'object',
  required: ['lensVerdict', 'summary', 'blockingIssues'],
  properties: {
    lensVerdict: { type: 'string', enum: ['pass', 'fail'] },
    summary: { type: 'string' },
    blockingIssues: ISSUES,
  },
}
const REPRO_RESULT = {
  type: 'object',
  required: ['reproduced', 'evidence'],
  properties: { reproduced: { type: 'boolean' }, evidence: { type: 'string' } },
}

const where =
  a.phase === 'sprint'
    ? `sprint ${a.sprint} QA, round ${a.round}`
    : `the final assessment, round ${a.round}`
const recheck = a.recheck && a.recheck.previousCommit
  ? `This is a RE-CHECK. The previous round graded commit ${a.recheck.previousCommit}` +
    (a.recheck.previousRoundDir ? `, and its verdict.json is in ${a.recheck.previousRoundDir}` : ', and its verdict.json is still in the round directory') +
    `. Follow "Re-check rounds" in the skill.`
  : 'This is the first evaluation of this round: grade your slice in full.'

function lensPrompt(lens, upstream) {
  const owner = browser ? 'screen' : 'api'
  return [
    `You are the \`${lens}\` lens of a parallel evaluation: ${where}.`,
    `Load the \`${SKILL}\` skill and follow its common rules and its \`${lens}\` lens section exactly. Your agent definition's standards and the qa-rubric skill apply in full.`,
    `Round directory: ${a.roundDir}`,
    `phase: "${a.phase}"   sprint: ${a.phase === 'sprint' ? a.sprint : 'null'}   round: ${a.round}`,
    `commit: ${a.commit}`,
    `Browser verification is ${browser ? 'ENABLED' : 'DISABLED'} for this run, so the \`${owner}\` lens owns the acceptance criteria${lens === owner ? ' — that is you' : ', not you'}.`,
    recheck,
    upstream ? `From the lenses that ran before you: ${upstream}` : '',
    a.correction ? `CORRECTION REQUESTED — an earlier attempt at this round was rejected for the reasons below. Fix what applies to your lens and write your files again:\n${a.correction}` : '',
    `Write ${a.roundDir}/lenses/${lens}.md and ${a.roundDir}/lenses/${lens}.json. Do not write verdict.json or qa.md.`,
    'Then return your lensVerdict, a one-paragraph summary, and your blocking issues with id, repro, observed and expected copied exactly from your file.',
  ].filter(Boolean).join('\n')
}

function runLens(lens, upstream) {
  return agent(lensPrompt(lens, upstream), {
    label: `lens:${lens}`,
    phase: 'Lenses',
    agentType: EVALUATOR,
    effort: EFFORT[lens],
    schema: LENS_RESULT,
  })
}

phase('Lenses')
// Everything that runs the application shares its ports and its datastore, so
// those lenses go one after another. The code lens only reads, and runs beside them.
const [code, chain] = await parallel([
  () => runLens('code'),
  async () => {
    const out = {}
    out.tests = await runLens('tests')
    const testsLine = out.tests ? `tests lens — ${out.tests.summary}` : 'tests lens — produced no result; treat the suite as not run and carry nothing.'
    out.api = await runLens('api', testsLine)
    if (browser) {
      const apiLine = out.api ? `api lens — ${out.api.summary}` : 'api lens — produced no result.'
      out.screen = await runLens('screen', `${testsLine}\n${apiLine}`)
    }
    return out
  },
])

const lenses = Object.assign({}, chain || {}, { code })
const missing = ['tests', 'api', 'code'].concat(browser ? ['screen'] : []).filter(l => !lenses[l])
if (missing.length) log(`No result from lens: ${missing.join(', ')} — merge_verdicts.py will refuse to merge until it is re-run.`)

// Reproduce each blocking issue found by running the product. Issues the code
// lens found by reading have nothing to reproduce. A reproducer is given the
// steps and the expectation and nothing else — not the lens's notes, not the cause.
const reproductions = {}
if (reproduce) {
  phase('Reproduce')
  const targets = ['tests', 'api', 'screen']
    .filter(l => lenses[l])
    .flatMap(l => (lenses[l].blockingIssues || []).map(issue => ({ lens: l, issue })))
  for (const { lens, issue } of targets) {
    const result = await agent(
      [
        `You are a reproducer in a parallel evaluation: ${where}. Load the \`${SKILL}\` skill and follow "Reproducing a blocking issue" exactly.`,
        `Round directory: ${a.roundDir}   round: ${a.round}   commit: ${a.commit}`,
        `Issue id: ${issue.id} (reported by the ${lens} lens)`,
        `Reproduction steps:\n${(issue.repro || []).map((s, i) => `  ${i + 1}. ${s}`).join('\n')}`,
        `Observed: ${issue.observed}`,
        `Expected: ${issue.expected}`,
        `Write ${a.roundDir}/lenses/verify/${issue.id}.json, then return whether you reproduced it and your evidence.`,
      ].join('\n'),
      { label: `reproduce:${issue.id}`, phase: 'Reproduce', agentType: EVALUATOR, effort: EFFORT.reproduce, schema: REPRO_RESULT },
    )
    reproductions[issue.id] = result ? result.reproduced : null
  }
}

return {
  lensVerdicts: Object.fromEntries(Object.entries(lenses).map(([name, r]) => [name, r ? r.lensVerdict : null])),
  missing,
  reproductions,
  next: `Run merge_verdicts.py on ${a.roundDir} with --round ${a.round}. It, not this result, decides the verdict.`,
}
