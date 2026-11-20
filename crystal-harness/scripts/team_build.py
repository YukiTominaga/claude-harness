#!/usr/bin/env python3
"""Team build: several builders on one working tree, kept apart by code.

With `harness.teamBuild` on, the first build of a round is done by up to
`harness.maxBuilders` generator teammates working at the same time. Two
generators on one working tree collide — that is why the harness otherwise runs
one at a time — so a team build is only allowed under a **split plan** that gives
every builder a set of paths nobody else may touch, and the pieces of that
agreement that can be checked are checked here rather than asked for in a prompt.

Subcommands:

    team_build.py validate <split.json>   shape, builder count, disjoint ownership
    team_build.py activate <split.json>   validate, then install it as .harness/split.json
    team_build.py deactivate              remove .harness/split.json
    team_build.py commit --builder <name> -m <message>
                                          commit exactly that builder's owned paths
    team_build.py check                   after the builders stop: uncommitted work,
                                          paths changed that nobody owns, missing reports
    team_build.py report                  join reports/<builder>.md into report.md
    team_build.py gate                    PreToolUse hook on Agent: who may be named what

`.harness/split.json` is the ACTIVE plan. The ownership guard reads it to decide
what a `builder-<name>` teammate may write, so it exists only between `activate`
and `deactivate`, and no agent may write it.

A split plan:

    {
      "interfaces": ["POST /notes {title, body?} -> 201 {id, title, body}", "..."],
      "builders": [
        {"name": "api", "scope": "the HTTP API and its storage", "owns": ["app.py", "tests/api/**"]},
        {"name": "cli", "scope": "the command-line client",      "owns": ["cli/**", "tests/cli/**"]}
      ]
    }

`owns` entries are either one file (`app.py`) or a whole directory (`cli/**`).
Nothing cleverer is accepted, because those two forms are the ones for which
"do these overlap" has an exact answer.
"""

import argparse
import datetime
import json
import os
import re
import subprocess
import sys

try:
    import fcntl
except ImportError:  # no flock: commits are then serialised only by git's own index lock
    fcntl = None

ROLES = ("harness-planner", "harness-generator", "harness-evaluator", "harness-investigator")
# Roles the guard recognises by agent type and that are never teammates: under a
# name, a hook would no longer see what they are.
NEVER_NAMED = ("harness-evaluator", "harness-investigator")
BUILDER_PREFIX = "builder-"
NAME_RE = re.compile(r"^[a-z][a-z0-9-]{0,23}$")
ACTIVE = os.path.join(".harness", "split.json")
DEFAULT_MAX_BUILDERS = 3


def read_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def git(project_dir, *args, check=True):
    proc = subprocess.run(["git", "-C", project_dir, *args], capture_output=True, text=True)
    if check and proc.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {proc.stderr.strip() or proc.stdout.strip()}")
    return proc


def max_builders(project_dir):
    try:
        value = read_json(os.path.join(project_dir, ".harness", "config.json"))["harness"]["maxBuilders"]
        if isinstance(value, int) and not isinstance(value, bool) and value >= 1:
            return value
    except Exception:  # noqa: BLE001
        pass
    return DEFAULT_MAX_BUILDERS


def normalize_own(entry):
    """('file'|'dir', normalized path) for an `owns` entry, or (None, reason)."""
    if not isinstance(entry, str) or not entry.strip():
        return None, "must be a non-empty string"
    text = entry.strip().replace("\\", "/")
    kind = "file"
    if text.endswith("/**"):
        kind, text = "dir", text[:-3]
    elif text.endswith("/"):
        kind, text = "dir", text[:-1]
    if any(ch in text for ch in "*?[]{}"):
        return None, "only `path/to/file` and `path/to/dir/**` are accepted — no other wildcards"
    if text.startswith("/") or re.match(r"^[A-Za-z]:", text):
        return None, "must be relative to the project root"
    parts = [p for p in text.split("/") if p not in ("", ".")]
    if not parts:
        return None, "would own the whole project — give each builder a part of it"
    if ".." in parts:
        return None, "must not contain `..`"
    if parts[0].casefold() in (".harness", ".git"):
        return None, f"must not be under {parts[0]}/"
    return kind, "/".join(parts)


def owns_path(owned, rel):
    """Does a normalized (kind, path) entry cover the project-relative path `rel`?"""
    kind, path = owned
    a, b = path.casefold(), rel.replace("\\", "/").casefold()
    return b == a if kind == "file" else (b == a or b.startswith(a + "/"))


def overlaps(first, second):
    (k1, p1), (k2, p2) = first, second
    a, b = p1.casefold(), p2.casefold()
    if a == b:
        return True
    if k1 == "dir" and b.startswith(a + "/"):
        return True
    if k2 == "dir" and a.startswith(b + "/"):
        return True
    return False


def validate_plan(plan, limit):
    """Every violation in a split plan, as strings. Empty means valid."""
    errors = []
    if not isinstance(plan, dict):
        return ["top level must be a JSON object"]
    builders = plan.get("builders")
    if not isinstance(builders, list) or not builders:
        return ["`builders` must be a non-empty array"]
    if len(builders) > limit:
        errors.append(
            f"{len(builders)} builders, but harness.maxBuilders is {limit} — merge the smallest "
            "pieces rather than raising the limit"
        )

    owned = {}  # name -> [(kind, path)]
    seen_names = set()
    for i, builder in enumerate(builders):
        where = f"builders[{i}]"
        if not isinstance(builder, dict):
            errors.append(f"{where}: must be an object")
            continue
        name = builder.get("name")
        if not isinstance(name, str) or not NAME_RE.match(name):
            errors.append(f"{where}.name: must match {NAME_RE.pattern}")
            name = f"#{i}"
        elif name in seen_names:
            errors.append(f"{where}.name: {name!r} is used twice")
        seen_names.add(name)
        if not isinstance(builder.get("scope"), str) or not builder["scope"].strip():
            errors.append(f"{where}.scope: say in a sentence what this builder builds")
        owns = builder.get("owns")
        if not isinstance(owns, list) or not owns:
            errors.append(f"{where}.owns: must be a non-empty array of paths")
            owns = []
        entries = []
        for j, entry in enumerate(owns):
            kind, value = normalize_own(entry)
            if kind is None:
                errors.append(f"{where}.owns[{j}] ({entry!r}): {value}")
            else:
                entries.append((kind, value))
        owned[name] = entries

    names = list(owned)
    for i, first in enumerate(names):
        for second in names[i + 1:]:
            for a in owned[first]:
                for b in owned[second]:
                    if overlaps(a, b):
                        errors.append(
                            f"{first} owns {a[1]!r} and {second} owns {b[1]!r} — these overlap; "
                            "a path has exactly one owner"
                        )

    interfaces = plan.get("interfaces")
    if not isinstance(interfaces, list) or any(not isinstance(x, str) or not x.strip() for x in interfaces):
        errors.append("`interfaces` must be an array of strings")
    elif len(builders) > 1 and not interfaces:
        errors.append(
            "`interfaces` is empty — builders working at the same time need the surface between "
            "them pinned before they start (routes, payload shapes, table names, exported names)"
        )
    return errors


def load_active(project_dir):
    plan = read_json(os.path.join(project_dir, ACTIVE))
    if not isinstance(plan, dict) or not isinstance(plan.get("builders"), list):
        raise ValueError(f"{ACTIVE} is not a split plan")
    return plan


def entries_of(builder):
    return [e for e in (normalize_own(x) for x in builder.get("owns", [])) if e[0] is not None]


def find_builder(plan, name):
    for builder in plan["builders"]:
        if builder.get("name") == name:
            return builder
    return None


# ---------------------------------------------------------------- commands


def cmd_validate(args):
    try:
        plan = read_json(args.split)
    except Exception as exc:  # noqa: BLE001
        print(f"invalid: could not read or parse {args.split}: {exc}")
        return 1
    errors = validate_plan(plan, max_builders(args.project_dir))
    if errors:
        for line in errors:
            print(f"invalid: {line}")
        return 1
    print(f"ok: {len(plan['builders'])} builder(s), {len(plan.get('interfaces', []))} pinned interface(s)")
    return 0


def cmd_activate(args):
    project_dir = os.path.abspath(args.project_dir)
    code = cmd_validate(args)
    if code != 0:
        return code
    split_path = os.path.abspath(args.split)
    parts = os.path.relpath(os.path.dirname(split_path), project_dir).split(os.sep)
    if len(parts) != 3 or parts[0] != ".harness" or parts[1] not in ("sprints", "final"):
        print("team_build: the split plan must be .harness/sprints/NN/split.json or .harness/final/NN/split.json", file=sys.stderr)
        return 1
    plan = read_json(split_path)
    active = {
        "interfaces": plan.get("interfaces", []),
        "builders": plan["builders"],
        "roundDir": "/".join(parts),
        "base": git(project_dir, "rev-parse", "HEAD").stdout.strip(),
        "activatedAt": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    with open(os.path.join(project_dir, ACTIVE), "w", encoding="utf-8") as f:
        json.dump(active, f, indent=2, ensure_ascii=False)
        f.write("\n")
    os.makedirs(os.path.join(project_dir, active["roundDir"], "reports"), exist_ok=True)
    print(f"active: {', '.join(BUILDER_PREFIX + b['name'] for b in plan['builders'])} — base {active['base'][:7]}")
    return 0


def cmd_deactivate(args):
    path = os.path.join(args.project_dir, ACTIVE)
    if os.path.exists(path):
        os.remove(path)
        print("deactivated")
    else:
        print("no active split plan")
    return 0


def cmd_commit(args):
    """Commit one builder's owned paths, and nothing else.

    Builders share a working tree and an index, so a plain `git add -A && git
    commit` by one of them sweeps up the others' half-written files. This stages
    only what the named builder owns, under a lock so two builders cannot
    interleave between staging and committing.
    """
    project_dir = os.path.abspath(args.project_dir)
    try:
        plan = load_active(project_dir)
    except Exception as exc:  # noqa: BLE001
        print(f"team_build: no usable active split plan ({exc})", file=sys.stderr)
        return 1
    builder = find_builder(plan, args.builder)
    if builder is None:
        print(f"team_build: {args.builder!r} is not a builder in the active split plan", file=sys.stderr)
        return 1
    if not args.message.strip():
        print("team_build: the commit message is empty", file=sys.stderr)
        return 1

    # In artifacts/, which every harness project already keeps out of git.
    lock_dir = os.path.join(project_dir, ".harness", "artifacts")
    os.makedirs(lock_dir, exist_ok=True)
    lock = open(os.path.join(lock_dir, ".team-commit.lock"), "w")
    try:
        if fcntl is not None:
            fcntl.flock(lock, fcntl.LOCK_EX)
        paths = []
        for _kind, path in entries_of(builder):
            tracked = git(project_dir, "ls-files", "--", path, check=False).stdout.strip()
            if tracked or os.path.exists(os.path.join(project_dir, path)):
                paths.append(path)
        if not paths:
            print("nothing to commit: none of this builder's paths exist yet")
            return 0
        git(project_dir, "add", "-A", "--", *paths)
        staged = git(project_dir, "diff", "--cached", "--name-only", "--", *paths).stdout.strip()
        if not staged:
            print("nothing to commit: no changes in this builder's paths")
            return 0
        git(project_dir, "commit", "-q", "-m", args.message, "--", *paths)
        sha = git(project_dir, "rev-parse", "--short", "HEAD").stdout.strip()
        print(f"committed {sha}: {len(staged.splitlines())} file(s) owned by {args.builder}")
        return 0
    except RuntimeError as exc:
        print(f"team_build: {exc}", file=sys.stderr)
        return 1
    finally:
        lock.close()


def changed_paths(project_dir, base):
    """(committed since base, uncommitted) project-relative paths, .harness/ excluded."""
    committed = git(project_dir, "diff", "--name-only", "-z", base, "HEAD").stdout.split("\0")
    status = git(project_dir, "status", "--porcelain", "-z", "--untracked-files=all").stdout.split("\0")
    uncommitted, i = [], 0
    while i < len(status):
        entry = status[i]
        if len(entry) > 3:
            uncommitted.append(entry[3:])
            if entry[0] in ("R", "C"):
                i += 1  # the next field is the path it was renamed from
        i += 1

    def keep(paths):
        return sorted({p for p in paths if p and not p.replace("\\", "/").startswith(".harness/")})

    return keep(committed), keep(uncommitted)


def cmd_check(args):
    """What the builders left behind that the plan does not allow.

    Exit 0: clean. Exit 2: violations, printed one per line and addressed to the
    builder who can fix each, so the orchestrator can pass them on verbatim.
    """
    project_dir = os.path.abspath(args.project_dir)
    try:
        plan = load_active(project_dir)
        committed, uncommitted = changed_paths(project_dir, plan["base"])
    except Exception as exc:  # noqa: BLE001
        print(f"team_build: cannot check ({exc})", file=sys.stderr)
        return 1

    owners = {b["name"]: entries_of(b) for b in plan["builders"]}

    def owner_of(path):
        for name, entries in owners.items():
            if any(owns_path(entry, path) for entry in entries):
                return name
        return None

    violations = []
    for path in uncommitted:
        name = owner_of(path)
        if name:
            violations.append(f"{BUILDER_PREFIX}{name}: uncommitted work in {path} — commit it with team_build.py commit")
        else:
            violations.append(f"nobody: {path} was created or changed but no builder owns it — the owner of the nearest path should say whose it is, or remove it")
    for path in committed:
        if owner_of(path) is None:
            violations.append(f"nobody: {path} was committed but no builder owns it")
    for name in owners:
        report = os.path.join(project_dir, plan["roundDir"], "reports", f"{name}.md")
        if not os.path.isfile(report) or os.path.getsize(report) == 0:
            violations.append(f"{BUILDER_PREFIX}{name}: no report at {plan['roundDir']}/reports/{name}.md")

    if violations:
        for line in violations:
            print(line)
        return 2
    print(f"clean: {len(committed)} committed path(s), each owned by one builder; every builder reported")
    return 0


def cmd_report(args):
    project_dir = os.path.abspath(args.project_dir)
    try:
        plan = load_active(project_dir)
    except Exception as exc:  # noqa: BLE001
        print(f"team_build: no usable active split plan ({exc})", file=sys.stderr)
        return 1
    round_dir = os.path.join(project_dir, plan["roundDir"])
    lines = [
        "# Build report — team build",
        "",
        f"Built by {len(plan['builders'])} builders working at the same time from commit `{plan['base'][:7]}`, "
        "each within the paths the split plan gave it. Each section below is that builder's own report, unedited.",
        "",
        "## Pinned interfaces",
    ]
    lines += [f"- {item}" for item in plan.get("interfaces", [])] or ["- none"]
    for builder in plan["builders"]:
        name = builder["name"]
        lines += ["", f"## Builder `{name}` — {builder.get('scope', '').strip()}", "", f"Owns: {', '.join(builder.get('owns', []))}", ""]
        path = os.path.join(round_dir, "reports", f"{name}.md")
        if os.path.isfile(path):
            with open(path, "r", encoding="utf-8") as f:
                lines.append(f.read().rstrip())
        else:
            lines.append("**This builder wrote no report.**")
    with open(os.path.join(round_dir, "report.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print(f"wrote {plan['roundDir']}/report.md from {len(plan['builders'])} builder report(s)")
    return 0


def deny(reason):
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }))
    return 0


def cmd_gate(_args):
    """PreToolUse on Agent: decide who may be given a name.

    When agent teams are enabled, an Agent call that carries a `name` starts a
    teammate, and every hook then sees that teammate under its NAME, not under
    the agent type it was spawned from. The ownership guard recognises a harness
    role by agent type — so a generator or evaluator started under an arbitrary
    name would be invisible to it. This closes that: a harness generator may be
    named only `builder-<x>` for a builder `x` of the active split plan, and a
    harness evaluator may not be named at all.

    Fails closed like the guard it protects: an event it cannot read is blocked.
    """
    try:
        event = json.load(sys.stdin)
    except Exception as exc:  # noqa: BLE001
        print(f"crystal-harness team gate: could not parse the PreToolUse event ({exc}); blocking.", file=sys.stderr)
        return 2
    if not isinstance(event, dict):
        print("crystal-harness team gate: PreToolUse event was not a JSON object; blocking.", file=sys.stderr)
        return 2
    if event.get("tool_name") != "Agent":
        return 0
    tool_input = event.get("tool_input") if isinstance(event.get("tool_input"), dict) else {}
    name = tool_input.get("name")
    if not isinstance(name, str) or not name:
        return 0
    subagent_type = tool_input.get("subagent_type")
    leaf = subagent_type.rsplit(":", 1)[-1] if isinstance(subagent_type, str) else ""
    is_builder_name = name.startswith(BUILDER_PREFIX)
    if leaf not in ROLES and not is_builder_name:
        return 0

    project_dir = os.environ.get("CLAUDE_PROJECT_DIR") or event.get("cwd") or os.getcwd()

    if leaf in NEVER_NAMED:
        return deny(
            f"crystal-harness: do not give a {leaf} a name ({name!r}). A named agent becomes "
            "a teammate when agent teams are enabled, hooks then see it under that name, and the "
            f"ownership guard can no longer tell it is a {leaf}. Spawn it without `name`."
        )
    if leaf != "harness-generator":
        if is_builder_name:
            return deny(
                f"crystal-harness: the name {name!r} is reserved for harness-generator builders of a "
                "team build. Use another name, or spawn the harness-generator agent type."
            )
        return 0  # a named planner writes one file the guard does not police

    if not is_builder_name:
        return deny(
            f"crystal-harness: a harness-generator may be named only `{BUILDER_PREFIX}<name>` for a builder "
            f"in the active split plan (got {name!r}). Outside a team build, spawn it without `name`."
        )
    builder = name[len(BUILDER_PREFIX):]
    try:
        plan = load_active(project_dir)
    except Exception:  # noqa: BLE001
        return deny(
            f"crystal-harness: {name!r} cannot start — there is no active split plan (.harness/split.json). "
            "Run team_build.py activate on a validated split.json first."
        )
    if find_builder(plan, builder) is None:
        known = ", ".join(BUILDER_PREFIX + b.get("name", "?") for b in plan["builders"])
        return deny(f"crystal-harness: {name!r} is not in the active split plan. Its builders are: {known}.")
    return 0


def main():
    parser = argparse.ArgumentParser(description="crystal-harness team build")
    sub = parser.add_subparsers(dest="command", required=True)

    for name in ("validate", "activate"):
        p = sub.add_parser(name)
        p.add_argument("split")
        p.add_argument("--project-dir", default=os.getcwd())
    for name in ("deactivate", "check", "report"):
        p = sub.add_parser(name)
        p.add_argument("--project-dir", default=os.getcwd())
    p = sub.add_parser("commit")
    p.add_argument("--builder", required=True)
    p.add_argument("-m", "--message", required=True)
    p.add_argument("--project-dir", default=os.getcwd())
    sub.add_parser("gate")

    args = parser.parse_args()
    commands = {
        "validate": cmd_validate, "activate": cmd_activate, "deactivate": cmd_deactivate,
        "commit": cmd_commit, "check": cmd_check, "report": cmd_report, "gate": cmd_gate,
    }
    return commands[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
