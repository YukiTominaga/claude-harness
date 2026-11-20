export const meta = {
  name: 'diagnose',
  description: 'Diagnose one recurring blocking issue: gather evidence, argue three competing hypotheses apart, refute each, then test and decide',
  whenToUse: 'Started by /crystal-harness:build when harness.diagnoseRecurringIssues is true and a blocking issue has come back. Not meant to be run by hand.',
  phases: [
    { title: 'Evidence', detail: 'one investigator reproduces the issue and records what it sees' },
    { title: 'Hypotheses', detail: 'three investigators argue different causes, without seeing each other' },
    { title: 'Refutation', detail: 'three investigators each try to break one hypothesis' },
    { title: 'Diagnosis', detail: 'one investigator runs the deciding experiments and writes the diagnosis' },
  ],
}

const a = args || {}
for (const key of ['roundDir', 'issueId', 'verdictPath', 'commit']) {
  if (a[key] === undefined || a[key] === null || a[key] === '') {
    throw new Error(`diagnose: missing required arg "${key}"`)
  }
}
const PLUGIN = a.agentPrefix || 'crystal-harness'
const INVESTIGATOR = `${PLUGIN}:harness-investigator`
const DIR = `${a.roundDir}/diagnosis/${a.issueId}`
const ANGLES = ['state', 'wiring', 'premise']
const EFFORT = Object.assign({ evidence: 'medium', hypothesis: 'high', refutation: 'medium', diagnosis: 'high' }, a.effort || {})

const common = [
  `Issue: ${a.issueId}, reported in ${a.verdictPath}. Read it there.`,
  `Round directory: ${a.roundDir}   commit: ${a.commit}`,
  `Everything you write goes in ${DIR}/.`,
  a.scratchDir ? `Scratch directory for throwaway scripts: ${a.scratchDir}` : '',
].filter(Boolean).join('\n')

function investigator(part, body, opts) {
  return agent(`You are an investigator. Your part: **${part}**.\n${common}\n${body}`, Object.assign({ agentType: INVESTIGATOR }, opts))
}

phase('Evidence')
const evidence = await investigator(
  'evidence',
  `Follow "Evidence" in your agent definition. You are the only one who may run the application until the last step. Write ${DIR}/evidence.md, then return whether you reproduced the issue and a two-sentence summary of what you saw.`,
  {
    label: 'evidence', phase: 'Evidence', effort: EFFORT.evidence,
    schema: { type: 'object', required: ['reproduced', 'summary'], properties: { reproduced: { type: 'boolean' }, summary: { type: 'string' } } },
  },
)
if (!evidence || !evidence.reproduced) {
  log('The issue could not be reproduced, so there is nothing to diagnose. The orchestrating command decides what follows.')
  return { status: 'not_reproduced', issueId: a.issueId, evidence: evidence ? evidence.summary : null, files: [`${DIR}/evidence.md`] }
}

phase('Hypotheses')
const HYPOTHESIS = { type: 'object', required: ['claim', 'experiment'], properties: { claim: { type: 'string' }, experiment: { type: 'string' }, deadEnd: { type: 'boolean' } } }
const hypotheses = await parallel(ANGLES.map(angle => () =>
  investigator(
    `hypothesis, angle \`${angle}\``,
    `Follow "Hypothesis" in your agent definition. Do NOT run the application; work from the code and ${DIR}/evidence.md. Do not read any other file in ${DIR}/. Write ${DIR}/h-${angle}.md, then return your claim in one sentence, your discriminating experiment, and deadEnd: true only if this angle honestly led nowhere.`,
    { label: `hypothesis:${angle}`, phase: 'Hypotheses', effort: EFFORT.hypothesis, schema: HYPOTHESIS },
  ),
))

phase('Refutation')
const live = ANGLES.filter((angle, i) => hypotheses[i] && !hypotheses[i].deadEnd)
const refutations = await parallel(live.map(angle => () =>
  investigator(
    `refutation of the \`${angle}\` hypothesis`,
    `Follow "Refutation" in your agent definition. The hypothesis to break is ${DIR}/h-${angle}.md; you may also read ${DIR}/evidence.md and the code. Do NOT run the application and do not read the other hypotheses. Write ${DIR}/r-${angle}.md, then return whether the hypothesis survives and your strongest objection.`,
    {
      label: `refute:${angle}`, phase: 'Refutation', effort: EFFORT.refutation,
      schema: { type: 'object', required: ['survives', 'objection'], properties: { survives: { type: 'boolean' }, objection: { type: 'string' } } },
    },
  ),
))

phase('Diagnosis')
const standing = live.map((angle, i) => `${angle}: ${refutations[i] ? (refutations[i].survives ? 'survived its refutation' : 'did not survive its refutation') : 'was not examined'}`)
const diagnosis = await investigator(
  'verdict on the cause',
  [
    `Follow "Verdict on the cause" in your agent definition. Read every file in ${DIR}/. You may run the application now; stop it when you are done.`,
    `Where the hypotheses stand going in — ${standing.join('; ') || 'none of the three angles produced a hypothesis'}. A refutation is an argument, not a result: run the experiments before you believe either side.`,
    `Write ${DIR}/diagnosis.md, then return the root cause in one sentence and your confidence.`,
  ].join('\n'),
  {
    label: 'diagnosis', phase: 'Diagnosis', effort: EFFORT.diagnosis,
    schema: { type: 'object', required: ['rootCause', 'confidence'], properties: { rootCause: { type: 'string' }, confidence: { type: 'string', enum: ['high', 'medium', 'low'] } } },
  },
)

return {
  status: diagnosis ? 'diagnosed' : 'incomplete',
  issueId: a.issueId,
  rootCause: diagnosis ? diagnosis.rootCause : null,
  confidence: diagnosis ? diagnosis.confidence : null,
  hypotheses: Object.fromEntries(ANGLES.map((angle, i) => [angle, hypotheses[i] ? hypotheses[i].claim : null])),
  diagnosisPath: `${DIR}/diagnosis.md`,
}
