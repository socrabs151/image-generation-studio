# Contributing

Спасибо за интерес к проекту. Ниже — как настроить окружение и какие правила соблюдать.

## Окружение

```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
# Linux/macOS
source .venv/bin/activate

pip install -e ".[dev]"
```

## Запуск приложения

```bash
python -m app
```

## Проверки перед коммитом

```bash
ruff check .        # линтер
ruff format .       # форматтер (по желанию)
pytest -q           # тесты
```

CI прогоняет `ruff check` и `pytest` на каждый push/PR — держите их зелёными.

## Стандарты кода

Полный свод — `specs.md` §11. Ключевое:

- Python 3.11+, type hints везде, `from __future__ import annotations`.
- Длина строки — 100 символов.
- Docstrings на русском; комментарии — только для неочевидного.
- Файловый ввод-вывод — всегда `encoding="utf-8"`.
- Логирование через `logging`, не `print`.
- Ядро (`core/`, `providers/`, `services/`) не импортирует PySide6.

## Сообщение о проблемах

Опишите шаги воспроизведения, ожидаемое и фактическое поведение. Не прикладывайте
API-ключи и личные данные.