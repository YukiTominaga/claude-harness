---
type: regex
target: { source: file, path: .harness/final/01/verdict.json }
flags: is
weight: 2
pattern: '"blockingIssues"\s*:\s*\[(?:(?!"nonBlockingIssues")[\s\S])*?(?:restart|re-start|os\.remove|wipe|startup|start-up|on start|persist)'
---
