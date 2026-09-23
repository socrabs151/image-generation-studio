# -*- coding: utf-8 -*-
"""Иерархия исключений (specs.md §10).

AppError → ProviderError → InsufficientFundsError, BadParameterError,
ProviderTimeoutError, NetworkError. Реализация — этап M1.
"""

from __future__ import annotations

# TODO(M1): исключения из specs.md §10.