---
name: team-build
description: How a harness build is split across several generators working at the same time — writing the split plan (split.json), and the rules a builder teammate works under. Use when your prompt puts you in the splitting phase, or names you builder-<name>.
---

# Team build

With `harness.teamBuild` on, the first build of a round is done by several
generators at once, each an agent-team teammate named `builder-<name>`. Two
generators on one working tree normally collide, so a team build happens only
under a **split plan**: every builder gets paths nobody else may write, and the
surface between the builders is pinned before anyone starts. A script validates
the plan and a hook enforces it. Fixes after a failed QA round are not split —
those go to a single generator, as always.

## Splitting phase — writing `split.json`

You are a plain `harness-generator`, alone, and you write **one file and no
code**: `<round directory>/split.json`. Read `spec.md`, `config.json`, the
contract if there is one, and enough of the existing tree to know where things
live.

```json
{
  "interfaces": [
    "POST /notes {title: string 1-100, body?: string} -> 201 {id, title, body}; 422 {error} on a bad title",
    "table notes(id integer pk, title text, body text)",
    "cli exits 0 on success, 1 with the API's error message on stderr"
  ],
  "builders": [
    { "name": "api", "scope": "the HTTP API, its storage, and its tests",
      "owns": ["app.py", "tests/api/**"] },
    { "name": "cli", "scope": "the command-line client and its tests",
      "owns": ["cli/**", "tests/cli/**"] }
  ]
}
```

- **Split along seams that already exist in the product** — a server and its
  client, an API and a worker, independent feature modules. If the work has no
  such seam, write a plan with **one** builder; the build then runs as a normal
  single generator and nothing is lost. A forced split costs more in
  coordination than it saves. At most `harness.maxBuilders` builders (default 3).
- **`owns` is exact.** Each entry is one file (`app.py`) or one whole directory
  (`cli/**`); no other wildcards. No path may fall under two builders. Every file
  the build will create or change must fall under exactly one — including shared
  ones: `package.json`, a lockfile, the route table, the schema, the README. Give
  each shared file to the builder who changes it most; the others ask that
  builder for what they need. Tests belong to the builder whose code they test.
- **`interfaces` is the agreement the builders build against** without waiting for
  each other: routes with payload and status shapes, table and column names,
  exported function signatures, file formats, ports, environment variables. Pin
  what one builder's code will call in another's. Do not pin anything internal to
  one builder. If `spec.md` or the contract already fixes an interface, copy it.
- `name` is lowercase letters, digits and hyphens; it becomes `builder-<name>`,
  and the builder's report `reports/builder-<name>.md`. Do not write the
  `builder-` prefix into `name` yourself.
- `scope` is one sentence saying what the builder delivers, in terms of the spec.

`scripts/team_build.py validate` checks the plan; if it sends violations back,
fix exactly those. Do not start building.

## Building as `builder-<name>`

Your prompt names you `builder-<name>` and gives you your scope, your paths, the
pinned interfaces, and the other builders. You are a `harness-generator` — every
rule in your agent definition holds — working beside others in the same working
tree, which adds these:

- **Write only your own paths.** The active plan is `.harness/split.json` (read it
  with Read). A hook denies a write anywhere else, and that denial is the design
  working, not an obstacle. If the product needs a change in someone else's path,
  message that builder by name (`builder-<theirs>`) and say exactly what you need;
  they make the change. Never route around it through the shell.
- **Build to the pinned interfaces, and trust them.** Do not wait for another
  builder's code to exist: write against the interface and test against it. If an
  interface is wrong or missing something, do not quietly deviate — message every
  builder it touches and the lead, agree the change, and record it in your report.
- **Commit through the script, and only through it:**

  ```
  python3 "<plugin root>/scripts/team_build.py" commit --builder <name> -m "feat: …"
  ```

  It commits exactly your paths. `git add`, `git commit`, `git stash`, `git reset`,
  `git checkout` and their relatives are denied to builders, because each of them
  acts on the whole tree and the others are mid-edit in it. Read-only git is fine.
  Commit at every meaningful checkpoint, as usual.
- **Test your own part.** Run the tests in your paths. The whole suite, the full
  build and the app as a whole may be red for reasons that are another builder's
  unfinished work — that is expected until everyone is done, and it is not yours
  to fix. If you start the application to check your part, the port may be in use
  by another builder: use another port for your check, and stop what you started.
- **Answer the other builders.** A question from a peer about your interface is
  blocking them. Reply before you go on.
- **Finish cleanly.** Write your report to
  `<round directory>/reports/builder-<name>.md` using the generator's
  `build-notes.md` template (it is the one file you may write under `.harness/`),
  commit everything you own, then tell the lead you are done: the commits you
  made, your test results verbatim, what is partial, and any interface change you
  agreed. Do not summarise the build as successful.
- **If that `Write` is rejected by a rule you did not expect**, do what your agent
  definition says for `build-notes.md`, with `reports/builder-<name>.md` as the
  name in both markers. Write it no other way. Tell the lead, in your done
  message, that the report was refused and is in your final response. Then end
  your turn with the `Write rejected:` line and the report between
  `<!-- crystal-harness:begin reports/builder-<name>.md -->` and
  `<!-- crystal-harness:end reports/builder-<name>.md -->`, and stop. A hook keeps
  the text you end your turn with; a copy inside a message to the lead is not
  what gets placed.

When the builders have stopped, a script checks what they left: uncommitted work,
a changed path nobody owns, a missing report. The lead will pass any such line
back to you verbatim; fix exactly that.
