"""Where the request in flight ran: the VPS, or a Daytona sandbox.

A tiny module, modelled on :mod:`app.services.progress`'s ``ContextVar``
arrangement, and kept separate from it because "where it ran" is not progress
— it is a fact ``responses.py`` also needs, and ``offload.py`` already imports
``responses.py``, so importing back from there would be a cycle.

Set only by :func:`app.services.offload.maybe_offload`, and only in the
request task itself: ``mark_sandbox()`` once a shard has actually been
claimed, ``mark_server()`` as the honest revert on a fallback. Never from
inside a shard's own ``gather`` child — those run with a copied context, and a
write there would not propagate back to the request task that reads this.
"""

from __future__ import annotations

from contextvars import ContextVar

SERVER = "server"
SANDBOX = "sandbox"

_placement: ContextVar[str] = ContextVar("pdfkit_placement", default=SERVER)


def current() -> str:
    """Where the request in flight ran, or ``SERVER`` if nothing said otherwise."""
    return _placement.get()


def mark_sandbox() -> None:
    _placement.set(SANDBOX)


def mark_server() -> None:
    _placement.set(SERVER)
