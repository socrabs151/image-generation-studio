"""A4: a total that hides unknown prices must say so."""

from __future__ import annotations

from app.services.history_stats import HistoryTotals, summarize
from app.services.history_store import HistoryRecord


def _record(**kwargs) -> HistoryRecord:
    base = {
        "timestamp": "2026-10-02T10:00:00",
        "provider_id": "polza",
        "model": "m",
        "prompt": "x",
        "n": 1,
        "status": "ok",
        "cost_rub": 2.8,
        "file_paths": ["C:/a.png"],
    }
    base.update(kwargs)
    return HistoryRecord(**base)


class TestSummary:
    def test_a_fully_priced_history_shows_only_the_total(self) -> None:
        line = summarize([_record(), _record()]).summary()

        assert "without a known price" not in line
        assert "5.60" in line

    def test_an_unpriced_attempt_is_called_out(self) -> None:
        records = [
            _record(),
            _record(status="error", cost_rub=None, file_paths=[]),
        ]

        line = summarize(records).summary()

        assert "1 without a known price" in line

    def test_several_unpriced_attempts_are_counted(self) -> None:
        records = [_record(status="error", cost_rub=None, file_paths=[]) for _ in range(3)]

        line = summarize(records).summary()

        assert "3 without a known price" in line

    def test_the_total_still_adds_up_what_is_known(self) -> None:
        records = [
            _record(cost_rub=1.4),
            _record(status="error", cost_rub=None, file_paths=[]),
            _record(cost_rub=1.4),
        ]
        totals = summarize(records)

        assert totals.spent_rub == 2.8
        assert totals.unpriced == 1

    def test_the_count_is_carried_in_the_dataclass(self) -> None:
        assert HistoryTotals(unpriced=2).summary().endswith("2 without a known price")
