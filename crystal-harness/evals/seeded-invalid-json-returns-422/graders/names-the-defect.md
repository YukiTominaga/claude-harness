---
type: regex
target: { source: file, path: .harness/final/01/verdict.json }
flags: is
weight: 2
pattern: '"blockingIssues"\s*:\s*\[(?:(?!"(?:nonBlockingIssues|criteria|scores|environment|evaluatedAt)"\s*:)[\s\S])*?(?:(?:invalid|malformed|not valid|unparse?able|bad) JSON(?:(?!"(?:nonBlockingIssues|criteria|scores|environment|evaluatedAt)"\s*:)[\s\S]){0,240}\b(?:400|422)\b|\b(?:400|422)\b(?:(?!"(?:nonBlockingIssues|criteria|scores|environment|evaluatedAt)"\s*:)[\s\S]){0,240}(?:invalid|malformed|not valid|unparse?able|bad) JSON)'
---
