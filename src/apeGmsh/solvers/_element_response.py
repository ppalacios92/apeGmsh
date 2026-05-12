"""Deprecation shim for the element response catalog relocation (Phase 8.3a).

Canonical home is :mod:`apeGmsh.opensees._response_catalog`.  The
catalog IS OpenSees-specific — it maps each OpenSees element class and
integration rule to the response tokens (forces, stresses, strains,
fibers, layers, …) the element produces.  Results-side modules import
it from the bridge package; that is a one-way dependency by design.
"""
from __future__ import annotations

import warnings

from apeGmsh.opensees._response_catalog import *  # noqa: F401,F403
from apeGmsh.opensees import _response_catalog as _canonical

# Re-export the module attribute names so ``from apeGmsh.solvers._element_response import X``
# resolves any public name the canonical module exposes.
__all__ = getattr(_canonical, "__all__", [
    name for name in vars(_canonical) if not name.startswith("_")
])

warnings.warn(
    "apeGmsh.solvers._element_response is deprecated; import from "
    "apeGmsh.opensees._response_catalog instead.",
    DeprecationWarning,
    stacklevel=2,
)
