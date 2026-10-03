name: Pull request
about: Изменение в коде
title: ""
body:
  - type: textarea
    id: what
    attributes:
      label: Что изменено
      description: Одна-две фразы: что стало работать иначе.
    validations:
      required: true

  - type: textarea
    id: checks
    attributes:
      label: Как проверялось
      value: |
        ruff check .
        mypy
        pytest -q
      render: text
    validations:
      required: true

  - type: checkboxes
    id: rules
    attributes:
      label: Чек-лист
      options:
        - label: ruff check . проходит
          required: true
        - label: mypy проходит
          required: true
        - label: pytest проходит
          required: true
        - label: CHANGELOG.md обновлён
        - label: Изменение описано по-человечески, без ссылок на приватные файлы
