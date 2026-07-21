# Python Sandbox MCP Server

A minimal [MCP](https://modelcontextprotocol.io) server that gives an LLM one tool, `run_python`, for doing calculations in a restricted Python sandbox — arithmetic, statistics, linear algebra, calculus, symbolic math, dataframes, dates, and more, without giving it a real shell.

## Files

| File | Purpose |
|---|---|
| `sandbox_server.py` | The MCP server itself. Exposes the `run_python` tool. Run this. |
| `sandbox_runner.py` | Entry point launched in its own subprocess for every single call. Reads code from stdin, executes it, exits. |
| `sandbox_core.py` | Shared sandbox definition: allowed builtins, available libraries, and the import restriction. Imported by the runner. |
| `requirements.txt` | Python dependencies. |

## How it works

1. The LLM calls `run_python(code, timeout=5)`.
2. `sandbox_server.py` launches `sandbox_runner.py` as a **fresh subprocess** and pipes `code` to it over stdin.
3. `sandbox_runner.py` builds a restricted globals dict (from `sandbox_core.py`) and `exec()`s the code in it. Anything printed goes to the subprocess's real stdout.
4. The parent process captures that stdout with a **hard wall-clock timeout** (`subprocess.run(..., timeout=...)`). If the code doesn't finish in time, the child is forcibly killed and a timeout error is returned — the tool call can never hang indefinitely.

Running each call in its own subprocess (rather than `exec`-ing inside the long-lived server process) also sidesteps a couple of gotchas:
- A timeout implemented with `signal.alarm` only works on the main thread, but MCP frameworks commonly invoke tools from a worker thread — `subprocess.run`'s timeout doesn't care which thread calls it.
- It's an actual hard timeout (kill the process) rather than a cooperative one that depends on the sandboxed code checking for a pending signal between bytecode instructions.

## What's available inside the sandbox

**Builtins:** a small whitelist — `abs`, `min`, `max`, `sum`, `round`, `len`, `range`, `enumerate`, `sorted`, `pow`, `divmod`, `int`, `float`, `str`, `bool`, `list`, `dict`, `tuple`, `set`, `print`, `zip`, `map`, `filter`, and the constants `True`/`False`/`None`. No `open`, `eval`, `input`, etc.

**Modules already in scope by name** (no `import` needed, though it also works):
- `math`, `statistics`, `datetime`, `decimal`, `fractions`, `itertools`, `collections` (always available)
- `numpy` (also as `np`), `pandas` (also as `pd`), `scipy`, `sympy` — available if installed; the sandbox degrades gracefully without them

**`import` is allowed**, but a fixed deny-list of modules is blocked regardless of how they're reached (`os`, `sys`, `subprocess`, `socket`, `shutil`, `pathlib`, `pickle`, `ctypes`, `importlib`, and similar — see `_BLOCKED_IMPORT_ROOTS` in `sandbox_core.py` for the full list). Anything not on that list — including submodules of the libraries above, like `from scipy.integrate import quad` — is importable.

## Why a deny-list instead of an allow-list

An earlier version tried to allow-list every module the sandbox should permit. In practice, SciPy/NumPy/Pandas/SymPy pull in an unbounded, ever-shifting set of ordinary stdlib helpers internally (`unittest`, `argparse`, `textwrap`, `dataclasses`, ...) just to initialize themselves, and enumerating all of them was a losing battle. Blocking the specific modules that grant file, process, or network access — and allowing everything else — is far more maintainable, at the cost of a weaker guarantee (see **Security model** below).

## Security model — read this before exposing it to anyone but yourself

This is a **lightweight** sandbox meant to let an LLM do calculations, not a hardened security boundary. Specifically:

- The deny-list only covers modules already known to grant dangerous access. If you install additional packages into this environment (`requests`, `boto3`, a database driver, ...), they become importable too, since they aren't stdlib and aren't on the list — add them to `_BLOCKED_IMPORT_ROOTS` if you don't want the sandbox reaching them.
- A builtins/import restriction implemented at the Python level can potentially be bypassed by a sufficiently determined attacker with code execution (e.g. via object introspection tricks to reach otherwise-unreachable objects).
- Subprocess isolation bounds *time* (via the timeout) but is not a substitute for OS-level sandboxing.

**If you need real isolation** — untrusted users, production/internet exposure — run this inside a container or VM, or use a proper sandboxing technology (gVisor, Firecracker, nsjail) instead of relying on the restrictions in this code alone.

## Setup

```bash
pip install -r requirements.txt
```

## Running

```bash
python sandbox_server.py
```

This starts the server on the stdio transport. Point an MCP client (e.g. Claude Desktop's config) at `sandbox_server.py`.

## Example

```python
run_python(code="""
import numpy as np
from scipy.integrate import quad

def integrand(x):
    return np.exp(np.sin(2 * x))

result, error = quad(integrand, 0, np.pi / 2)
print(f"{result=}")
print(f"{error=}")
""")
```

```
result=3.104379017855555
error=2.025584703747011e-10
```

Note that `run_python` only returns what's **printed** — the return value of the last expression isn't captured automatically, so sandboxed code should use `print(...)` to surface results.

## Known limitations

- `signal.alarm` isn't used, but a genuinely stuck subprocess will still hold system resources (CPU/memory) until the timeout is reached and it's killed — pick a `timeout` that fits your use case.
- No resource limits beyond wall-clock time (no memory cap, no CPU cap). Consider adding OS-level limits (e.g. `resource.setrlimit` on Linux, a container's memory limit) if that matters for your deployment.
- The deny-list is stdlib-focused; if your environment has extra third-party packages installed, review whether they need to be blocked too.
