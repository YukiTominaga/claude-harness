#!/usr/bin/env python3
"""No harness agent is told to write a file Claude Code will refuse to let it write.

Claude Code's Write tool refuses a subagent's write when the file's basename
matches FORBIDDEN below, and it does so while validating the tool input —
before permission rules and PreToolUse hooks run — so no allow rule, hook or
permission mode lets the write through. Until 0.16.0 the generator was told to
write `report.md`, which matches: every such write was refused, and the Bash
fallback its prompt offered was in turn stopped by auto mode as undermining
oversight. The run halted.

This test reads everything that instructs an agent — agents/, skills/,
commands/, workflows/ — collects every `.md` file name mentioned there, and
fails on any name the rule would refuse. A name with a placeholder
(`builder-<name>.md`, `h-${angle}.md`) is checked for what it can expand to.
It also checks the names the scripts give agents to write.

No framework — run it directly:

    python3 crystal-harness/scripts/test_subagent_filenames.py

Exits 0 when every case passes, 1 otherwise.
"""

import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGIN = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.dont_write_bytecode = True  # importing the scripts must not leave __pycache__/ in the plugin

# Claude Code's Write tool rule for subagents, confirmed on Claude Code
# v2.1.332: a subagent's Write whose basename matches this is rejected with
# "Subagents should return findings as text, not write report files. Include
# this content in your final response instead." (errorCode 5, telemetry event
# tengu_subagent_md_report_blocked). Copied here, not imported, because it is
# Claude Code's rule, not this plugin's; update it when Claude Code changes it.
FORBIDDEN = re.compile(r"^(REPORT|SUMMARY|FINDINGS|ANALYSIS).*\.md$", re.IGNORECASE)
# The rule only looks at the start of the name today. The name this plugin
# picked for the generator's notes keeps clear of these words anywhere in it,
# so a rule that widened from "starts with" to "contains" would still pass it.
WORDS = ("report", "summary", "findings", "analysis")

SCANNED = ("agents", "skills", "commands", "workflows")
# Runs started before 0.16.0 have the generator's notes under this name, so the
# instructions still name it — to read when build-notes.md is absent, never to
# write. Every line naming it must say "legacy"; that is what keeps an
# instruction to write it from creeping back in.
LEGACY = "report.md"

# A basename built from literal name characters and placeholders (<name>, ${name}),
# ending in .md. The look-behind keeps a match from starting mid-name, so for
# `reports/builder-<name>.md` the match is the basename `builder-<name>.md`.
NAME = re.compile(
    r"(?<![A-Za-z0-9_.\-<>}])((?:[A-Za-z0-9_.\-]|<[^<>\n/]{1,40}>|\$\{[^{}\n/]{1,40}\})+\.md)\b",
    re.IGNORECASE,
)
PLACEHOLDER = re.compile(r"<[^<>]*>|\$\{[^{}]*\}")

FAILURES = []
COUNT = 0


def check(name, condition, detail=""):
    global COUNT
    COUNT += 1
    if not condition:
        FAILURES.append(name)
    print(f"{'PASS' if condition else 'FAIL'}  {name}{'' if condition else '  <- ' + str(detail)[:2000]}")


def lens_names():
    """The lenses the evaluate workflow runs: what `<lens>.md` can be."""
    with open(os.path.join(PLUGIN, "workflows", "evaluate.js"), "r", encoding="utf-8") as f:
        return sorted(set(re.findall(r"runLens\('([a-z]+)'", f.read())))


# Placeholder names whose values are a closed set this test can enumerate. A
# placeholder name that could expand to a refused name and is not listed here
# fails: give it a fixed prefix, as builder-<name>.md has, or list its values.
EXPANSIONS = {
    "<lens>.md": lens_names,
    "${lens}.md": lens_names,
}


def could_be_refused(name):
    """Whether the rule could refuse `name`, a basename that may hold placeholders."""
    first = PLACEHOLDER.search(name)
    if first is None:
        return bool(FORBIDDEN.match(name))
    prefix = name[: first.start()].casefold()
    return any(word.startswith(prefix) or prefix.startswith(word) for word in WORDS)


def expand(name, values):
    return [PLACEHOLDER.sub(value, name, count=1) for value in values]


def scanned_files():
    for top in SCANNED:
        for dirpath, _dirs, files in os.walk(os.path.join(PLUGIN, top)):
            for filename in sorted(files):
                if filename.endswith((".md", ".js")):
                    yield os.path.join(dirpath, filename)


def violations_in(path):
    """(names seen, [violation]) for one instruction file."""
    seen, problems = set(), []
    rel = os.path.relpath(path, PLUGIN)
    with open(path, "r", encoding="utf-8") as f:
        for lineno, line in enumerate(f, 1):
            for name in NAME.findall(line):
                seen.add(name)
                where = f"{rel}:{lineno}"
                if name.casefold() == LEGACY:
                    if "legacy" not in line.casefold():
                        problems.append(f"{where}: names {name} without calling it legacy — a subagent cannot write it")
                    continue
                if not could_be_refused(name):
                    continue
                if not PLACEHOLDER.search(name):
                    problems.append(f"{where}: {name} is a name Claude Code refuses a subagent to write")
                elif name not in EXPANSIONS:
                    problems.append(
                        f"{where}: {name} could expand to a name Claude Code refuses — give it a fixed "
                        "prefix, or list its values in EXPANSIONS"
                    )
                else:
                    bad = [n for n in expand(name, EXPANSIONS[name]()) if FORBIDDEN.match(n)]
                    if bad:
                        problems.append(f"{where}: {name} expands to {', '.join(bad)}")
    return seen, problems


def main():
    # ---- the regex itself: the cases it was confirmed against
    for name, refused in (
        ("report.md", True), ("REPORT.md", True), ("Report-final.md", True), ("summary.md", True),
        ("findings-1.md", True), ("analysis.MD", True), ("build-notes.md", False), ("qa.md", False),
        ("my-report.md", False), ("report.json", False), ("builder-report-ui.md", False),
    ):
        check(f"the rule {'refuses' if refused else 'allows'} {name}", bool(FORBIDDEN.match(name)) is refused)

    # ---- every .md name the instructions mention
    all_seen, all_problems = set(), []
    for path in scanned_files():
        seen, problems = violations_in(path)
        all_seen |= seen
        all_problems += problems
    check("the scan found the names it should (sanity)",
          {"qa.md", "contract.md", "build-notes.md", "diagnosis.md"} <= all_seen, sorted(all_seen))
    check("no instruction names a file Claude Code refuses a subagent to write",
          not all_problems, "\n" + "\n".join(all_problems))
    check("the lens names were read from the evaluate workflow", lens_names() == ["api", "code", "screen", "tests"], lens_names())

    # ---- the names the scripts give agents to write
    try:
        import guard_harness_artifacts as guard
        import returned_files
        import team_build
    except ImportError as exc:
        check("the scripts that name the generator's notes import", False, exc)
    else:
        notes = returned_files.NOTES
        check("the generator's notes file avoids the refused words anywhere in its name",
              not any(word in notes.casefold() for word in WORDS) and not FORBIDDEN.match(notes), notes)
        check("the scripts agree on the notes name and the legacy name",
              guard.NOTES == team_build.NOTES == notes and guard.LEGACY_NOTES == team_build.LEGACY_NOTES
              == returned_files.LEGACY_NOTES == LEGACY,
              (guard.NOTES, team_build.NOTES, notes, guard.LEGACY_NOTES, team_build.LEGACY_NOTES))
        names = ["report", "report-ui", "summary", "findings", "analysis-api", "api", "x"]
        for builder in names:
            check(f"builder {builder!r}: a valid name", not team_build.validate_plan(
                {"interfaces": ["x"], "builders": [{"name": builder, "scope": "s", "owns": ["a/**"]},
                                                     {"name": "other", "scope": "s", "owns": ["b/**"]}]}, 3))
        refused = [
            f"{role}:{name}"
            for role, agent_type in (("generator", "crystal-harness:harness-generator"),
                                     ("evaluator", "crystal-harness:harness-evaluator"),
                                     *(("builder", f"builder-{b}") for b in names))
            for name in returned_files.placeable(agent_type)
            if FORBIDDEN.match(os.path.basename(name))
        ]
        check("no file an agent may hand back has a refused name", not refused, refused)
        check("a builder's report is reports/builder-<name>.md, whatever the name",
              all(team_build.builder_report_name(b) == f"builder-{b}.md" and not FORBIDDEN.match(team_build.builder_report_name(b))
                  for b in names), [team_build.builder_report_name(b) for b in names])

    # ---- the instructions and the parser agree on the markers
    with open(os.path.join(PLUGIN, "agents", "harness-generator.md"), "r", encoding="utf-8") as f:
        generator = f.read()
    check("the generator is told to write build-notes.md", "`build-notes.md`" in generator)
    check("the generator's fallback markers are the ones the parser reads",
          "<!-- crystal-harness:begin build-notes.md -->" in generator
          and "<!-- crystal-harness:end build-notes.md -->" in generator)
    check("the generator is no longer told to route a rejected Write through Bash",
          "<<'EOF'" not in generator and "cat >" not in generator)
    with open(os.path.join(PLUGIN, "agents", "harness-evaluator.md"), "r", encoding="utf-8") as f:
        evaluator = f.read()
    check("the evaluator is no longer told to route a rejected Write through Bash",
          "<<'EOF'" not in evaluator and "cat >" not in evaluator)

    print()
    if FAILURES:
        print(f"{len(FAILURES)} failing case(s): {', '.join(FAILURES)}")
        return 1
    print(f"all {COUNT} subagent file-name cases pass")
    return 0


if __name__ == "__main__":
    sys.exit(main())
