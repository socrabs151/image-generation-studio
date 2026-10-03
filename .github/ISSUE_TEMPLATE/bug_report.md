name: Ошибка
about: Что-то сломалось
title: ""
labels: ["bug"]
body:
  - type: markdown
    attributes:
      value: |
        Спасибо, что сообщаете. Ключи в issue не прикладывайте — приложение хранит их
        в `data/settings.json`, отправлять их не нужно.

  - type: textarea
    id: what
    attributes:
      label: Что произошло
      description: Что вы ожидали увидеть и что получилось на самом деле.
    validations:
      required: true

  - type: textarea
    id: steps
    attributes:
      label: Шаги
      value: |
        1.
        2.
    validations:
      required: true

  - type: input
    id: version
    attributes:
      label: Версия
      placeholder: "0.3.0"
    validations:
      required: true

  - type: dropdown
    id: aggregator
    attributes:
      label: Агрегатор
      options:
        - AITUNNEL
        - Polza.ai
        - Оба
        - Не применимо
    validations:
      required: true

  - type: textarea
    id: logs
    attributes:
      label: Строки из `data/app.log`
      description: Только строки вокруг ошибки, без ключей.
      render: text
