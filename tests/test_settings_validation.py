"""B9: a settings file that cannot be written back is refused on read."""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from app.services.settings_store import SettingsStore, _as_float, _as_int


class TestNumbers:
    @pytest.mark.parametrize("value", ["nan", "NaN", float("nan"), "inf", "-inf", "Infinity"])
    def test_a_number_that_cannot_be_written_back_is_refused(self, value: object) -> None:
        """JSON cannot write nan, so such a setting breaks the file on the next save."""
        assert math.isfinite(_as_float(value, 50.0))
        assert _as_float(value, 50.0) == 50.0

    def test_real_numbers_are_untouched(self) -> None:
        assert _as_float("12.5", 50.0) == 12.5
        assert _as_float(0, 50.0) == 0.0

    def test_a_boolean_is_not_a_number(self) -> None:
        assert _as_float(True, 50.0) == 50.0
        assert _as_int(True, 7) == 7

    def test_nonsense_falls_back(self) -> None:
        assert _as_float("soon", 50.0) == 50.0
        assert _as_float(None, 50.0) == 50.0


class TestTheFileRoundTrip:
    def _store(self, tmp_path: Path, body: dict) -> SettingsStore:
        path = tmp_path / "settings.json"
        path.write_text(json.dumps(body), encoding="utf-8")
        return SettingsStore(path)

    def test_nan_in_the_file_does_not_break_the_next_save(self, tmp_path: Path) -> None:
        store = self._store(tmp_path, {"confirm_threshold_rub": "nan"})

        settings = store.load()
        assert math.isfinite(settings.confirm_threshold_rub)

        store.save(settings)
        # The point: the file still parses afterwards.
        assert SettingsStore(tmp_path / "settings.json").load() is not None

    def test_inf_in_the_file_does_not_break_the_next_save(self, tmp_path: Path) -> None:
        store = self._store(tmp_path, {"session_limit_rub": "Infinity"})

        settings = store.load()
        assert math.isfinite(settings.session_limit_rub)

        store.save(settings)
        assert SettingsStore(tmp_path / "settings.json").load() is not None

    def test_zero_history_limit_does_not_switch_trimming_off(self, tmp_path: Path) -> None:
        """0 means "keep everything forever", which nothing offered and nobody wants."""
        settings = self._store(tmp_path, {"history_limit": 0}).load()

        assert settings.history_limit >= 1

    def test_a_negative_history_limit_is_clamped_too(self, tmp_path: Path) -> None:
        settings = self._store(tmp_path, {"history_limit": -50}).load()

        assert settings.history_limit >= 1

    def test_a_normal_limit_is_kept(self, tmp_path: Path) -> None:
        assert self._store(tmp_path, {"history_limit": 25}).load().history_limit == 25

    def test_a_missing_limit_keeps_the_default(self, tmp_path: Path) -> None:
        assert self._store(tmp_path, {}).load().history_limit == 200
