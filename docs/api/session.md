# Session — `apeGmsh`

The top-level session object. Owns a single Gmsh kernel and wires
all composites (`model`, `mesh`, `parts`, `constraints`, `loads`,
`masses`, …). The OpenSees bridge is **not** a session composite —
import it explicitly via `from apeGmsh.opensees import apeSees`.

## Package

::: apeGmsh

## Session class

::: apeGmsh._core.apeGmsh

## Base

::: apeGmsh._session._SessionBase
