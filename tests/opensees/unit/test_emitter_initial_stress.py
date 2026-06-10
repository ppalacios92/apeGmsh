"""Unit tests for the Phase SSI-1 stress-control emitter methods.

The Protocol gained two methods, ``addToParameter`` and
``step_hook_ramp``, plus a behavior change to ``analyze`` that wraps
the analyze loop with per-step hook dispatcher calls once any ramp
has been registered.

These tests verify:

1. Protocol contract — both methods exist with the right signatures.
2. RecordingEmitter mirrors the Protocol.
3. TclEmitter — addToParameter line shape; step_hook_ramp emits the
   dispatcher boilerplate exactly once, then parameter declarations +
   proc body + lappend; analyze wraps when hooks are registered.
4. PyEmitter — same shape, Python syntax.
5. Linear-ramp math: factor formula and updateParameter delta are
   computed correctly for a representative ramp.
"""
from __future__ import annotations

import inspect
from typing import get_type_hints

from apeGmsh.opensees.emitter.base import Emitter
from apeGmsh.opensees.emitter.py import PyEmitter
from apeGmsh.opensees.emitter.recording import RecordingEmitter
from apeGmsh.opensees.emitter.tcl import TclEmitter


# ---------------------------------------------------------------------------
# 1. Protocol contract
# ---------------------------------------------------------------------------


def test_emitter_protocol_has_add_to_parameter() -> None:
    assert hasattr(Emitter, "addToParameter")
    hints = get_type_hints(Emitter.addToParameter)
    assert hints.get("tag") is int
    assert hints.get("ele_tag") is int
    assert hints.get("response") is str
    assert hints.get("return") is type(None)
    sig = inspect.signature(Emitter.addToParameter)
    assert [p.name for p in sig.parameters.values()] == [
        "self", "tag", "ele_tag", "response",
    ]


def test_emitter_protocol_has_step_hook_ramp() -> None:
    assert hasattr(Emitter, "step_hook_ramp")
    sig = inspect.signature(Emitter.step_hook_ramp)
    params = list(sig.parameters.values())
    # Positional: self, name. Then kw-only: targets, n_steps_to_full, phase.
    assert params[0].name == "self"
    assert params[1].name == "name"
    assert params[1].kind == inspect.Parameter.POSITIONAL_OR_KEYWORD
    by_name = {p.name: p for p in params}
    assert by_name["targets"].kind == inspect.Parameter.KEYWORD_ONLY
    assert by_name["n_steps_to_full"].kind == inspect.Parameter.KEYWORD_ONLY
    assert by_name["phase"].kind == inspect.Parameter.KEYWORD_ONLY
    # ``phase`` has a default of "before".
    assert by_name["phase"].default == "before"


# ---------------------------------------------------------------------------
# 2. RecordingEmitter
# ---------------------------------------------------------------------------


def test_recording_emitter_captures_add_to_parameter() -> None:
    e = RecordingEmitter()
    e.addToParameter(1, 42, "commitStressIncrementXX")
    assert e.calls == [
        ("addToParameter", (1, 42, "commitStressIncrementXX"), {}),
    ]


def test_recording_emitter_captures_step_hook_ramp() -> None:
    e = RecordingEmitter()
    e.step_hook_ramp(
        "ramp_a",
        targets=((1, -6300.0), (2, -6300.0), (3, -6300.0)),
        n_steps_to_full=10.0,
        phase="before",
    )
    assert e.calls == [
        (
            "step_hook_ramp",
            ("ramp_a",),
            {
                "targets": ((1, -6300.0), (2, -6300.0), (3, -6300.0)),
                "n_steps_to_full": 10.0,
                "phase": "before",
            },
        ),
    ]


# ---------------------------------------------------------------------------
# 3. TclEmitter
# ---------------------------------------------------------------------------


def test_tcl_add_to_parameter_line_shape() -> None:
    e = TclEmitter()
    e.addToParameter(1, 42, "commitStressIncrementXX")
    last = e.lines()[-1]
    assert last == "addToParameter 1 element 42 commitStressIncrementXX"


def test_tcl_step_hook_ramp_emits_dispatcher_once() -> None:
    """The dispatcher boilerplate (set _apesees_before_step_hooks {} +
    proc _apesees_call_before_step + proc _apesees_call_after_step)
    must emit exactly once across the emitter's lifetime."""
    e = TclEmitter()
    e.step_hook_ramp(
        "ramp_a",
        targets=((1, -6300.0),),
        n_steps_to_full=10.0,
        phase="before",
    )
    e.step_hook_ramp(
        "ramp_b",
        targets=((2, -4200.0),),
        n_steps_to_full=20.0,
        phase="before",
    )
    text = "\n".join(e.lines())
    # Dispatcher header is the comment line — count occurrences.
    assert text.count(
        "# apeSees per-step hook dispatcher (Phase SSI-1)"
    ) == 1
    # Both proc bodies are present.
    assert "proc ramp_a {}" in text
    assert "proc ramp_b {}" in text
    # Both lappends are present.
    assert "lappend _apesees_before_step_hooks ramp_a" in text
    assert "lappend _apesees_before_step_hooks ramp_b" in text


def test_tcl_step_hook_ramp_emits_parameter_declarations() -> None:
    e = TclEmitter()
    e.step_hook_ramp(
        "ramp_a",
        targets=((1, -6300.0), (2, -6300.0), (3, -6300.0)),
        n_steps_to_full=10.0,
        phase="before",
    )
    text = "\n".join(e.lines())
    assert "parameter 1" in text
    assert "parameter 2" in text
    assert "parameter 3" in text


def test_tcl_step_hook_ramp_proc_body_shape() -> None:
    """The proc body must:
    - Initialize state on first call.
    - Advance the count, compute capped factor.
    - Emit one updateParameter per target with the delta against the
      previous cumulative.
    """
    e = TclEmitter()
    e.step_hook_ramp(
        "myramp",
        targets=((7, -1000.0), (8, -2000.0)),
        n_steps_to_full=10.0,
        phase="before",
    )
    text = "\n".join(e.lines())
    # First-call initialization.
    assert "if {![info exists myramp_state(count)]}" in text
    assert "set myramp_state(count) 0" in text
    assert "set myramp_state(cum_7) 0.0" in text
    assert "set myramp_state(cum_8) 0.0" in text
    # Counter advance + factor.
    assert (
        "set myramp_state(count) [expr {$myramp_state(count) + 1}]"
        in text
    )
    assert "set _factor [expr {$myramp_state(count) / 10.0}]" in text
    assert "if {$_factor > 1.0} { set _factor 1.0 }" in text
    # Per-target updateParameter lines.
    assert "set _cur [expr {-1000.0 * $_factor}]" in text
    assert "set _delta [expr {$_cur - $myramp_state(cum_7)}]" in text
    assert "updateParameter 7 $_delta" in text
    assert "set myramp_state(cum_7) $_cur" in text
    assert "set _cur [expr {-2000.0 * $_factor}]" in text
    assert "updateParameter 8 $_delta" in text


def test_tcl_analyze_unwrapped_when_no_hooks() -> None:
    # No hooks → still a fail-loud per-increment loop (no dispatcher
    # calls), never a bare ``analyze 10`` (which short-circuits on the
    # first failed increment and lets the deck silently run on).
    e = TclEmitter()
    n_before = len(e.lines())
    e.analyze(steps=10)
    new_lines = e.lines()[n_before:]
    text = "\n".join(new_lines)
    assert "analyze 10" not in text
    assert "for {set _apesees_i 0} {$_apesees_i < 10}" in text
    assert "if {[analyze 1] != 0} {" in text.replace("    ", "")
    assert "_apesees_call_before_step" not in text
    assert "_apesees_call_after_step" not in text


def test_tcl_analyze_wraps_when_hooks_registered() -> None:
    """Once step_hook_ramp has run, analyze emits a for-loop with
    dispatcher calls instead of a bare ``analyze N`` line."""
    e = TclEmitter()
    e.step_hook_ramp(
        "ramp_a",
        targets=((1, -6300.0),),
        n_steps_to_full=10.0,
        phase="before",
    )
    n_before_analyze = len(e.lines())
    e.analyze(steps=10, dt=0.1)
    new_lines = e.lines()[n_before_analyze:]
    text = "\n".join(new_lines)
    # for-loop header and closing brace.
    assert any(
        "for {set _apesees_i 0} {$_apesees_i < 10}" in line
        for line in new_lines
    )
    assert new_lines[-1] == "}"
    # Dispatcher calls bracketing analyze 1.
    assert "_apesees_call_before_step" in text
    assert "analyze 1 0.1" in text
    assert "_apesees_call_after_step" in text


def test_tcl_analyze_wraps_without_dt() -> None:
    e = TclEmitter()
    e.step_hook_ramp(
        "r",
        targets=((1, -100.0),),
        n_steps_to_full=5.0,
        phase="before",
    )
    n_before = len(e.lines())
    e.analyze(steps=5)
    new_lines = e.lines()[n_before:]
    text = "\n".join(new_lines)
    # No dt → "[analyze 1]" (rc-checked) inside the loop.
    assert "analyze 1" in text
    # Sanity: make sure the analyze call has no trailing dt.
    inner_lines = [ln for ln in new_lines if "analyze 1" in ln]
    assert any(ln.strip() == "if {[analyze 1] != 0} {" for ln in inner_lines)


def test_tcl_after_phase_uses_correct_list() -> None:
    e = TclEmitter()
    e.step_hook_ramp(
        "after_ramp",
        targets=((1, -100.0),),
        n_steps_to_full=5.0,
        phase="after",
    )
    text = "\n".join(e.lines())
    assert "lappend _apesees_after_step_hooks after_ramp" in text
    assert "lappend _apesees_before_step_hooks after_ramp" not in text


# ---------------------------------------------------------------------------
# 4. PyEmitter
# ---------------------------------------------------------------------------


def test_py_add_to_parameter_line_shape() -> None:
    e = PyEmitter()
    e.addToParameter(1, 42, "commitStressIncrementXX")
    last = e.lines()[-1]
    assert last == (
        "ops.addToParameter(1, 'element', 42, 'commitStressIncrementXX')"
    )


def test_py_step_hook_ramp_dispatcher_idempotent() -> None:
    e = PyEmitter()
    e.step_hook_ramp(
        "ramp_a",
        targets=((1, -6300.0),),
        n_steps_to_full=10.0,
        phase="before",
    )
    e.step_hook_ramp(
        "ramp_b",
        targets=((2, -4200.0),),
        n_steps_to_full=20.0,
        phase="before",
    )
    text = "\n".join(e.lines())
    assert text.count("# apeSees per-step hook dispatcher (Phase SSI-1)") == 1
    assert "_apesees_before_step_hooks: list = []" in text
    assert "def ramp_a()" in text
    assert "def ramp_b()" in text
    assert "_apesees_before_step_hooks.append(ramp_a)" in text
    assert "_apesees_before_step_hooks.append(ramp_b)" in text


def test_py_step_hook_ramp_function_body_shape() -> None:
    e = PyEmitter()
    e.step_hook_ramp(
        "myramp",
        targets=((7, -1000.0),),
        n_steps_to_full=10.0,
        phase="before",
    )
    text = "\n".join(e.lines())
    # State dict at module level.
    assert "myramp_state: dict = {'count': 0, 'cum_7': 0.0}" in text
    # Function body lines.
    assert "myramp_state['count'] += 1" in text
    assert "_factor = min(myramp_state['count'] / 10.0, 1.0)" in text
    assert "_cur = -1000.0 * _factor" in text
    assert "_delta = _cur - myramp_state['cum_7']" in text
    assert "ops.updateParameter(7, _delta)" in text


def test_py_analyze_unwrapped_when_no_hooks() -> None:
    # No hooks → still a fail-loud per-increment loop (no dispatcher
    # calls), never a bare ``ops.analyze(10)`` (which short-circuits on
    # the first failed increment and lets the deck silently run on).
    e = PyEmitter()
    n_before = len(e.lines())
    e.analyze(steps=10)
    text = "\n".join(e.lines()[n_before:])
    assert "ops.analyze(10)" not in text
    assert "for _apesees_i in range(10):" in text
    assert "if ops.analyze(1) != 0:" in text
    assert "_apesees_call_before_step()" not in text
    assert "_apesees_call_after_step()" not in text


def test_py_analyze_wraps_when_hooks_registered() -> None:
    e = PyEmitter()
    e.step_hook_ramp(
        "r",
        targets=((1, -6300.0),),
        n_steps_to_full=10.0,
        phase="before",
    )
    n_before = len(e.lines())
    e.analyze(steps=10, dt=0.1)
    new_lines = e.lines()[n_before:]
    text = "\n".join(new_lines)
    assert "for _apesees_i in range(10):" in text
    assert "_apesees_call_before_step()" in text
    assert "ops.analyze(1, 0.1)" in text
    assert "_apesees_call_after_step()" in text


# ---------------------------------------------------------------------------
# 5. Linear-ramp math sanity (executed proc semantics)
# ---------------------------------------------------------------------------
#
# The Tcl + Py emit produce a textual proc that, when run, must:
# - factor(k) = min(k / n_steps_to_full, 1.0) for the k-th call
# - cumulative(k) = target * factor(k)
# - delta(k) = cumulative(k) - cumulative(k-1)
#
# We exercise the EQUIVALENT Python algorithm here (without invoking
# the textual emit) so the formula is locked in.  The Tcl / py text
# emit are read-only renderings of this same algorithm; if they drift
# from this reference, the Tcl/py tests above will catch the textual
# divergence.


def _simulate_ramp(target: float, n_steps_to_full: float, steps: int) -> list[float]:
    """Run the ramp algorithm in Python and return the cumulative
    value after each step.  Mirrors what the emitted proc will do."""
    cumulative = 0.0
    out: list[float] = []
    for k in range(1, steps + 1):
        factor = min(k / n_steps_to_full, 1.0)
        current = target * factor
        # The proc uses delta = current - cumulative; updateParameter
        # adds delta to the running OpenSees parameter, equivalent to
        # setting it to current cumulatively.
        cumulative = current
        out.append(cumulative)
    return out


def test_ramp_reaches_target_at_n_steps() -> None:
    out = _simulate_ramp(target=-6300.0, n_steps_to_full=10.0, steps=10)
    assert out[-1] == -6300.0


def test_ramp_plateaus_after_full() -> None:
    """Once factor caps at 1.0, subsequent steps produce delta=0."""
    out = _simulate_ramp(target=-6300.0, n_steps_to_full=10.0, steps=15)
    assert out[9] == -6300.0
    assert out[10] == -6300.0
    assert out[14] == -6300.0


def test_ramp_lambda_install_scales_target() -> None:
    """lambda_install is baked into the target before passing to the
    ramp — at full ramp, cumulative = sigma * lambda_install."""
    sigma = -6300.0
    lambda_install = 0.5
    scaled_target = sigma * lambda_install
    out = _simulate_ramp(target=scaled_target, n_steps_to_full=10.0, steps=10)
    assert out[-1] == -3150.0
