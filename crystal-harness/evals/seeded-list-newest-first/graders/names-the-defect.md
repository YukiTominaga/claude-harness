---
type: regex
target: { source: file, path: .harness/final/01/verdict.json }
flags: is
weight: 2
pattern: '"blockingIssues"\s*:\s*\[(?:(?!"nonBlockingIssues")[\s\S])*?(?:\border\b|ordering|sorted|descending|\bDESC\b|reverse|newest|oldest)'
---
