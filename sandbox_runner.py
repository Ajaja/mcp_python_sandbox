"""
Runs inside its own subprocess, once per `run_python` call. Reads code
from stdin, executes it in the restricted sandbox defined in
sandbox_core.py, and lets print() output go straight to this process's
real stdout (which the parent captures).

Using a subprocess (rather than exec-ing in the long-lived server
process) gives us two things a signal-based approach can't:
  - A timeout that works no matter which thread the MCP framework calls
    the tool from (signal.alarm only works on the main thread).
  - A *hard* timeout: subprocess.run(..., timeout=...) can forcibly kill
    the process if it hangs, rather than relying on the sandboxed code
    to cooperatively check for a pending signal.
"""

import sys

import sandbox_core


def main() -> int:
    code = sys.stdin.read()

    safe_globals = sandbox_core.build_safe_globals()

    try:
        exec(code, safe_globals)
    except Exception as e:
        print(f"Error: {type(e).__name__}: {e}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
