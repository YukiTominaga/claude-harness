#!/bin/bash
# Build one eval fixture in the current (empty) directory.
#   setup.sh <notes-a|notes-b|tracker> <full|thin> [mutation ...]
# notes-a: a Notes API that passed a final assessment. `full` is its own test
#          suite; `thin` is a happy-path suite that stays green under every
#          mutation, so a seeded defect cannot be found just by running the tests.
# notes-b: a second, independently written implementation of the same spec.
# tracker: a larger API — projects, tasks, a workflow, blocking relations,
#          filters and paging — with the same two suites. Its mutations are
#          either defects or decoys (see mutate.py).
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
fixture="$1"; tests="$2"; shift 2

cp "$here/$fixture/app.py" app.py
case "$fixture" in
  notes-a)
    mkdir -p tests && cp "$here/notes-a/tests_$tests/test_notes_api.py" tests/test_notes_api.py
    test_cmd="python3 -m unittest discover -s tests -v" ;;
  notes-b)
    cp -r "$here/notes-b/tests" tests
    test_cmd="python3 -m unittest discover -s tests -t . -v" ;;
  tracker)
    mkdir -p tests && cp "$here/tracker/tests_$tests/test_tracker_api.py" tests/test_tracker_api.py
    test_cmd="python3 -m unittest discover -s tests -v" ;;
  *) echo "setup.sh: unknown fixture $fixture" >&2; exit 2 ;;
esac
if [ "$#" -gt 0 ]; then
  python3 "$here/mutate.py" "$@" app.py
fi

if [ "$fixture" = "tracker" ]; then
  spec="$here/tracker/spec.md"; db="tracker.db"; subject="tracker api"
  complete='The Tracker API in `app.py`: projects, tasks with tags and priorities, the todo/doing/done workflow, blocking relations, listing with filters and paging, and archiving, moving and deleting — with the validation and status codes the spec describes.'
else
  spec="$here/harness/spec.md"; db="notes.db"; subject="notes api"
  complete='The Notes API in `app.py`: create, read, list and delete notes, with the validation and status codes the spec describes.'
fi

mkdir -p .harness/final/01 .harness/sprints .harness/artifacts
cp "$spec" .harness/spec.md
cat > .harness/config.json <<JSON
{
  "commands": { "install": null, "dev": null, "build": null, "test": "$test_cmd", "backendDev": "python3 app.py" },
  "urls": { "app": null, "api": "http://127.0.0.1:8765" },
  "database": { "kind": "sqlite", "file": "./$db", "url": null },
  "harness": { "useEvaluator": true, "useSprints": false, "contextReset": true, "browserVerification": false,
               "codexReview": false, "parallelEvaluation": false, "maxFinalQaRounds": 5 }
}
JSON
cat > .harness/state.json <<JSON
{ "schemaVersion": 3, "phase": "final-qa", "currentSprint": null, "currentRound": 1, "sprints": [], "finalRounds": [],
  "repeatedIssueFingerprints": {}, "lastGoodCommit": null, "baseCommit": null, "blockedReason": null,
  "updatedAt": "2026-01-01T00:00:00Z" }
JSON
cat > .harness/final/01/report.md <<MD
# Final round 01 report — build

## What is complete
$complete

## Self-check results
The test suite passes.
MD
printf '%s\n%s-journal\n*.db\n__pycache__/\n.harness/artifacts/\n' "$db" "$db" > .gitignore
git init -q .
git -c user.email=eval@example.com -c user.name=eval add -A
git -c user.email=eval@example.com -c user.name=eval commit -q -m "feat: $subject"
