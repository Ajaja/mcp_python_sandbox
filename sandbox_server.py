"""
A minimal MCP server that gives an LLM a `run_python` tool for doing
calculations in a restricted Python sandbox.

Sandbox design:
- Only a small whitelist of safe builtins is exposed (no `open`, `eval`,
  `input`, os/sys access, etc.)
- A curated set of calculation libraries (math, statistics, datetime,
  decimal, fractions, itertools, collections, numpy, pandas, scipy,
  sympy) are available by name, with `import` restricted to a fixed
  allow-list (see sandbox_core.py) via a sys.addaudithook — no
  `__import__` monkey-patching, which caused import-lock hangs on
  Windows with libraries like SciPy.
- Each call runs in its own short-lived subprocess (sandbox_runner.py),
  with a hard wall-clock timeout via subprocess.run(..., timeout=...).
  This works regardless of which thread the MCP framework invokes the
  tool from, and can forcibly kill a hung/runaway execution.

This is a *lightweight* sandbox suitable for arithmetic/calculation
tasks. It is NOT a hard security boundary — a determined attacker with
code execution can often find ways around a builtins-based sandbox
(e.g. via object introspection). If you need real isolation (untrusted
users, production exposure), run this inside a container/VM or use a
proper sandboxing solution (e.g. gVisor, Firecracker, nsjail) instead of
relying on Python-level restrictions alone.

Requirements:
    pip install -r requirements.txt

Run directly for local testing (stdio transport):
    python sandbox_server.py

Or point an MCP client (Claude Desktop, etc.) at this script.
"""

import os
import subprocess
import sys

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("python-sandbox")

_RUNNER_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sandbox_runner.py")


@mcp.tool()
def run_python(code: str, timeout: int = 60) -> str:
    """
    Execute Python code in a restricted sandbox for calculations and return whatever was printed to stdout.

    Only basic builtins plus a curated set of calculation modules are available: `math`, `statistics`, `datetime`, `decimal`, `fractions`, `itertools`, `collections`, `numpy`, `pandas`, `scipy` and `sympy`.
    There is no file, network, or OS access. 
    `import` works but is restricted to those libraries and their submodules (e.g. `from scipy.integrate import quad` is fine; `import os` is not). 
    Use `print(...)` to see results — the return value of the last expression is not captured automatically.

    Args:
        code: Python source code to execute.
        timeout: Max seconds allowed before execution is aborted (default is 60).
    """
    try:
        proc = subprocess.run(
            [sys.executable, _RUNNER_PATH],
            input=code,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return f"Error: execution exceeded {timeout}s timeout"

    if proc.returncode != 0:
        err = proc.stderr.strip() or f"process exited with code {proc.returncode}"
        return err

    output = proc.stdout
    return output if output else "(no output — use print() to see results)"


if __name__ == "__main__":
    mcp.run()
