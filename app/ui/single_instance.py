"""Refuse to open a second window over the same data files.

Two windows sharing one data directory can overwrite each other's history and
settings, which loses records of paid generations. The first process keeps a
named local socket; a second one asks that window to come forward and exits.

The Qt calls sit behind three module-level functions so the tests can exercise
the logic with plain fakes and without importing PySide6 at all.
"""

from __future__ import annotations

import getpass
import hashlib
from collections.abc import Callable
from pathlib import Path

RAISE_COMMAND = b"raise"

Listener = Callable[[str, Callable[[], None]], object | None]


def server_name(data_dir: Path, app_id: str = "image-generation-studio") -> str:
    """Build a server name that is unique per user and per data directory."""
    try:
        user = getpass.getuser()
    except Exception:  # pragma: no cover - depends on the OS account setup
        user = "user"
    resolved = str(Path(data_dir).resolve()).lower()
    digest = hashlib.sha256(resolved.encode("utf-8")).hexdigest()[:10]
    return f"{app_id}-{user}-{digest}"


def _qt_probe(name: str) -> bool:
    """Report whether another process is already listening on ``name``."""
    from PySide6.QtNetwork import QLocalSocket

    socket = QLocalSocket()
    try:
        socket.connectToServer(name)
        return bool(socket.waitForConnected(300))
    finally:
        socket.abort()
        socket.close()


def _qt_notify(name: str) -> None:
    """Ask the running instance to bring its window forward."""
    from PySide6.QtNetwork import QLocalSocket

    socket = QLocalSocket()
    try:
        socket.connectToServer(name)
        if socket.waitForConnected(300):
            socket.write(RAISE_COMMAND)
            socket.flush()
            socket.waitForBytesWritten(300)
    finally:
        socket.abort()
        socket.close()


def _qt_listen(name: str, on_activate: Callable[[], None]) -> object | None:
    """Own ``name`` and call ``on_activate`` when another instance asks for us."""
    from PySide6.QtNetwork import QLocalServer

    # A socket left behind by a crashed process would block us forever.
    QLocalServer.removeServer(name)
    server = QLocalServer()
    server.setSocketOptions(QLocalServer.UserAccessOption)
    if not server.listen(name):
        return None

    def serve() -> None:
        connection = server.nextPendingConnection()
        if connection is None:
            return
        connection.readyRead.connect(lambda: _consume(connection, on_activate))
        connection.disconnected.connect(connection.deleteLater)

    server.newConnection.connect(serve)
    return server


def _consume(connection: object, on_activate: Callable[[], None]) -> None:
    data = connection.readAll().data()
    if RAISE_COMMAND in data:
        on_activate()


class SingleInstanceGuard:
    """Decide whether this process may open the window.

    ``acquire`` returns ``True`` for the first instance and ``False`` for every
    later one. It never blocks the application from starting: if the name
    cannot be claimed, the guard reports success and lets the window open,
    because a working window is better than a refusal.
    """

    def __init__(
        self,
        name: str,
        *,
        probe: Callable[[str], bool] | None = None,
        notify: Callable[[str], None] | None = None,
        listen: Listener | None = None,
    ) -> None:
        self._name = name
        self._probe = probe or _qt_probe
        self._notify = notify or _qt_notify
        self._listen = listen or _qt_listen
        self._server: object | None = None
        self._callback: Callable[[], None] | None = None

    @property
    def is_primary(self) -> bool:
        """Whether this process claimed the name."""
        return self._server is not None

    def set_activation_callback(self, callback: Callable[[], None]) -> None:
        """Register the action for "another instance asked to come forward"."""
        self._callback = callback

    def acquire(self) -> bool:
        """Claim the name, or defer to the instance that already holds it."""
        if self._probe(self._name):
            self._notify(self._name)
            return False
        self._server = self._listen(self._name, self._activate)
        return True

    def release(self) -> None:
        """Give the name up so the next launch can take it."""
        if self._server is not None:
            close = getattr(self._server, "close", None)
            if callable(close):
                close()
            self._server = None

    def _activate(self) -> None:
        if self._callback is not None:
            self._callback()
