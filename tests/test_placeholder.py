# -*- coding: utf-8 -*-
"""Заготовка тестов ядра. Реализация — M1/M4."""

from __future__ import annotations

import pytest


@pytest.mark.skip(reason="Тесты появятся на этапе M1 (specs.md §16)")
def test_placeholder() -> None:
    """Плейсхолдер, чтобы CI проходил до появления реальных тестов."""
    assert True