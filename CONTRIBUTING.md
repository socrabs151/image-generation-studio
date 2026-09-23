# Contributing

## Окружение

```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
# Linux/macOS
source .venv/bin/activate

pip install -e ".[dev]"
```

## Проверки перед коммитом

```bash
ruff check .        # линтер
ruff format .       # форматтер
pytest -q           # тесты
```

CI выполняет `ruff check` и `pytest` на каждый push и pull request; обе проверки
должны проходить.

## Стандарты кода

- Python 3.11+, аннотации типов везде, `from __future__ import annotations`.
- Максимальная длина строки — 100 символов.
- Docstrings для модулей, классов и публичных функций.
- Файловый ввод-вывод — всегда с `encoding="utf-8"`.
- Логирование через `logging`, не `print`.
- Слои `core/`, `providers/`, `services/` не импортируют PySide6.

## Сообщения коммитов

Conventional Commits, на английском языке:

```
feat: add model catalog caching
fix: correct price range calculation
docs: update contributing guide
chore: bump dependencies
```

Типы: `feat`, `fix`, `docs`, `refactor`, `test`, `chore`.

## Сообщение о проблемах

Опишите шаги воспроизведения, ожидаемое и фактическое поведение. Не прикладывайте
API-ключи и персональные данные.