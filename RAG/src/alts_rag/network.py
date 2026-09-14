"""Refuse outbound service calls unless an approval record covers them."""

from __future__ import annotations

import socket
from typing import Any


class OutboundRefused(RuntimeError):
    """Raised when a test or adapter attempts a network call without approval."""


def refuse_outbound(*_args: Any, **_kwargs: Any) -> None:
    raise OutboundRefused("outbound service calls require Moses's approval")


def install_socket_guard() -> None:
    """Block new TCP connections from this process. Tests call this helper."""

    def blocked(*_args: Any, **_kwargs: Any) -> None:
        raise OutboundRefused("socket connections are disabled in this process")

    socket.socket.connect = blocked  # type: ignore[method-assign]
    socket.create_connection = blocked  # type: ignore[assignment]
