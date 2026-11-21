---
type: regex
target: { source: file, path: .harness/final/01/verdict.json }
flags: is
weight: 2
pattern: '"blockingIssues"\s*:\s*\[(?:(?!"(?:nonBlockingIssues|criteria|scores|environment|evaluatedAt)"\s*:)[\s\S])*?(?:(?:delet|remov)\w*(?:(?!"(?:nonBlockingIssues|criteria|scores|environment|evaluatedAt)"\s*:)[\s\S]){0,300}(?:block|wait)|(?:block|wait)\w*(?:(?!"(?:nonBlockingIssues|criteria|scores|environment|evaluatedAt)"\s*:)[\s\S]){0,300}(?:delet|remov)|dangling)'
---
