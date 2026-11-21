---
type: regex
target: { source: file, path: .harness/final/01/verdict.json }
flags: is
weight: 2
pattern: '"blockingIssues"\s*:\s*\[(?:(?!"(?:nonBlockingIssues|criteria|scores|environment|evaluatedAt)"\s*:)[\s\S])*?(?:mov\w*(?:(?!"(?:nonBlockingIssues|criteria|scores|environment|evaluatedAt)"\s*:)[\s\S]){0,300}archiv|archiv\w*(?:(?!"(?:nonBlockingIssues|criteria|scores|environment|evaluatedAt)"\s*:)[\s\S]){0,300}mov)'
---
