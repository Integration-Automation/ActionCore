"""The Python builtins an action list may call: one allowlist for every executor that registers builtins."""
from __future__ import annotations

import builtins
from typing import Callable, Dict, FrozenSet

# Anything that can run code, reach attributes or namespaces, or touch files and stdin (eval, exec, compile,
# __import__, open, input, getattr, globals, ...) is left out, because action lists also arrive over sockets.
SAFE_BUILTINS: FrozenSet[str] = frozenset({
    "abs", "all", "any", "ascii", "bin", "callable", "chr", "divmod",
    "format", "hash", "hex", "len", "max", "min", "oct", "ord", "pow",
    "print", "repr", "round", "sorted", "sum",
})


def safe_builtin_commands() -> Dict[str, Callable[..., object]]:
    """Return ``{name: builtin}`` for every name in :data:`SAFE_BUILTINS`, in name order."""
    return {name: getattr(builtins, name) for name in sorted(SAFE_BUILTINS)}
