"""Tests for the file name template.

Checked against the code as it was before: without a template there was one
fixed naming scheme, so none of these could pass.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from app.services.file_names import (
    DEFAULT_FILENAME_TEMPLATE,
    NameParts,
    render_filename,
    sanitize,
    unknown_placeholders,
)
from app.services.history_store import HistoryStore

WHEN = datetime(2026, 10, 2, 21, 5, 7)


class TestPlaceholders:
    def test_the_default_names_the_file_by_date_and_model(self) -> None:
        parts = NameParts(model="tongyi-mai/z-image", when=WHEN)

        assert render_filename(DEFAULT_FILENAME_TEMPLATE, parts) == (
            "2026-10-02-21-05-07_tongyi-mai-z-image"
        )

    def test_every_documented_placeholder_is_filled(self) -> None:
        parts = NameParts(
            model="z-image",
            provider="polza",
            prompt="a cat",
            index=2,
            total=3,
            when=WHEN,
        )
        # A dash separates the values: a pipe would be replaced, it is one of
        # the characters Windows does not allow in a name. Spaces are kept,
        # Windows allows them, so a prompt reads as written.
        template = "{date}-{time}-{datetime}-{model}-{provider}-{prompt}-{index}-{total}"

        assert render_filename(template, parts) == (
            "2026-10-02-21-05-07-2026-10-02_21-05-07-z-image-polza-a cat-2-3"
        )

    def test_a_slash_in_the_model_becomes_a_dash(self) -> None:
        # Otherwise the name would land in a subfolder that may not exist.
        parts = NameParts(model="tongyi-mai/z-image", when=WHEN)

        assert "/" not in render_filename("{model}", parts)

    def test_a_prompt_cannot_escape_the_folder(self) -> None:
        parts = NameParts(model="m", prompt="../../etc/passwd", when=WHEN)

        rendered = render_filename("{prompt}", parts)

        assert "/" not in rendered
        assert ".." not in rendered

    def test_an_unknown_placeholder_is_left_visible(self) -> None:
        # Silently dropping it would change the name with no explanation.
        parts = NameParts(model="m", when=WHEN)

        assert render_filename("{model}-{typo}", parts) == "m-{typo}"

    def test_unknown_placeholders_are_reported(self) -> None:
        assert unknown_placeholders("{model}-{nope}-{also_nope}") == ["{nope}", "{also_nope}"]
        assert unknown_placeholders(DEFAULT_FILENAME_TEMPLATE) == []


class TestSafety:
    def test_windows_reserved_names_are_replaced(self) -> None:
        assert sanitize("CON") == ""
        assert sanitize("COM1") == ""

    def test_trailing_dots_and_spaces_are_dropped(self) -> None:
        # Windows strips them silently, so two names would collide.
        assert sanitize("name...") == "name"
        assert sanitize("name   ") == "name"

    def test_control_characters_do_not_survive(self) -> None:
        assert sanitize("a\x00b\x1fc") == "a-b-c"

    def test_long_values_are_cut(self) -> None:
        assert len(sanitize("x" * 500)) <= 120

    def test_an_empty_template_still_produces_a_name(self) -> None:
        parts = NameParts(model="z-image", when=WHEN)

        assert render_filename("", parts) == "2026-10-02-21-05-07_z-image"
        assert render_filename("{prompt}", NameParts(model="m", prompt="///", when=WHEN))

    def test_a_template_of_only_illegal_characters_falls_back(self) -> None:
        parts = NameParts(model="z-image", when=WHEN)

        rendered = render_filename("<<<", parts)

        assert rendered == "2026-10-02-21-05-07_z-image"


class TestBatches:
    def test_index_and_total_are_available_for_each_file(self) -> None:
        first = render_filename(
            "{model}_{index}of{total}", NameParts(model="m", index=1, total=3, when=WHEN)
        )
        second = render_filename(
            "{model}_{index}of{total}", NameParts(model="m", index=2, total=3, when=WHEN)
        )

        assert first == "m_1of3"
        assert second == "m_2of3"

    def test_the_caller_separates_a_batch_even_without_the_index(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A template without {index} must not cost the user two pictures.

        The save path refuses a name that is taken, so three images of one batch
        become three files instead of one overwritten twice.
        """
        import app.services.generation_service as gs
        from app.core.models import GeneratedImage, GenerationRequest, GenerationResult

        request = GenerationRequest(provider_id="polza", model="m", prompt="x", n=3)
        result = GenerationResult(
            images=[GeneratedImage(data=b"\x89PNG\r\n\x1a\n" + bytes([n]) * 8) for n in range(3)],
            cost_rub=3.0,
            balance=None,
            model="m",
        )
        monkeypatch.setattr(gs, "now_iso", lambda: "2026-10-02T21:05:07")
        service = gs.GenerationService(HistoryStore(tmp_path / "history.json"))

        paths, error = service._save_images(result, tmp_path / "out", request, template="{model}")

        assert error is None
        assert len(paths) == 3
        assert len(set(paths)) == 3, f"two images share a name: {paths}"
