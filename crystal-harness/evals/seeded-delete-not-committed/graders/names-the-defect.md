---
type: regex
target: { source: file, path: .harness/final/01/verdict.json }
flags: is
weight: 2
pattern: '"blockingIssues"\s*:\s*\[(?:(?!"nonBlockingIssues")[\s\S])*?(?:commit|roll(?:ed|s)?[ -]?back|transaction|still (?:there|present|exists|readable|returned|in the)|not (?:removed|deleted|persisted)|survives|reappears|remains)'
---
