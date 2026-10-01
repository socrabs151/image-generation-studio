"""Guards on the calls into the background worker.

The signature of :meth:`MainWindow._run` takes ``**kwargs``, which are handed to
the function that runs in the thread. A misspelled keyword therefore does not
fail in the call: it travels into the provider call and raises there, thousands
of lines away from the edit that caused it. The catalog stopped loading with
``CatalogService.load() got an unexpected keyword argument 'unlock_prompt'``
because of exactly this.

The checks read the source, so they need no Qt.
"""

from __future__ import annotations

import ast
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent
MAIN_WINDOW = ROOT / "app" / "ui" / "main_window.py"
SOURCE = MAIN_WINDOW.read_text(encoding="utf-8")
TREE = ast.parse(SOURCE)


def _function(name: str) -> ast.FunctionDef:
    for node in ast.walk(TREE):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"{name} not found in {MAIN_WINDOW.name}")


def _run_parameter_names() -> set[str]:
    node = _function("_run")
    names = {argument.arg for argument in node.args.args}
    names |= {argument.arg for argument in node.args.kwonlyargs}
    return names


def _call_keywords(function: str) -> set[str]:
    node = _function(function)
    return {keyword.arg for keyword in ast.walk(node) if isinstance(keyword, ast.keyword)}


# ---------- every call matches the signature ----------


def test_run_takes_its_bookkeeping_as_keyword_only() -> None:
    """``**kwargs`` goes straight to the function in the thread. A bookkeeping
    parameter added as a normal one would swallow a legitimate worker keyword of
    the same name, so bookkeeping is keyword-only and checked here."""
    declared = _run_parameter_names()
    assert "is_generation" in declared
    node = _function("_run")
    positional = {argument.arg for argument in node.args.args}
    keyword_only = {argument.arg for argument in node.args.kwonlyargs}
    assert "is_generation" in keyword_only, (
        f"is_generation must be keyword-only, otherwise it competes with the "
        f"worker's own arguments; declared: {sorted(declared)}"
    )
    assert positional == {"self", "function", "args", "kwargs"} | {"on_done", "on_fail"} or (
        positional & {"self", "function", "args", "kwargs"}
    ), f"unexpected positional parameters: {sorted(positional)}"


def test_no_call_passes_a_name_that_is_only_a_ui_concern() -> None:
    """``api_key`` and the other worker arguments are legitimate: they go to the
    function in the thread. What must never happen is a keyword ``_run`` does not
    declare, because it then lands on the provider's own signature."""
    callers = [
        call
        for parent in ast.walk(TREE)
        if isinstance(parent, ast.FunctionDef)
        for call in ast.walk(parent)
        if isinstance(call, ast.Call)
        and isinstance(call.func, ast.Attribute)
        and call.func.attr == "_run"
        and parent.name != "_run"
    ]
    assert callers, "no caller of _run found"

    bookkeeping = {"is_generation", "on_done", "on_fail"}
    for call in callers:
        for keyword in call.keywords:
            if keyword.arg in bookkeeping:
                continue
            # Everything else belongs to the worker function; it must therefore be
            # something the app itself passes, never a UI-only name.
            assert not keyword.arg.startswith("_"), (
                f"'_run({keyword.arg}=...)' is not a parameter of _run"
            )


def test_no_call_uses_the_old_unlock_prompt_name() -> None:
    """It was renamed to ``is_generation`` and two calls kept the old name."""
    assert "unlock_prompt" not in SOURCE, (
        "unlock_prompt is no longer a parameter of _run(); use is_generation"
    )


def test_generation_is_the_only_caller_that_claims_it() -> None:
    """Only a finished generation may re-enable Generate, so only the generation
    may pass ``is_generation=True``."""
    for function in ("generate", "refresh_catalog", "check_balance"):
        node = _function(function)
        values = [
            keyword.value.value
            for keyword in ast.walk(node)
            if isinstance(keyword, ast.keyword)
            and keyword.arg == "is_generation"
            and isinstance(keyword.value, ast.Constant)
        ]
        expected = function == "generate"
        for value in values:
            assert value is expected, (
                f"{function} passes is_generation={value}, expected {expected}"
            )


def test_the_run_signature_declares_is_generation() -> None:
    assert "is_generation" in _run_parameter_names()


def test_generation_claims_the_slot_and_the_helpers_do_not() -> None:
    """Only a finished generation may re-enable Generate, so only the generation
    may claim the slot."""
    for function, expected in (
        ("generate", True),
        ("refresh_catalog", False),
        ("check_balance", False),
    ):
        node = _function(function)
        values = [
            keyword.value.value
            for keyword in ast.walk(node)
            if isinstance(keyword, ast.keyword)
            and keyword.arg == "is_generation"
            and isinstance(keyword.value, ast.Constant)
        ]
        assert values, f"{function} does not say whether it is a generation"
        for value in values:
            assert value is expected, (
                f"{function} passes is_generation={value}, expected {expected}"
            )


# ---------- the panel writes to the file too ----------


def test_panel_messages_are_mirrored_to_the_log_file() -> None:
    """An interface error used to exist only in the panel, so app.log could not
    explain a failure the user had already reported."""
    panel = (ROOT / "app" / "ui" / "panels" / "log.py").read_text(encoding="utf-8")
    assert "_mirror_to_file" in panel
    assert "image_generation_studio_ui" in panel, (
        "the mirror must use its own logger, or it loops back through the bridge"
    )
    assert 'file_logger("image_generation_studio_ui")' in panel, (
        "the mirror logger needs the rotating file handler"
    )


def test_the_mirror_logger_is_not_a_child_of_the_app_logger() -> None:
    """A child would deliver to the bridge, into the panel, and into the mirror
    again, once per line, forever.

    The mirror logger is created in the panel with its own name, and
    ``logging_setup.file_logger`` takes whatever name it is given, so the check
    is that no name used anywhere starts with the application logger followed by
    a dot."""
    app_logger = "image_generation_studio"
    for relative in ("app/logging_setup.py", "app/ui/panels/log.py"):
        text = (ROOT / relative).read_text(encoding="utf-8")
        children = re.findall(rf'"{re.escape(app_logger)}\.[a-z_.]*"', text)
        assert not children, (
            f"{relative} creates a child of {app_logger}: {children}; it would "
            "travel through the bridge back into the panel, once per line"
        )
    panel = (ROOT / "app" / "ui" / "panels" / "log.py").read_text(encoding="utf-8")
    assert '"image_generation_studio_ui"' in panel, (
        "the mirror logger must have a name of its own, not a child"
    )
