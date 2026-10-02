"""Money must be a real number of kopecks, and a paid image must never be lost.

Each test was checked against the code as it was before these fixes and failed
there, so they are not restating the implementation.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.core.pricing import reserved_amount, round_money
from app.providers.http_utils import as_money
from app.services.generation_service import GenerationService
from app.services.history_stats import summarize, totals_by_model
from app.services.history_store import HistoryRecord, HistoryStore


def _record(cost: float, model: str = "tongyi-mai/z-image") -> HistoryRecord:
    return HistoryRecord(
        timestamp="2026-10-02T10:00:00",
        provider_id="polza",
        model=model,
        prompt="x",
        n=1,
        status="ok",
        cost_rub=cost,
        file_paths=[f"/tmp/{model}-{abs(hash(cost))}.png"],
    )


class TestMoneyPrecision:
    def test_rounding_each_price_is_not_enough(self) -> None:
        # This is the trap: the tail is not in the price, it appears during the
        # addition. Three images at 2.80 are recorded as 8.399999999999999
        # whether the price was rounded on the way in or not.
        assert sum([round_money(2.8)] * 3) != 8.4
        assert round_money(sum([2.8] * 3)) == 8.4

    def test_round_money_keeps_none(self) -> None:
        assert round_money(None) is None

    def test_round_money_rounds_to_kopecks(self) -> None:
        assert round_money(1.239) == 1.24
        assert round_money(3.004) == 3.0

    def test_money_from_a_provider_is_rounded(self) -> None:
        assert as_money("3.0049999") == 3.0
        assert as_money(2.8) == 2.8
        assert as_money(None) is None
        assert as_money("") is None
        assert as_money("nonsense") is None

    def test_reserved_amount_is_kopecks(self) -> None:
        # 20.4 * 3 is 61.199999999999996.
        assert reserved_amount(20.4, 3) == 61.2

    def test_history_total_has_no_tail(self) -> None:
        totals = summarize([_record(2.8) for _ in range(3)])
        assert totals.spent_rub == 8.4

    def test_group_totals_have_no_tail(self) -> None:
        groups = totals_by_model([_record(2.8) for _ in range(3)])
        assert len(groups) == 1
        assert groups[0].spent_rub == 8.4

    def test_a_priced_batch_sums_without_a_tail(self) -> None:
        # What one generation of three images reports back to the history.
        records = [_record(1.26) for _ in range(3)]
        assert summarize(records).spent_rub == 3.78


class TestFileNameCollision:
    def test_a_second_generation_never_overwrites_the_first(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Two paid batches of one model in the same second keep both files.

        The stamp in the name has a one-second precision, so without a name
        check the second batch replaces the first on disk while the history
        still claims both.
        """
        import app.services.generation_service as gs
        from app.core.models import (
            GeneratedImage,
            GenerationRequest,
            GenerationResult,
            ModelInfo,
        )

        payload = b"\x89PNG\r\n\x1a\n" + b"x" * 32
        model = ModelInfo(
            id="tongyi-mai/z-image", provider_id="polza", min_price=2.8, max_price=2.8
        )
        request = GenerationRequest(
            provider_id="polza", model="tongyi-mai/z-image", prompt="x", n=1
        )

        class Provider:
            def generate(self, request, *, timeout=180, cancel_check=None):
                return GenerationResult(
                    images=[GeneratedImage(data=payload)],
                    cost_rub=2.8,
                    balance=None,
                    model="tongyi-mai/z-image",
                )

        monkeypatch.setattr(gs, "create_provider", lambda provider_id, api_key: Provider())
        monkeypatch.setattr(gs, "now_iso", lambda: "2026-10-02T10:00:00")

        history_path = tmp_path / "history.json"
        service = GenerationService(HistoryStore(history_path))
        save_dir = tmp_path / "images"

        first = service.generate(request, model, save_dir=save_dir, api_key="k")
        second = service.generate(request, model, save_dir=save_dir, api_key="k")

        assert first.file_paths != second.file_paths, "the same path was handed out twice"
        for path in (*first.file_paths, *second.file_paths):
            assert Path(path).exists(), f"{path} was overwritten and is gone"

        records = json.loads(history_path.read_text(encoding="utf-8"))["records"]
        assert len(records) == 2
        assert sum(r["cost_rub"] for r in records) == 5.6

    def test_the_extra_suffix_appears_only_on_a_collision(self, tmp_path: Path) -> None:
        import app.services.generation_service as gs
        from app.core.models import GeneratedImage, GenerationResult

        service = GenerationService(HistoryStore(tmp_path / "history.json"))
        request = gs.GenerationRequest(
            provider_id="polza", model="tongyi-mai/z-image", prompt="x", n=1
        )
        result = GenerationResult(
            images=[GeneratedImage(data=b"\x89PNG\r\n\x1a\n" + b"a" * 8)],
            cost_rub=2.8,
            balance=None,
            model="tongyi-mai/z-image",
        )
        monkey_dir = tmp_path / "images"

        first, error = service._save_images(result, monkey_dir, request)
        second, error_two = service._save_images(result, monkey_dir, request)

        assert error is None and error_two is None
        assert Path(first[0]).stem.endswith("tongyi-mai-z-image")
        assert Path(second[0]).stem.endswith("tongyi-mai-z-image_2")
