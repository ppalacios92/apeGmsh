"""Streaming write-out (ADR 0065 Tier 1).

``TclEmitter.write_to`` / ``PyEmitter.write_to`` stream the internal line
buffer straight to a handle, avoiding both the ``list(self._lines)`` copy
of :meth:`lines` and the deck-sized joined string of
``"\\n".join(lines()) + "\\n"``. These tests lock two properties:

* **byte-identity** — the streamed bytes equal the old join output; and
* **bounded write-time allocation** — the Python allocation incurred *by
  the write itself* is a small fraction of the join path's, independent of
  deck size (the actual memory win behind the ADR).
"""
from __future__ import annotations

import tracemalloc

import pytest

from apeGmsh.opensees.emitter.py import PyEmitter
from apeGmsh.opensees.emitter.tcl import TclEmitter


class _NullSink:
    """A ``write``-only sink that discards output.

    Isolates the *Python-side* allocation of marshalling the deck to a
    handle from any OS/file-buffer cost, so tracemalloc sees only what the
    two strategies allocate.
    """

    def write(self, _s: str) -> None:  # noqa: D401 - trivial
        pass


def _fill_tcl(n: int) -> TclEmitter:
    em = TclEmitter()
    em.model(ndm=3, ndf=3)
    for i in range(1, n + 1):
        em.node(i, float(i), float(2 * i), float(3 * i))
    return em


def _fill_py(n: int) -> PyEmitter:
    em = PyEmitter()
    em.model(ndm=3, ndf=3)
    for i in range(1, n + 1):
        em.node(i, float(i), float(2 * i), float(3 * i))
    return em


@pytest.mark.parametrize("fill", [_fill_tcl, _fill_py])
def test_write_to_is_byte_identical_to_join(fill, tmp_path) -> None:
    em = fill(2_000)
    expected = "\n".join(em.lines()) + "\n"

    path = tmp_path / "deck.txt"
    with open(path, "w", encoding="utf-8") as f:
        em.write_to(f)

    assert path.read_text(encoding="utf-8") == expected


@pytest.mark.parametrize("fill", [_fill_tcl, _fill_py])
def test_write_to_allocates_far_less_than_join(fill) -> None:
    # A deck large enough that the join path's transient allocation
    # (list copy + one deck-sized string) is unambiguous against noise.
    em = fill(50_000)
    sink = _NullSink()

    tracemalloc.start()
    tracemalloc.reset_peak()
    sink.write("\n".join(em.lines()) + "\n")
    _, join_peak = tracemalloc.get_traced_memory()
    tracemalloc.reset_peak()
    em.write_to(sink)
    _, stream_peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    # The join path allocates a full list copy plus the joined deck string
    # (hundreds of KB at 50k nodes); streaming allocates ~nothing. Demand
    # at least a 10x reduction to stay robust across interpreters.
    assert stream_peak * 10 < join_peak, (
        f"streaming peak {stream_peak} not << join peak {join_peak}"
    )
