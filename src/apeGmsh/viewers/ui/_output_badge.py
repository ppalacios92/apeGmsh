"""OutputBadge — status-bar widget surfacing OutputDock warning/error counts.

A small ``QToolButton`` that lives in the status bar and shows a
running count of warnings and errors captured by an
:class:`OutputDock`. Hidden when both counts are zero. Clicking the
badge makes the dock visible and raises it to the front of its tab
group.

Designed to be the low-bandwidth peripheral that ParaView gets right:
the user doesn't need to keep the dock open — the badge tells them
when something's piling up.
"""
from __future__ import annotations

from typing import Any


_WARN_GLYPH  = "⚠"     # ⚠
_ERROR_GLYPH = "⛔"     # ⛔


class OutputBadge:
    """Wraps a ``QToolButton`` that tracks an :class:`OutputDock`'s counts.

    Not a ``QWidget`` subclass itself — composes one. The exposed
    :attr:`widget` is a ``QToolButton`` ready to be added to a status
    bar via ``status_bar.addPermanentWidget(badge.widget)``.

    Parameters
    ----------
    output_dock
        The :class:`OutputDock` whose ``.counts`` and ``on_append`` we
        subscribe to.
    dock_widget
        The enclosing ``QDockWidget`` that hosts the output dock.
        Used by the click handler to show + raise the dock.
    parent
        Optional Qt parent.
    """

    def __init__(
        self,
        output_dock: Any,
        dock_widget: Any,
        *,
        parent: Any = None,
    ) -> None:
        from qtpy import QtCore, QtWidgets

        button = QtWidgets.QToolButton(parent)
        button.setAutoRaise(True)
        # Qt enum location varies across bindings; the Qt.ToolButtonStyle
        # form works for both PyQt5/PySide2 and PyQt6/PySide6.
        button.setToolButtonStyle(
            QtCore.Qt.ToolButtonStyle.ToolButtonTextOnly,
        )
        button.setText("")
        button.setToolTip("Open the Output dock to see captured messages")
        button.setCursor(_pointing_cursor())
        button.clicked.connect(self._on_clicked)

        self._button = button
        self._output_dock = output_dock
        self._dock_widget = dock_widget

        # Subscribe to the dock's counts-changed channel so the badge
        # updates on both append AND clear (clear resets counts to
        # zero — without this hook the badge would stay stale until
        # the next append).
        output_dock.on_counts_changed(self._refresh)
        # Initial state — usually zero counts on construction, but
        # the dock may already have appends if the LogRouter fired
        # before the badge was wired.
        self._refresh()

    # ------------------------------------------------------------------
    # Public surface
    # ------------------------------------------------------------------

    @property
    def widget(self) -> Any:
        return self._button

    @property
    def is_visible(self) -> bool:
        return self._button.isVisible()

    @property
    def text(self) -> str:
        """The badge's current text — for tests / introspection."""
        return self._button.text()

    def refresh(self) -> None:
        """Force-refresh from the dock's current counts.

        Normally called automatically via the ``on_append`` hook;
        exposed for tests and for the case where the dock is cleared
        externally (it should call ``badge.refresh()`` to update).
        """
        self._refresh()

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _on_clicked(self) -> None:
        """Make the dock visible and raise it to the front of its tab group."""
        dw = self._dock_widget
        if dw is None:
            return
        try:
            dw.setVisible(True)
            dw.raise_()
        except Exception:
            pass

    def _refresh(self) -> None:
        counts = self._output_dock.counts
        warnings = counts.get("warning", 0)
        errors   = counts.get("error", 0)
        if warnings == 0 and errors == 0:
            self._button.setText("")
            self._button.hide()
            return
        parts: list[str] = []
        if errors > 0:
            # Errors first — more important.
            parts.append(f"{_ERROR_GLYPH} {errors}")
        if warnings > 0:
            parts.append(f"{_WARN_GLYPH} {warnings}")
        self._button.setText("  ".join(parts))
        self._button.show()


def _pointing_cursor() -> Any:
    """``Qt.CursorShape.PointingHandCursor`` — cue the badge is clickable."""
    from qtpy import QtCore, QtGui
    return QtGui.QCursor(QtCore.Qt.CursorShape.PointingHandCursor)
