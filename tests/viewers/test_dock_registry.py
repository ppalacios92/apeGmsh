"""Unit tests for :class:`DockSpec` / :class:`DockRegistry`.

Tests split into two groups:

* No-Qt — validates the pure-Python parts (DockSpec construction,
  registry register/dedup/forward-ref checks). Run without Qt.
* With Qt — validates :meth:`DockRegistry.mount` actually wires
  QDockWidgets onto a QMainWindow with the right objectNames,
  tabification, and visibility.
"""
from __future__ import annotations

import pytest

from apeGmsh.viewers.ui._dock_registry import DockRegistry, DockSpec


# =====================================================================
# DockSpec validation (no Qt)
# =====================================================================


def test_dockspec_basic_construction():
    spec = DockSpec(
        dock_id="outline",
        title="Outline",
        factory=lambda parent: object(),
    )
    assert spec.dock_id == "outline"
    assert spec.title == "Outline"
    assert spec.default_area == "right"
    assert spec.default_visible is True
    assert spec.default_floating is False
    assert spec.tabify_with is None


def test_dockspec_rejects_empty_id():
    with pytest.raises(ValueError, match="non-empty"):
        DockSpec(dock_id="", title="x", factory=lambda p: None)


def test_dockspec_rejects_invalid_chars_in_id():
    # Spaces, slashes, etc. would corrupt QSettings paths.
    with pytest.raises(ValueError, match="alphanumeric"):
        DockSpec(dock_id="bad id", title="x", factory=lambda p: None)
    with pytest.raises(ValueError, match="alphanumeric"):
        DockSpec(dock_id="bad/id", title="x", factory=lambda p: None)


def test_dockspec_accepts_separators_in_id():
    # Underscores, hyphens, dots all OK.
    for ok_id in ("foo_bar", "foo-bar", "foo.bar", "foo123"):
        spec = DockSpec(dock_id=ok_id, title="x", factory=lambda p: None)
        assert spec.dock_id == ok_id


def test_dockspec_rejects_invalid_area():
    with pytest.raises(ValueError, match="default_area"):
        DockSpec(
            dock_id="x", title="x", factory=lambda p: None,
            default_area="middle",
        )


# =====================================================================
# DockRegistry register / dedup / forward-ref (no Qt)
# =====================================================================


def _spec(dock_id: str, tabify_with=None) -> DockSpec:
    return DockSpec(
        dock_id=dock_id,
        title=dock_id.title(),
        factory=lambda p: None,
        tabify_with=tabify_with,
    )


def test_registry_register_and_query():
    reg = DockRegistry()
    assert len(reg) == 0
    reg.register(_spec("outline"))
    assert len(reg) == 1
    assert "outline" in reg
    assert "missing" not in reg


def test_registry_rejects_duplicate_id():
    reg = DockRegistry()
    reg.register(_spec("outline"))
    with pytest.raises(ValueError, match="Duplicate"):
        reg.register(_spec("outline"))


def test_registry_rejects_forward_tabify_ref():
    """tabify_with must reference an already-registered dock."""
    reg = DockRegistry()
    with pytest.raises(ValueError, match="unregistered"):
        reg.register(_spec("diagrams", tabify_with="outline"))


def test_registry_accepts_backward_tabify_ref():
    reg = DockRegistry()
    reg.register(_spec("outline"))
    reg.register(_spec("diagrams", tabify_with="outline"))
    assert len(reg) == 2


def test_registry_specs_returns_in_order():
    reg = DockRegistry()
    reg.register(_spec("a"))
    reg.register(_spec("b"))
    reg.register(_spec("c"))
    assert [s.dock_id for s in reg.specs()] == ["a", "b", "c"]


# =====================================================================
# DockRegistry.mount — requires Qt
# =====================================================================


@pytest.fixture(scope="module")
def qapp():
    QtWidgets = pytest.importorskip("qtpy.QtWidgets")
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    yield app


def _make_window(qapp):
    from qtpy import QtWidgets
    win = QtWidgets.QMainWindow()
    # Central widget needed or QMainWindow warns when adding docks.
    win.setCentralWidget(QtWidgets.QWidget(win))
    return win


def test_mount_creates_docks_with_objectnames(qapp):
    from qtpy import QtWidgets

    reg = DockRegistry()
    reg.register(DockSpec(
        dock_id="outline",
        title="Outline",
        factory=lambda parent: QtWidgets.QWidget(parent),
    ))
    reg.register(DockSpec(
        dock_id="diagrams",
        title="Diagrams",
        factory=lambda parent: QtWidgets.QWidget(parent),
    ))

    win = _make_window(qapp)
    docks = reg.mount(win)

    assert set(docks.keys()) == {"outline", "diagrams"}
    assert docks["outline"].objectName() == "outline"
    assert docks["diagrams"].objectName() == "diagrams"
    # Window owns them — they appear as children.
    assert docks["outline"].parent() is win


def test_mount_applies_default_area(qapp):
    from qtpy import QtCore, QtWidgets

    reg = DockRegistry()
    reg.register(DockSpec(
        dock_id="left_dock",
        title="Left",
        factory=lambda p: QtWidgets.QWidget(p),
        default_area="left",
    ))
    reg.register(DockSpec(
        dock_id="bottom_dock",
        title="Bottom",
        factory=lambda p: QtWidgets.QWidget(p),
        default_area="bottom",
    ))

    win = _make_window(qapp)
    docks = reg.mount(win)

    assert win.dockWidgetArea(docks["left_dock"]) == \
        QtCore.Qt.DockWidgetArea.LeftDockWidgetArea
    assert win.dockWidgetArea(docks["bottom_dock"]) == \
        QtCore.Qt.DockWidgetArea.BottomDockWidgetArea


def test_mount_applies_visibility(qapp):
    from qtpy import QtWidgets

    reg = DockRegistry()
    reg.register(DockSpec(
        dock_id="hidden",
        title="Hidden",
        factory=lambda p: QtWidgets.QWidget(p),
        default_visible=False,
    ))
    reg.register(DockSpec(
        dock_id="visible",
        title="Visible",
        factory=lambda p: QtWidgets.QWidget(p),
        default_visible=True,
    ))

    win = _make_window(qapp)
    win.show()              # docks only become visible when window is shown
    docks = reg.mount(win)

    assert not docks["hidden"].isVisible()
    assert docks["visible"].isVisible()
    win.close()


def test_mount_tabifies_with_referenced_dock(qapp):
    from qtpy import QtWidgets

    reg = DockRegistry()
    reg.register(DockSpec(
        dock_id="outline",
        title="Outline",
        factory=lambda p: QtWidgets.QWidget(p),
    ))
    reg.register(DockSpec(
        dock_id="diagrams",
        title="Diagrams",
        factory=lambda p: QtWidgets.QWidget(p),
        tabify_with="outline",
    ))

    win = _make_window(qapp)
    docks = reg.mount(win)

    # Both should be tabified together. Qt exposes this via
    # tabifiedDockWidgets(); each appears in the other's tabbed group.
    outline_tabs = win.tabifiedDockWidgets(docks["outline"])
    assert docks["diagrams"] in outline_tabs


def test_mount_calls_factory_in_registration_order(qapp):
    from qtpy import QtWidgets

    calls: list[str] = []

    def factory_for(name):
        def factory(parent):
            calls.append(name)
            return QtWidgets.QWidget(parent)
        return factory

    reg = DockRegistry()
    reg.register(DockSpec("a", "A", factory_for("a")))
    reg.register(DockSpec("b", "B", factory_for("b")))
    reg.register(DockSpec("c", "C", factory_for("c")))

    win = _make_window(qapp)
    reg.mount(win)
    assert calls == ["a", "b", "c"]


# =====================================================================
# sanitize_dock_placement — idempotent per-launch heal for a degenerate
# nav-dock placement (the recurring "stuck on the upper edge" bug).
# Requires Qt.
# =====================================================================

# Floors mirroring LAYOUT.outline_* so the assertions are self-contained.
_MINW, _INITW, _MINH, _INITH = 180, 260, 120, 400


def _new_dock(win, object_name="dock_mesh_outline"):
    from qtpy import QtWidgets
    d = QtWidgets.QDockWidget("Outline", win)
    d.setObjectName(object_name)
    d.setWidget(QtWidgets.QWidget(win))
    return d


def _sanitize(win, dock):
    from apeGmsh.viewers.ui._dock_registry import sanitize_dock_placement
    sanitize_dock_placement(
        win, dock,
        min_width=_MINW, initial_width=_INITW,
        min_height=_MINH, initial_height=_INITH,
    )


def test_sanitize_heals_top_to_left(qapp):
    from qtpy import QtCore
    win = _make_window(qapp)
    dock = _new_dock(win)
    win.addDockWidget(QtCore.Qt.TopDockWidgetArea, dock)
    _sanitize(win, dock)
    assert win.dockWidgetArea(dock) == QtCore.Qt.LeftDockWidgetArea
    assert dock.isFloating() is False


def test_sanitize_heals_bottom_to_left(qapp):
    from qtpy import QtCore
    win = _make_window(qapp)
    dock = _new_dock(win)
    win.addDockWidget(QtCore.Qt.BottomDockWidgetArea, dock)
    _sanitize(win, dock)
    assert win.dockWidgetArea(dock) == QtCore.Qt.LeftDockWidgetArea


def test_sanitize_unfloats_to_left(qapp):
    """The original 50884941 floating symptom."""
    from qtpy import QtCore
    win = _make_window(qapp)
    dock = _new_dock(win)
    win.addDockWidget(QtCore.Qt.LeftDockWidgetArea, dock)
    dock.setFloating(True)
    assert dock.isFloating() is True
    _sanitize(win, dock)
    assert dock.isFloating() is False
    assert win.dockWidgetArea(dock) == QtCore.Qt.LeftDockWidgetArea


def test_sanitize_reasserts_features(qapp):
    """A corrupt state that stripped the drag handles is re-armed."""
    from qtpy import QtCore, QtWidgets
    win = _make_window(qapp)
    dock = _new_dock(win)
    win.addDockWidget(QtCore.Qt.LeftDockWidgetArea, dock)
    dock.setFeatures(QtWidgets.QDockWidget.NoDockWidgetFeatures)
    _sanitize(win, dock)
    feats = dock.features()
    assert bool(feats & QtWidgets.QDockWidget.DockWidgetMovable)
    assert bool(feats & QtWidgets.QDockWidget.DockWidgetFloatable)


def test_sanitize_sets_both_floors(qapp):
    from qtpy import QtCore
    win = _make_window(qapp)
    dock = _new_dock(win)
    win.addDockWidget(QtCore.Qt.LeftDockWidgetArea, dock)
    _sanitize(win, dock)
    assert dock.minimumWidth() == _MINW
    assert dock.minimumHeight() == _MINH


def test_sanitize_heals_collapsed_height_to_min(qapp):
    """THE recurring bug: a Left, non-floating, full-width dock crushed
    vertically to a title-bar sliver. The sticky height floor reclaims
    space from the sibling WITHOUT tearing the dock out of its split."""
    from qtpy import QtCore, QtWidgets
    win = _make_window(qapp)
    win.resize(1200, 800)
    top = _new_dock(win, "dock_mesh_outline")
    bottom = QtWidgets.QDockWidget("Sib", win)
    bottom.setObjectName("dock_sibling")
    bottom.setWidget(QtWidgets.QWidget(win))
    win.addDockWidget(QtCore.Qt.LeftDockWidgetArea, top)
    win.addDockWidget(QtCore.Qt.LeftDockWidgetArea, bottom)
    win.splitDockWidget(top, bottom, QtCore.Qt.Vertical)
    win.show()
    qapp.processEvents()
    # Crush the bottom dock to a sliver.
    win.resizeDocks([top, bottom], [760, 30], QtCore.Qt.Vertical)
    qapp.processEvents()
    assert bottom.height() < _MINH  # genuinely crushed
    _sanitize(win, bottom)
    qapp.processEvents()
    assert bottom.height() >= _MINH          # reclaimed by the floor
    assert win.dockWidgetArea(bottom) == QtCore.Qt.LeftDockWidgetArea
    assert bottom.isFloating() is False      # NOT torn out of the split
    win.close()


def test_sanitize_preserves_healthy_left(qapp):
    """A healthy Left dock keeps its area; the sanitizer must not fire
    the re-dock branch."""
    from qtpy import QtCore
    win = _make_window(qapp)
    dock = _new_dock(win)
    win.addDockWidget(QtCore.Qt.LeftDockWidgetArea, dock)
    _sanitize(win, dock)
    assert win.dockWidgetArea(dock) == QtCore.Qt.LeftDockWidgetArea
    assert dock.isFloating() is False


def test_sanitize_preserves_healthy_right(qapp):
    """A user who docks the nav panel on the RIGHT keeps it there —
    Right is a legitimate vertical-tree area, only Top/Bottom/floating
    are degenerate."""
    from qtpy import QtCore
    win = _make_window(qapp)
    dock = _new_dock(win)
    win.addDockWidget(QtCore.Qt.RightDockWidgetArea, dock)
    _sanitize(win, dock)
    assert win.dockWidgetArea(dock) == QtCore.Qt.RightDockWidgetArea


def test_sanitize_preserves_user_width_on_healthy_left(qapp):
    """Plan-08 persistence: a healthy Left dock the user widened is NOT
    reset to the initial width (the re-dock/resize branch never fires)."""
    from qtpy import QtCore
    win = _make_window(qapp)
    win.resize(1200, 800)
    dock = _new_dock(win)
    win.addDockWidget(QtCore.Qt.LeftDockWidgetArea, dock)
    win.show()
    qapp.processEvents()
    win.resizeDocks([dock], [420], QtCore.Qt.Horizontal)
    qapp.processEvents()
    widened = dock.width()
    assert widened > _INITW
    _sanitize(win, dock)
    qapp.processEvents()
    # Width preserved (floor only clamps UP, and the dock is above it).
    assert dock.width() >= _INITW
    assert dock.width() == widened
    win.close()
