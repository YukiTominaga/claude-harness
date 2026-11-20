---
type: regex
target: { source: file, path: .harness/final/01/verdict.json }
flags: is
weight: 2
pattern: '"blockingIssues"\s*:\s*\[(?:(?!"nonBlockingIssues")[\s\S])*?(?:(?:unknown|non-?existent|missing|never[- ]existed|does not exist|doesn.t exist|no such|absent|already[- ]deleted)[\s\S]{0,200}\b(?:204|404)\b|\b(?:204|404)\b[\s\S]{0,200}(?:unknown|non-?existent|missing|never[- ]existed|does not exist|doesn.t exist|no such|absent|already[- ]deleted))'
---
