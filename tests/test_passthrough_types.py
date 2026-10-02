"""Types for the extra parameters Polza documents.

`upscale_factor` is the reason this module exists: the aggregator declares it as
a *string* enumeration of '1' '2' '4' '8', so a value that looks like a number
must not be cast to one.
"""

from __future__ import annotations

from app.providers.passthrough import PASSTHROUGH_TYPES, typed_passthrough


class TestKnownTypes:
    def test_booleans_accept_the_usual_spellings(self) -> None:
        for text in ("true", "True", "1", "yes", "on", "да"):
            assert typed_passthrough({"isEnhance": text})["isEnhance"] is True
        for text in ("false", "False", "0", "no", "off", "нет"):
            assert typed_passthrough({"isEnhance": text})["isEnhance"] is False

    def test_numbers_become_numbers(self) -> None:
        assert typed_passthrough({"guidance_scale": "7.5"})["guidance_scale"] == 7.5
        assert typed_passthrough({"strength": "0,8"})["strength"] == 0.8
        assert isinstance(typed_passthrough({"strength": "1"})["strength"], int)

    def test_upscale_factor_stays_a_string(self) -> None:
        """It is an enumeration of '1' '2' '4' '8', not a number."""
        result = typed_passthrough({"upscale_factor": "2"})

        assert result["upscale_factor"] == "2"
        assert isinstance(result["upscale_factor"], str)

    def test_upscale_factor_is_not_in_the_type_map(self) -> None:
        assert "upscale_factor" not in PASSTHROUGH_TYPES


class TestUnknownAndBroken:
    def test_an_unknown_parameter_is_left_alone(self) -> None:
        result = typed_passthrough({"font_name": "Inter"})

        assert result == {"font_name": "Inter"}

    def test_a_value_that_is_not_a_number_is_left_as_text(self) -> None:
        """Nothing is sent yet, so the aggregator can reject it with its own text."""
        result = typed_passthrough({"guidance_scale": "high"})

        assert result["guidance_scale"] == "high"

    def test_an_unreadable_boolean_is_left_as_text(self) -> None:
        result = typed_passthrough({"isEnhance": "maybe"})

        assert result["isEnhance"] == "maybe"

    def test_non_text_values_pass_through_untouched(self) -> None:
        result = typed_passthrough({"isEnhance": True, "guidance_scale": 3})

        assert result == {"isEnhance": True, "guidance_scale": 3}

    def test_empty_passthrough_stays_empty(self) -> None:
        assert typed_passthrough({}) == {}
