# -*- coding: utf-8 -*-
"""QRunnable-обёртки над сервисами для выполнения не в UI-потоке (specs.md §9.6).

Сигналы finished / failed / progress. Реализация — этап M1.
"""

from __future__ import annotations

# TODO(M1): CatalogWorker, GenerationWorker.