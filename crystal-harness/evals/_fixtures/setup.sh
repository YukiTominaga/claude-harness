#!/bin/bash
# Build one eval fixture in the current (empty) directory.
#   setup.sh <notes-a|notes-b> <full|thin> [mutation]
# notes-a: a Notes API that passed a final assessment. `full` is its own test
#          suite; `thin` is a happy-path suite that stays green under every
#          mutation, so a seeded defect cannot be found just by running the tests.
# notes-b: a second, independently written implementation of the same spec.
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
fixture="$1"; tests="$2"; mutation="${3:-}"

cp "$here/$fixture/app.py" app.py
if [ "$fixture" = "notes-a" ]; then
  mkdir -p tests && cp "$here/notes-a/tests_$tests/test_notes_api.py" tests/test_notes_api.py
  test_cmd="python3 -m unittest discover -s tests -v"
else
  cp -r "$here/notes-b/tests" tests
  test_cmd="python3 -m unittest discover -s tests -t . -v"
fi
if [ -n "$mutation" ]; then
  python3 "$here/mutate.py" "$mutation" app.py
fi

mkdir -p .harness/final/01 .harness/sprints .harness/artifacts
cp "$here/harness/spec.md" .harness/spec.md
cat > .harness/config.json <<JSON
{
  "commands": { "install": null, "dev": null, "build": null, "test": "$test_cmd", "backendDev": "python3 app.py" },
  "urls": { "app": null, "api": "http://127.0.0.1:8765" },
  "database": { "kind": "sqlite", "file": "./notes.db", "url": null },
  "harness": { "useEvaluator": true, "useSprints": false, "contextReset": true, "browserVerification": false,
               "codexReview": false, "parallelEvaluation": false, "maxFinalQaRounds": 5 }
}
JSON
cat > .harness/state.json <<JSON
{ "schemaVersion": 3, "phase": "final-qa", "currentSprint": null, "currentRound": 1, "sprints": [], "finalRounds": [],
  "repeatedIssueFingerprints": {}, "lastGoodCommit": null, "baseCommit": null, "blockedReason": null,
  "updatedAt": "2026-01-01T00:00:00Z" }
JSON
cat > .harness/final/01/report.md <<'MD'
# Final round 01 report — build

## What is complete
The Notes API in `app.py`: create, read, list and delete notes, with the validation and status codes the spec describes.

## Self-check results
The test suite passes.
MD
printf 'notes.db\nnotes.db-journal\n*.db\n__pycache__/\n.harness/artifacts/\n' > .gitignore
git init -q .
git -c user.email=eval@example.com -c user.name=eval add -A
git -c user.email=eval@example.com -c user.name=eval commit -q -m "feat: notes api"
