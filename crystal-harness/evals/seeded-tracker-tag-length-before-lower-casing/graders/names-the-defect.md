---
type: regex
target: { source: file, path: .harness/final/01/verdict.json }
flags: is
weight: 2
pattern: '"blockingIssues"\s*:\s*\[(?:(?!"(?:nonBlockingIssues|criteria|scores|environment|evaluatedAt)"\s*:)[\s\S])*?(?:(?:length|longer than|characters|over-?long|\blimit)(?:(?!"(?:nonBlockingIssues|criteria|scores|environment|evaluatedAt)"\s*:)[\s\S]){0,300}lower|lower(?:(?!"(?:nonBlockingIssues|criteria|scores|environment|evaluatedAt)"\s*:)[\s\S]){0,300}(?:length|longer than|characters|over-?long|\blimit))'
---
