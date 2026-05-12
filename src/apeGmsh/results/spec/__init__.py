"""apeGmsh.results.spec — recorder declaration + resolved spec + emit helpers.

Phase 8.3b relocates the recorder cluster out of ``apeGmsh.solvers``
into this sub-package:

- :mod:`apeGmsh.results.spec.declaration` — :class:`Recorders`
  declaration helper (user-facing API).
- :mod:`apeGmsh.results.spec._resolved` — resolved containers
  (:class:`ResolvedRecorderSpec`, :class:`ResolvedRecorderRecord`)
  produced by :meth:`Recorders.resolve` and consumed by the
  results-side capture / live / transcoder / writer machinery.
- :mod:`apeGmsh.results.spec._emit` — emission helpers
  (:func:`emit_logical`, :func:`to_ops_args`, :func:`mpco_ops_args`,
  :func:`line_station_gpx_path`, …) that translate a resolved spec
  into OpenSees-native recorder commands.

Canonical user import::

    from apeGmsh.results.spec import Recorders

The previous import path ``apeGmsh.solvers.Recorders`` continues to
work for one release cycle via a deprecation shim in
:mod:`apeGmsh.solvers`; same envelope pattern as the Phase-8.1 /
8.2 / 8.3a relocations.
"""
from __future__ import annotations

from ._resolved import ResolvedRecorderRecord, ResolvedRecorderSpec
from .declaration import Recorders

__all__ = [
    "Recorders",
    "ResolvedRecorderRecord",
    "ResolvedRecorderSpec",
]
