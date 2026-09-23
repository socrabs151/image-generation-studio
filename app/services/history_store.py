# -*- coding: utf-8 -*-
"""Хранилище истории: history.json (specs.md §5.3, §9.4).

Обрезка до лимита, атомарная запись. Реализация — этап M2.
"""

from __future__ import annotations

# TODO(M2): HistoryStore.