"""Black-box finite-difference sensitivity for apeGmsh.

Compute how a response changes with any model parameter — every damping channel
included — by perturbing the parameter and re-running the analysis on top of the
``apeSees`` bridge. No solver edits, no analytic derivative. See
``internal_docs/guide_sensitivity.md``.

```python
from apeGmsh.sensitivity import Sensitivity, Param, Response

def build(ops, params):
    ops.model(ndm=3, ndf=3)
    ...                                  # materials / elements / fix / mass
    ops.damping.rayleigh(ratio=params["xi"], f_i=2.0, f_j=12.0)
    ...                                  # excitation

sens = Sensitivity.from_apesees(
    fem, build=build,
    params=[Param(name="xi", value=0.05)],
    response=Response(pg="Roof", component="displacement_x", reduce="peak"),
    steps=6000, dt=0.002,
)
grad = sens.gradient()                   # {"xi": d(peak drift)/d(xi)}
sens.step_study("xi")                    # plateau check (always do this)
```
"""
from __future__ import annotations

from ._fd import FDSensitivity
from .driver import Sensitivity, default_apesees_runner
from .spec import Param, Response, reduce_response

__all__ = [
    "Sensitivity",
    "Param",
    "Response",
    "FDSensitivity",
    "reduce_response",
    "default_apesees_runner",
]
