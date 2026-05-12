"""
``_RecorderNS`` — backs ``ops.recorder.<Type>(...)``.

Phase 3B populates the three core recorder kinds:

  * :meth:`_RecorderNS.Node`    — :class:`apeGmsh.opensees.recorder.Node`
  * :meth:`_RecorderNS.Element` — :class:`apeGmsh.opensees.recorder.Element`
  * :meth:`_RecorderNS.MPCO`    — :class:`apeGmsh.opensees.recorder.MPCO`

Each method's signature mirrors the matching dataclass exactly and
constructs + registers a typed primitive on the bridge. No ``**kwargs``
at the user-facing surface (charter P12).
"""
from __future__ import annotations

from typing import Iterable

from ...._vocabulary import expand_many
from ...recorder import (
    MPCO,
    Element,
    Node,
    RecorderDeclaration,
    RecorderRecord,
)
from ._base import _BridgeNamespace


__all__ = ["_RecorderNS"]


class _RecorderNS(_BridgeNamespace):
    """``ops.recorder.<Type>(...)`` — typed methods for Phase 3B."""

    # -- Node -----------------------------------------------------------
    def Node(
        self,
        *,
        file: str,
        response: str,
        nodes: tuple[int, ...] | None = None,
        pg: str | None = None,
        dofs: tuple[int, ...],
        dT: float | None = None,
        time_format: str = "step",
    ) -> Node:
        """Construct + register a ``recorder Node``.

        Exactly one of ``nodes`` or ``pg`` must be supplied. See
        :class:`apeGmsh.opensees.recorder.Node` for the full parameter
        contract.
        """
        return self._bridge._register(
            Node(
                file=file,
                response=response,
                nodes=nodes,
                pg=pg,
                dofs=dofs,
                dT=dT,
                time_format=time_format,
            )
        )

    # -- Element --------------------------------------------------------
    def Element(
        self,
        *,
        file: str,
        response: tuple[str, ...],
        elements: tuple[int, ...] | None = None,
        pg: str | None = None,
        dT: float | None = None,
        time_format: str = "step",
    ) -> Element:
        """Construct + register a ``recorder Element``.

        Exactly one of ``elements`` or ``pg`` must be supplied. See
        :class:`apeGmsh.opensees.recorder.Element` for the full
        parameter contract.
        """
        return self._bridge._register(
            Element(
                file=file,
                response=response,
                elements=elements,
                pg=pg,
                dT=dT,
                time_format=time_format,
            )
        )

    # -- declare (Phase 9 unified) --------------------------------------
    def declare(
        self,
        *,
        nodes: Iterable[str] | str = (),
        pg: str | Iterable[str] | None = None,
        ids: Iterable[int] | None = None,
        dt: float | None = None,
        n_steps: int | None = None,
        name: str = "default",
        record_name: str | None = None,
    ) -> RecorderDeclaration:
        """Declare a unified recorder spec; register on the bridge.

        Phase 9 commit 3a: supports the ``nodes`` category only with
        ``pg=`` or ``ids=`` selectors. Other categories
        (elements / line_stations / gauss / fibers / layers / modal)
        raise :class:`NotImplementedError` from emit time — they
        will land in commits 3b and 5.

        Parameters
        ----------
        nodes
            Tuple of canonical component names or a single shorthand
            string. Shorthand expansion happens here using the
            bridge's ``ndm``/``ndf`` (set via ``ops.model(...)``);
            per Phase 9 D8 the user never repeats ``ndm``/``ndf``.
        pg
            Physical group name (or tuple of names) targeted by this
            declaration. Mutually exclusive with ``ids=``.
        ids
            Explicit node tags. Mutually exclusive with ``pg=``.
        dt, n_steps
            Recording cadence; at most one may be set. Both ``None``
            records every analysis step.
        name
            Identifier for this declaration; multiple named
            declarations can coexist on one bridge.
        record_name
            Optional per-record name for traceability (auto-generated
            when ``None``).

        Returns
        -------
        The registered :class:`RecorderDeclaration`.

        Raises
        ------
        RuntimeError
            If ``ops.model(ndm=, ndf=)`` has not been called yet
            (the bridge needs the dimensionality to expand shorthands).
        """
        ndm = self._bridge._ndm
        ndf = self._bridge._ndf
        if ndm is None or ndf is None:
            raise RuntimeError(
                "ops.recorder.declare: ops.model(ndm=, ndf=) must be "
                "called before declaring recorders (Phase 9 D8 binds "
                "ndm/ndf at declaration time)."
            )

        # Normalize selectors to tuples.
        if isinstance(pg, str):
            pg_tuple: tuple[str, ...] = (pg,)
        elif pg is None:
            pg_tuple = ()
        else:
            pg_tuple = tuple(pg)
        ids_tuple = tuple(int(i) for i in ids) if ids is not None else None

        records: list[RecorderRecord] = []

        # Nodes category.
        nodes_seq: tuple[str, ...]
        if isinstance(nodes, str):
            nodes_seq = (nodes,)
        else:
            nodes_seq = tuple(nodes)
        if nodes_seq:
            components = expand_many(nodes_seq, ndm=ndm, ndf=ndf)
            records.append(
                RecorderRecord(
                    category="nodes",
                    components=components,
                    pg=pg_tuple,
                    ids=ids_tuple,
                    dt=dt,
                    n_steps=n_steps,
                    name=record_name,
                )
            )

        decl = RecorderDeclaration(
            records=tuple(records),
            name=name,
            ndm=ndm,
            ndf=ndf,
        )
        return self._bridge._register(decl)

    # -- MPCO -----------------------------------------------------------
    def MPCO(
        self,
        *,
        file: str,
        nodal_responses: tuple[str, ...] = (),
        elem_responses: tuple[str, ...] = (),
        dT: float | None = None,
        nsteps: int | None = None,
    ) -> MPCO:
        """Construct + register a ``recorder mpco``.

        At least one of ``nodal_responses`` or ``elem_responses`` must
        be non-empty; supplying both ``dT`` and ``nsteps`` raises. See
        :class:`apeGmsh.opensees.recorder.MPCO` for the full parameter
        contract.
        """
        return self._bridge._register(
            MPCO(
                file=file,
                nodal_responses=nodal_responses,
                elem_responses=elem_responses,
                dT=dT,
                nsteps=nsteps,
            )
        )
