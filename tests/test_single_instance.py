from __future__ import annotations

from pathlib import Path

from app.ui.single_instance import SingleInstanceGuard, server_name


class FakeServer:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


def build_guard(*, running: bool = False, can_listen: bool = True):
    calls: dict[str, list] = {"notified": [], "listened": [], "activated": []}
    server = FakeServer()

    def probe(name: str) -> bool:
        calls["probed"] = calls.get("probed", []) + [name]
        return running

    def notify(name: str) -> None:
        calls["notified"].append(name)

    def listen(name: str, on_activate) -> object | None:
        calls["listened"].append(name)
        calls["activate"] = on_activate
        return server if can_listen else None

    guard = SingleInstanceGuard("test-server", probe=probe, notify=notify, listen=listen)
    return guard, server, calls


def test_the_first_instance_takes_the_name() -> None:
    guard, _server, calls = build_guard()

    assert guard.acquire() is True
    assert guard.is_primary is True
    assert calls["listened"] == ["test-server"]
    assert calls["notified"] == []


def test_a_second_instance_asks_the_window_forward_and_stops() -> None:
    guard, _server, calls = build_guard(running=True)

    assert guard.acquire() is False
    assert guard.is_primary is False
    assert calls["notified"] == ["test-server"]
    assert calls["listened"] == []


def test_release_gives_the_name_up() -> None:
    guard, server, _calls = build_guard()
    guard.acquire()

    guard.release()

    assert server.closed is True
    assert guard.is_primary is False


def test_the_window_opens_even_when_the_name_cannot_be_claimed() -> None:
    # A guard that refuses to start the app would be worse than two windows.
    guard, _server, _calls = build_guard(can_listen=False)

    assert guard.acquire() is True
    assert guard.is_primary is False


def test_the_activation_callback_runs_on_request() -> None:
    guard, _server, calls = build_guard()
    guard.acquire()
    seen: list[str] = []
    guard.set_activation_callback(lambda: seen.append("raised"))

    calls["activate"]()

    assert seen == ["raised"]


def test_activation_without_a_callback_is_harmless() -> None:
    guard, _server, calls = build_guard()
    guard.acquire()

    calls["activate"]()  # must not raise


def test_release_without_a_server_is_harmless() -> None:
    guard, _server, _calls = build_guard()

    guard.release()


def test_the_server_name_separates_data_directories() -> None:
    first = server_name(Path("C:/tmp/studio"))
    second = server_name(Path("C:/tmp/studio"))

    assert first == second
    assert first != server_name(Path("D:/other/studio"))


def test_the_server_name_starts_with_the_application_id() -> None:
    assert server_name(Path("C:/tmp/studio")).startswith("image-generation-studio-")
