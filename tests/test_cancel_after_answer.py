"""Cancelling after the aggregator answered must not throw the pictures away."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import pytest

from app.core.errors import CancelledError
from app.core.models import GeneratedImage, GenerationRequest, GenerationResult, ModelInfo
from app.services.generation_service import GenerationService
from app.services.history_store import HistoryStore

PNG = b"\x89PNG\r\n\x1a\n" + b"z" * 24


class _Provider:
    """Answers straight away, ignoring the cancel request like a vendor would."""

    def generate(self, request, *, timeout=180, cancel_check=None):
        return GenerationResult(
            images=[GeneratedImage(data=PNG)],
            cost_rub=2.8,
            balance=None,
            model=request.model,
        )


def _late_cancel() -> Callable[[], bool]:
    """A cancel that says "no" while the request starts and "yes" after it."""
    calls = {"n": 0}

    def check() -> bool:
        calls["n"] += 1
        return calls["n"] > 1

    return check


def _request() -> GenerationRequest:
    return GenerationRequest(provider_id="polza", model="tongyi-mai/z-image", prompt="x", n=1)


def _model() -> ModelInfo:
    return ModelInfo(
        id="tongyi-mai/z-image", provider_id="polza", min_price=1.4, max_price=1.4, max_n=6
    )


def _service(tmp_path: Path) -> tuple[GenerationService, Path]:
    import app.services.generation_service as gs

    gs.create_provider = lambda provider_id, api_key: _Provider()
    history = tmp_path / "history.json"
    return GenerationService(HistoryStore(history)), history


class TestCancelAfterTheAnswer:
    def test_a_paid_result_is_saved_even_if_cancel_arrived_late(
        self, tmp_path: Path
    ) -> None:
        """The money is already spent; throwing the picture away helps nobody."""
        service, _history_path = _service(tmp_path)

        outcome = service.generate(
            _request(),
            _model(),
            save_dir=tmp_path / "out",
            api_key="k",
            cancel_check=_late_cancel(),
        )

        assert len(outcome.file_paths) == 1
        assert Path(outcome.file_paths[0]).exists()
        assert outcome.result.cost_rub == 2.8

    def test_the_history_records_the_cost_of_the_late_cancel(
        self, tmp_path: Path
    ) -> None:
        service, history_path = _service(tmp_path)

        service.generate(
            _request(),
            _model(),
            save_dir=tmp_path / "out",
            api_key="k",
            cancel_check=_late_cancel(),
        )

        records = json.loads(history_path.read_text(encoding="utf-8"))["records"]
        assert len(records) == 1
        assert records[0]["status"] == "ok"
        assert records[0]["cost_rub"] == 2.8
        assert len(records[0]["file_paths"]) == 1

    def test_a_cancel_before_the_request_still_stops_it(self, tmp_path: Path) -> None:
        """Nothing has been paid for yet, so nothing is written."""
        service, history_path = _service(tmp_path)
        with pytest.raises(CancelledError):
            service.generate(
                _request(),
                _model(),
                save_dir=tmp_path / "out",
                api_key="k",
                cancel_check=lambda: True,
            )

        assert not history_path.exists()
