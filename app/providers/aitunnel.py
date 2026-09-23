# -*- coding: utf-8 -*-
"""Провайдер AITUNNEL (specs.md §9.2).

Портируется логика из img-generator-script/aitunnel_image_models.py:
публичный каталог, POST /v1/images/generations, баланс/бюджет.
Реализация — этап M1.
"""

from __future__ import annotations

# TODO(M1): AitunnelProvider.