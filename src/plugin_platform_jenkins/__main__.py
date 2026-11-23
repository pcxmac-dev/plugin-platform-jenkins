"""`python -m plugin_platform_jenkins ...`: the plugin from the command line, its settings read from this shell's
environment (an EnvironmentLogin: JENKINS_URL, JENKINS_USER, JENKINS_TOKEN). `status` prints the status as the
platform's page gets it; `jobs` the jobs, a line each; `build JOB [NAME=value&...]` asks a job's build (the page asks
you to confirm it first; here, the command typed is the confirmation). The token is never printed."""
from __future__ import annotations

import json
import sys

from . import MACHINE
from .client import JenkinsError

USAGE = "python -m plugin_platform_jenkins status | jobs | build JOB [NAME=value&...]"


def flat(c) -> str:
    """A table's cell as text: its words with what is beneath them in brackets; a button is left out."""
    if isinstance(c, dict):
        if "form" in c:
            return ""
        return f"{c.get('text', '')} ({c['sub']})" if c.get("sub") else str(c.get("text", ""))
    return str(c)


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    what, rest = (argv[0], argv[1:]) if argv else ("status", [])
    try:
        if what == "status" and not rest:
            s = MACHINE.status()
            print(json.dumps(s, indent=1))
            return 0 if s.get("valid") else 1
        if what == "jobs" and not rest:
            s = MACHINE.status()
            print(s.get("summary", ""))
            table = next((t for t in s.get("tables", []) if t.get("title") == "Jobs"), None)
            if table is None:
                print(f"  {s.get('why') or 'no jobs read'}")
                return 1
            for row in table["rows"]:
                print("  " + "  ".join(x for x in (flat(c) for c in row) if x))
            if not table["rows"]:
                print(f"  {table.get('empty') or 'none'}")
            return 0
        if what == "build" and len(rest) in (1, 2):
            answer = MACHINE.build(*rest)
            print(answer.get("said", ""))
            for line in answer.get("lines") or []:
                print(f"  {line}")
            return 0 if answer.get("ok", True) else 1
    except ValueError as e:
        print(f"refused: {e}", file=sys.stderr)
        return 1
    except JenkinsError as e:
        print(f"failed: {e}", file=sys.stderr)
        return 1
    print(USAGE, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
