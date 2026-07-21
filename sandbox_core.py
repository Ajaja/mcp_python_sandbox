"""
Shared sandbox definition: the whitelisted builtins, whitelisted
calculation modules, and the restricted `__import__`.

This is imported by sandbox_runner.py, which actually executes user code
in its own subprocess. Keeping the whitelist here (rather than duplicated)
means sandbox_server.py and sandbox_runner.py can't drift out of sync.
"""

import collections
import datetime
import decimal
import fractions
import itertools
import math
import statistics

# --- Sandbox whitelist -------------------------------------------------

SAFE_BUILTINS = {
    "abs": abs, "min": min, "max": max, "sum": sum, "round": round,
    "len": len, "range": range, "enumerate": enumerate, "sorted": sorted,
    "pow": pow, "divmod": divmod, "int": int, "float": float, "str": str,
    "bool": bool, "list": list, "dict": dict, "tuple": tuple, "set": set,
    "print": print, "zip": zip, "map": map, "filter": filter,
    "True": True, "False": False, "None": None,
}

# Directly available "by name" in sandboxed code — the ones a calculation
# task is likely to reach for on purpose.
SAFE_MODULES = {
    "math": math,
    "statistics": statistics,
    "datetime": datetime,
    "decimal": decimal,
    "fractions": fractions,
    "itertools": itertools,
    "collections": collections,
}

# Popular calculation libraries — added only if installed, so the sandbox
# still works with just the stdlib if extras aren't present. See
# requirements.txt to install all of them.
_OPTIONAL_MODULES = {
#    "numpy": "numpy",
#    "np": "numpy",        # common alias, same module object
#    "pandas": "pandas",
#    "pd": "pandas",        # common alias
#    "scipy": "scipy",
#    "sympy": "sympy",
}

for _name, _module in _OPTIONAL_MODULES.items():
    try:
        SAFE_MODULES[_name] = __import__(_module)
    except ImportError:
        pass  # library not installed — just won't be available in the sandbox

# Some of these libraries (numpy/pandas/sympy especially) do their own
# lazy, internal imports of submodules the first time certain features are
# used (e.g. printing an array, or `date.today()` pulling in `time`).
#
# Scientific libraries (SciPy especially) also pull in an unbounded,
# ever-changing set of ordinary stdlib helpers internally — unittest,
# argparse, textwrap, dataclasses, and more depending on which submodule
# you touch. Trying to maintain an allow-list of "every stdlib module some
# calculation library might need internally" is a losing, high-maintenance
# battle, so instead of allow-listing safe modules we deny-list dangerous
# ones. Anything NOT in this set can be imported; these specific roots
# cannot.
#
# This is a deliberately different (weaker) tradeoff than a strict
# allow-list — see the module docstring's security caveat. It still stops
# the obvious escapes (file access, process spawning, sockets, ctypes),
# but it does NOT guarantee nothing else on your Python path could be
# imported and misused. If you install extra packages (e.g. `requests`,
# `boto3`) into this environment, they become importable too, since they
# aren't stdlib and aren't on this list — add them here explicitly if you
# don't want the sandbox to reach them.
_BLOCKED_IMPORT_ROOTS = {
    "os", "sys", "subprocess", "socket", "shutil", "pathlib", "pickle",
    "ctypes", "importlib", "runpy", "code", "pdb", "resource", "mmap",
    "multiprocessing", "signal", "fcntl", "tty", "pty",
    "pwd", "grp", "syslog", "sysconfig", "distutils", "ensurepip", "venv",
    "zipimport", "webbrowser", "http", "urllib", "ftplib", "smtplib",
    "telnetlib", "poplib", "imaplib", "platform", "sqlite3", "shelve",
    "tempfile", "glob", "asyncio",
}

# --- Import enforcement -------------------------------------------------
#
# We enforce this deny-list with a `__import__` wrapper rather than
# `sys.addaudithook`. That looks backwards — a wrapper adds a Python-level
# frame around every import call, which is exactly what seemed to cause a
# Windows-specific hang the first time `scipy.integrate` was imported (see
# git history / changelog for that report). But `addaudithook`'s "import"
# event turns out to have a disqualifying gap: it does NOT fire for a
# module that's already in sys.modules. Since SAFE_MODULES pre-imports
# numpy/pandas/scipy/sympy at startup, and THEY transitively import
# `pickle`, `ctypes`, `shutil`, and `subprocess` as a side effect, those
# end up cached before any sandboxed code ever runs — so an audit-hook-only
# deny-list silently let `import os`, `import pickle`, etc. straight
# through. Confirmed by testing: only genuinely fresh (non-cached) blocked
# imports were ever caught.
#
# A `__import__` wrapper doesn't have that gap: it checks the requested
# name against the deny-list *before* deciding whether to call the real
# `__import__` at all, so it blocks a name consistently whether or not the
# module happens to be cached.
#
# To handle the Windows concern without giving up correctness, we pair
# this wrapper with a hard, subprocess-level timeout (see
# sandbox_runner.py / sandbox_server.py): each execution runs in its own
# short-lived process via `subprocess.run(..., timeout=...)`, which
# forcibly kills the child if it doesn't return in time. That makes
# "hangs forever" structurally impossible regardless of the exact cause —
# worst case, the tool call returns a timeout error instead of blocking.
# If SciPy's first cold import is simply slow on a given Windows machine
# (compiled-extension loading, antivirus scanning, etc.), pass a larger
# `timeout` for that call rather than lowering the sandbox's guarantees.


def _restricted_import(name, globals=None, locals=None, fromlist=(), level=0):
    root = name.split(".")[0]
    if root in _BLOCKED_IMPORT_ROOTS:
        raise ImportError(f"import of '{name}' is not permitted in this sandbox")
    return __import__(name, globals, locals, fromlist, level)


SAFE_BUILTINS["__import__"] = _restricted_import


def build_safe_globals() -> dict:
    """Fresh globals dict for one execution."""
    return {"__builtins__": dict(SAFE_BUILTINS), **SAFE_MODULES}
