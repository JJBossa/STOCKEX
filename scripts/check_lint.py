"""Run the full linters and reject differences from the reviewed debt."""

import argparse
import hashlib
import json
import subprocess
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASELINE = ROOT / ".github" / "lint-baseline.json"
CRITICAL = ("E9", "F63", "F7", "F82")


def run(*args, allowed=(0,)):
    process = subprocess.run(args, cwd=ROOT, text=True, capture_output=True)
    if process.stderr:
        print(process.stderr, file=sys.stderr, end="")
    if process.returncode not in allowed:
        raise SystemExit(
            process.stdout or f"{args[0]} exited with {process.returncode}"
        )
    return process.stdout


def flake8_findings(files):
    output = run(
        sys.executable,
        "-m",
        "flake8",
        "--isolated",
        "--max-line-length=120",
        "--format=%(path)s|%(row)d|%(col)d|%(code)s|%(text)s",
        *files,
        allowed=(0, 1),
    )
    sources = {}
    for line in output.splitlines():
        path, row, col, code, message = line.split("|", 4)
        if code.startswith(CRITICAL):
            raise SystemExit(f"Flake8: {path}:{row}:{col} {code} {message}")
        if path not in sources:
            sources[path] = (ROOT / path).read_text(encoding="utf-8").splitlines()
        source = sources[path][int(row) - 1]
        yield path, (code, message, col, source), f"{path}:{row}:{col} {code} {message}"


def black_findings(files):
    output = run(
        sys.executable,
        "-m",
        "black",
        "--diff",
        "--quiet",
        "--workers=1",
        "--target-version=py311",
        *files,
    )
    path = ""
    changes = []
    for line in output.split("\n"):
        if changes and (line.startswith("--- ") or not line.startswith(("+", "-"))):
            yield path, tuple(changes), f"{path}: Black\n" + "\n".join(changes)
            changes = []
        if line.startswith("--- "):
            path = line[4:].split("\t", 1)[0]
        elif line.startswith(("+", "-")) and not line.startswith("+++ "):
            changes.append(line)


def inventory(findings):
    counts = Counter()
    descriptions = {}
    for path, content, description in findings:
        fingerprint = hashlib.sha256(repr(content).encode()).hexdigest()
        key = f"{path}:{fingerprint}"
        counts[key] += 1
        descriptions[key] = description
    return counts, descriptions


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write-baseline", action="store_true")
    args = parser.parse_args()
    files = sorted(
        {
            path
            for path in run(
                "git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"
            ).split("\0")
            if path.endswith(".py") and (ROOT / path).is_file()
        }
    )
    if not files:
        raise SystemExit("No Python files found")
    previous = (
        {} if args.write_baseline else json.loads(BASELINE.read_text(encoding="utf-8"))
    )
    current = {}
    failed = False
    for name, findings in (("flake8", flake8_findings), ("black", black_findings)):
        counts, descriptions = inventory(findings(files))
        current[name] = counts
        print(f"{name}: {sum(counts.values())} historical entries")
        if args.write_baseline:
            continue
        allowed = Counter(previous[name])
        for key, count in sorted((counts - allowed).items()):
            print(f"New ({count}): {descriptions[key]}", file=sys.stderr)
            failed = True
        if allowed - counts:
            print(f"{name}: remove stale entries from the baseline", file=sys.stderr)
            failed = True
    if args.write_baseline:
        BASELINE.write_text(json.dumps(current, sort_keys=True, indent=2) + "\n")
    return int(failed)


if __name__ == "__main__":
    sys.exit(main())
