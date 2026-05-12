"""apeGmsh.results.spec — recorder declaration + resolved spec + emit helpers.

Phase 8.3b relocates the recorder cluster out of ``apeGmsh.solvers``.

Sub-modules land here in commits 2--4 of the relocation:

- :mod:`apeGmsh.results.spec._emit` — emission helpers
  (:func:`emit_logical`, :func:`to_ops_args`, :func:`mpco_ops_args`,
  :func:`line_station_gpx_path`, …).
- :mod:`apeGmsh.results.spec._resolved` — resolved containers
  (:class:`ResolvedRecorderSpec`, :class:`ResolvedRecorderRecord`).
- :mod:`apeGmsh.results.spec.declaration` — :class:`Recorders`
  declaration helper.

The umbrella public surface is finalized in commit 5 once all three
sub-modules are in place.
"""
from __future__ import annotations
