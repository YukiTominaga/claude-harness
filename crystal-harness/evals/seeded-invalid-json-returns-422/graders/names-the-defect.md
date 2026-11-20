---
type: regex
target: { source: file, path: .harness/final/01/verdict.json }
flags: is
weight: 2
pattern: '"blockingIssues"\s*:\s*\[(?:(?!"nonBlockingIssues")[\s\S])*?(?:(?:invalid|malformed|not valid|unparse?able|bad) JSON[\s\S]{0,240}\b(?:400|422)\b|\b(?:400|422)\b[\s\S]{0,240}(?:invalid|malformed|not valid|unparse?able|bad) JSON)'
---
