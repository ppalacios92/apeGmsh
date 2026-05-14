"""Unit tests for :class:`OutputBadge` — status-bar count surfacer.

Tests use vanilla LogRouter + OutputDock + a dummy ``QDockWidget``
to verify the badge widget's display and click behavior without
needing a full ResultsViewer / VTK plotter.
"""
from __future__ import annotations

import pytest

pytest.importorskip("qtpy.QtCore")

from apeGmsh.viewers.ui._log_router import LogRouter
from apeGmsh.viewers.ui._output_badge import OutputBadge
from apeGmsh.viewers.ui._output_dock import OutputDock


@pytest.fixture(scope="module")
def qapp():
    from qtpy import QtWidgets
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    yield app


@pytest.fixture
def harness(qapp):
    """Yield ``(router, output_dock, dock_widget, badge)``."""
    from qtpy import QtWidgets
    router = LogRouter()
    output_dock = OutputDock(router)
    # A real QDockWidget the badge can target via setVisible / raise_.
    dock_widget = QtWidgets.QDockWidget("Output", None)
    dock_widget.setWidget(output_dock.widget)
    dock_widget.setVisible(False)
    badge = OutputBadge(output_dock, dock_widget)
    try:
        yield router, output_dock, dock_widget, badge
    finally:
        try:
            output_dock.close()
        except Exception:
            pass


# =====================================================================
# Hidden when zero
# =====================================================================


def test_badge_hidden_when_counts_zero(harness):
    _router, _output, _dw, badge = harness
    assert not badge.is_visible
    assert badge.text == ""


# =====================================================================
# Display
# =====================================================================


def test_badge_shows_warnings_only(harness):
    _router, output, _dw, badge = harness
    output.append("w1", "warning")
    output.append("w2", "warning")
    assert badge.is_visible
    assert "2" in badge.text
    assert "⚠" in badge.text
    assert "⛔" not in badge.text


def test_badge_shows_errors_only(harness):
    _router, output, _dw, badge = harness
    output.append("e1", "error")
    assert badge.is_visible
    assert "⛔" in badge.text
    assert "1" in badge.text
    assert "⚠" not in badge.text


def test_badge_shows_both_when_present(harness):
    _router, output, _dw, badge = harness
    output.append("w", "warning")
    output.append("e1", "error")
    output.append("e2", "error")
    text = badge.text
    assert "⚠" in text
    assert "⛔" in text
    # Errors listed first (more important).
    assert text.index("⛔") < text.index("⚠")
    assert "1" in text   # warnings
    assert "2" in text   # errors


def test_badge_ignores_info_severity(harness):
    _router, output, _dw, badge = harness
    output.append("just info", "info")
    assert not badge.is_visible
    assert badge.text == ""


# =====================================================================
# Live updates via router signal
# =====================================================================


def test_badge_updates_from_router_signal(harness, qapp):
    router, _output, _dw, badge = harness
    router.warning("from-signal")
    qapp.processEvents()
    assert badge.is_visible
    assert "⚠" in badge.text


# =====================================================================
# Clear → badge hides again
# =====================================================================


def test_badge_hides_after_clear(harness):
    _router, output, _dw, badge = harness
    output.append("w", "warning")
    output.append("e", "error")
    assert badge.is_visible
    output.clear()
    assert not badge.is_visible
    assert badge.text == ""


# =====================================================================
# Click → dock visible + raised
# =====================================================================


def test_badge_click_makes_dock_visible(harness):
    _router, output, dock_widget, badge = harness
    output.append("w", "warning")
    assert not dock_widget.isVisible()
    badge.widget.click()
    assert dock_widget.isVisible()


def test_badge_click_when_dock_already_visible_is_idempotent(harness):
    _router, output, dock_widget, badge = harness
    output.append("w", "warning")
    dock_widget.setVisible(True)
    badge.widget.click()    # Should not raise.
    assert dock_widget.isVisible()


# =====================================================================
# refresh() — manual sync
# =====================================================================


def test_refresh_reflects_current_counts(harness):
    _router, output, _dw, badge = harness
    # Mutate counts directly (simulating an out-of-band change) — the
    # badge should still come back into sync after refresh().
    output._counts["error"] = 5
    badge.refresh()
    assert "5" in badge.text
    assert "⛔" in badge.text
