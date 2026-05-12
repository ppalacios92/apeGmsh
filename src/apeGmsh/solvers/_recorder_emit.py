"""Deprecation shim for the recorder emit helpers relocation (Phase 8.3b).

Canonical home is :mod:`apeGmsh.results.spec._emit`.  The helpers
translate a resolved recorder spec into OpenSees-native recorder
syntax for the live driver, the Tcl/Py emit path, and the MPCO
binding — they live in ``results.spec`` because the spec they
consume lives there too.
"""
from __future__ import annotations

import warnings
from typing import Any

from apeGmsh.results.spec import _emit as _canonical


def __getattr__(name: str) -> Any:
    """Forward attribute access to the canonical module.

    Used so that ``from apeGmsh.solvers._recorder_emit import _X``
    keeps working even for underscore-prefixed names (which a plain
    star-import shim could not re-export).
    """
    return getattr(_canonical, name)


__all__ = getattr(_canonical, "__all__", [
    name for name in vars(_canonical) if not name.startswith("_")
])

warnings.warn(
    "apeGmsh.solvers._recorder_emit is deprecated; import from "
    "apeGmsh.results.spec._emit instead.",
    DeprecationWarning,
    stacklevel=2,
)
