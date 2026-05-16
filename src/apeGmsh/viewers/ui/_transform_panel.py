"""TransformPanel — Qt tab driving ``g.model.transforms`` from the viewer.

One operation combo + a stacked parameter form + Apply. All ops act
on the **current viewer selection**; ``sweep`` / ``thru_sections``
additionally capture curve sets (built into OCC wires by the viewer).
Pure UI — gathers params and fires ``on_apply``; ``model_viewer``
owns the library call + scene rebuild.

``on_apply(op, params, duplicate)``:
    op         translate|rotate|scale|mirror|copy|extrude|revolve|
               sweep|thru_sections
    params     dict of the form fields (angles in **degrees** — the
               viewer converts to radians; the library takes radians)
    duplicate  bool — for the in-place affine ops only: copy the
               selection first and transform the copies
"""
from __future__ import annotations

from typing import Any, Callable

_INPLACE = ("translate", "rotate", "scale", "mirror")
_OPS = (
    "translate", "rotate", "scale", "mirror", "copy",
    "extrude", "revolve", "sweep", "thru_sections",
)


def _qt():
    from qtpy import QtWidgets, QtCore
    return QtWidgets, QtCore


class TransformPanel:
    """Tab widget for the OCC transforms / generative ops."""

    def __init__(
        self,
        *,
        get_selection: Callable[[], list[tuple[int, int]]],
        on_apply: Callable[[str, dict, bool], None],
    ) -> None:
        QtWidgets, _ = _qt()
        self._get_selection = get_selection
        self._on_apply = on_apply
        self._fields: dict[str, dict[str, Any]] = {}
        self._path_curves: list[int] = []          # sweep
        self._sections: list[list[int]] = []       # thru_sections

        self.widget = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(self.widget)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(8)

        row = QtWidgets.QHBoxLayout()
        row.addWidget(QtWidgets.QLabel("Operation:"))
        self._combo = QtWidgets.QComboBox()
        self._combo.addItems([o.replace("_", " ") for o in _OPS])
        self._combo.currentIndexChanged.connect(self._on_op_changed)
        row.addWidget(self._combo, 1)
        lay.addLayout(row)

        self._stack = QtWidgets.QStackedWidget()
        for op in _OPS:
            self._stack.addWidget(self._build_form(op))
        lay.addWidget(self._stack)

        self._cb_dup = QtWidgets.QCheckBox("Keep original (copy first)")
        lay.addWidget(self._cb_dup)

        self._btn = QtWidgets.QPushButton("Apply")
        self._btn.clicked.connect(self._apply)
        lay.addWidget(self._btn)

        self._hint = QtWidgets.QLabel("")
        self._hint.setObjectName("DiagramSettingsEmptyHint")
        self._hint.setWordWrap(True)
        lay.addWidget(self._hint)
        lay.addStretch(1)
        self._on_op_changed(0)

    # ------------------------------------------------------------------
    # Form construction
    # ------------------------------------------------------------------

    def _dsb(self, default: float = 0.0) -> Any:
        QtWidgets, _ = _qt()
        s = QtWidgets.QDoubleSpinBox()
        s.setRange(-1.0e12, 1.0e12)
        s.setDecimals(4)
        s.setValue(default)
        return s

    def _spin(self, default: int = 0) -> Any:
        QtWidgets, _ = _qt()
        s = QtWidgets.QSpinBox()
        s.setRange(0, 1_000_000)
        s.setValue(default)
        return s

    def _form(self, op: str, specs: list[tuple[str, str, Any]]) -> Any:
        """specs: list of (key, label, widget). Stores widgets in
        ``self._fields[op]`` keyed by ``key``."""
        QtWidgets, _ = _qt()
        w = QtWidgets.QWidget()
        grid = QtWidgets.QGridLayout(w)
        grid.setContentsMargins(0, 0, 0, 0)
        store: dict[str, Any] = {}
        for i, (key, label, widget) in enumerate(specs):
            grid.addWidget(QtWidgets.QLabel(label), i, 0)
            grid.addWidget(widget, i, 1)
            store[key] = widget
        self._fields[op] = store
        return w

    def _build_form(self, op: str) -> Any:
        QtWidgets, _ = _qt()
        if op == "translate":
            return self._form(op, [
                ("dx", "dx", self._dsb()), ("dy", "dy", self._dsb()),
                ("dz", "dz", self._dsb()),
            ])
        if op == "rotate":
            return self._form(op, [
                ("angle", "angle (deg)", self._dsb()),
                ("ax", "axis x", self._dsb(0.0)),
                ("ay", "axis y", self._dsb(0.0)),
                ("az", "axis z", self._dsb(1.0)),
                ("cx", "centre x", self._dsb()),
                ("cy", "centre y", self._dsb()),
                ("cz", "centre z", self._dsb()),
            ])
        if op == "scale":
            return self._form(op, [
                ("sx", "sx", self._dsb(1.0)), ("sy", "sy", self._dsb(1.0)),
                ("sz", "sz", self._dsb(1.0)),
                ("cx", "centre x", self._dsb()),
                ("cy", "centre y", self._dsb()),
                ("cz", "centre z", self._dsb()),
            ])
        if op == "mirror":
            return self._form(op, [
                ("a", "plane a", self._dsb(1.0)),
                ("b", "plane b", self._dsb(0.0)),
                ("c", "plane c", self._dsb(0.0)),
                ("d", "plane d", self._dsb(0.0)),
            ])
        if op == "copy":
            w = QtWidgets.QLabel("Duplicates the current selection.")
            self._fields[op] = {}
            return w
        if op == "extrude":
            return self._form(op, [
                ("dx", "dx", self._dsb()), ("dy", "dy", self._dsb()),
                ("dz", "dz", self._dsb(1.0)),
                ("layers", "structured layers (0=off)", self._spin(0)),
                ("recombine", "recombine (hex/quad)",
                 QtWidgets.QCheckBox()),
            ])
        if op == "revolve":
            return self._form(op, [
                ("angle", "angle (deg)", self._dsb(90.0)),
                ("x", "axis pt x", self._dsb()),
                ("y", "axis pt y", self._dsb()),
                ("z", "axis pt z", self._dsb()),
                ("ax", "axis x", self._dsb(0.0)),
                ("ay", "axis y", self._dsb(0.0)),
                ("az", "axis z", self._dsb(1.0)),
                ("layers", "structured layers (0=off)", self._spin(0)),
                ("recombine", "recombine (hex/quad)",
                 QtWidgets.QCheckBox()),
            ])
        if op == "sweep":
            w = QtWidgets.QWidget()
            v = QtWidgets.QVBoxLayout(w)
            v.setContentsMargins(0, 0, 0, 0)
            v.addWidget(QtWidgets.QLabel(
                "Profiles = current selection.\nPath = a wire built "
                "from selected curves:"
            ))
            self._lbl_path = QtWidgets.QLabel("path: 0 curves")
            v.addWidget(self._lbl_path)
            hb = QtWidgets.QHBoxLayout()
            b1 = QtWidgets.QPushButton("Set path from selection")
            b1.clicked.connect(self._capture_path)
            b2 = QtWidgets.QPushButton("Clear")
            b2.clicked.connect(self._clear_path)
            hb.addWidget(b1, 1)
            hb.addWidget(b2)
            v.addLayout(hb)
            tr = QtWidgets.QHBoxLayout()
            tr.addWidget(QtWidgets.QLabel("Trihedron:"))
            self._combo_tri = QtWidgets.QComboBox()
            self._combo_tri.addItems([
                "DiscreteTrihedron", "CorrectedFrenet", "Fixed",
                "Frenet", "ConstantNormal", "Darboux",
            ])
            tr.addWidget(self._combo_tri, 1)
            v.addLayout(tr)
            self._fields[op] = {}
            return w
        if op == "thru_sections":
            w = QtWidgets.QWidget()
            v = QtWidgets.QVBoxLayout(w)
            v.setContentsMargins(0, 0, 0, 0)
            v.addWidget(QtWidgets.QLabel(
                "Each section = a wire from selected curves "
                "(≥ 2, in order):"
            ))
            self._list = QtWidgets.QListWidget()
            v.addWidget(self._list)
            hb = QtWidgets.QHBoxLayout()
            b1 = QtWidgets.QPushButton("Add section from selection")
            b1.clicked.connect(self._add_section)
            b2 = QtWidgets.QPushButton("Remove")
            b2.clicked.connect(self._remove_section)
            b3 = QtWidgets.QPushButton("Clear")
            b3.clicked.connect(self._clear_sections)
            for b in (b1, b2, b3):
                hb.addWidget(b)
            v.addLayout(hb)
            self._cb_solid = QtWidgets.QCheckBox("Make solid")
            self._cb_solid.setChecked(True)
            self._cb_ruled = QtWidgets.QCheckBox("Make ruled (linear)")
            v.addWidget(self._cb_solid)
            v.addWidget(self._cb_ruled)
            self._fields[op] = {}
            return w
        # Fallback (never hit — keeps the stack index aligned).
        self._fields[op] = {}
        return QtWidgets.QWidget()

    # ------------------------------------------------------------------
    # Curve-capture helpers (sweep / thru_sections)
    # ------------------------------------------------------------------

    def _selected_curves(self) -> list[int]:
        return [t for (d, t) in (self._get_selection() or []) if d == 1]

    def _capture_path(self) -> None:
        self._path_curves = self._selected_curves()
        self._lbl_path.setText(f"path: {len(self._path_curves)} curves")

    def _clear_path(self) -> None:
        self._path_curves = []
        self._lbl_path.setText("path: 0 curves")

    def _add_section(self) -> None:
        curves = self._selected_curves()
        if not curves:
            return
        self._sections.append(curves)
        self._list.addItem(
            f"section {len(self._sections)}: {len(curves)} curves"
        )

    def _remove_section(self) -> None:
        i = self._list.currentRow()
        if 0 <= i < len(self._sections):
            self._sections.pop(i)
            self._list.takeItem(i)

    def _clear_sections(self) -> None:
        self._sections = []
        self._list.clear()

    # ------------------------------------------------------------------
    # Apply
    # ------------------------------------------------------------------

    def _on_op_changed(self, idx: int) -> None:
        self._stack.setCurrentIndex(idx)
        op = _OPS[idx]
        self._cb_dup.setEnabled(op in _INPLACE)
        if op not in _INPLACE:
            self._cb_dup.setChecked(False)

    def set_hint(self, text: str) -> None:
        self._hint.setText(text)

    def reset_captures(self) -> None:
        """Drop captured sweep path / thru-section curves — OCC
        renumbers after the op so the old tags are stale."""
        self._clear_path()
        self._clear_sections()

    def _apply(self) -> None:
        op = _OPS[self._combo.currentIndex()]
        params: dict[str, Any] = {}
        for key, w in self._fields.get(op, {}).items():
            cls = type(w).__name__
            if cls == "QCheckBox":
                params[key] = w.isChecked()
            elif cls == "QSpinBox":
                params[key] = int(w.value())
            else:  # QDoubleSpinBox
                params[key] = float(w.value())
        if op == "sweep":
            params["path_curves"] = list(self._path_curves)
            params["trihedron"] = self._combo_tri.currentText()
        elif op == "thru_sections":
            params["sections"] = [list(s) for s in self._sections]
            params["make_solid"] = self._cb_solid.isChecked()
            params["make_ruled"] = self._cb_ruled.isChecked()
        self._on_apply(op, params, self._cb_dup.isChecked())
