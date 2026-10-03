name: Предложение
about: Идея или доработка
title: ""
labels: ["enhancement"]
body:
  - type: textarea
    id: problem
    attributes:
      label: Какая задача не решается
      description: Опишите ситуацию, а не решение.
    validations:
      required: true

  - type: textarea
    id: idea
    attributes:
      label: Как вы представляете решение
    validations:
      required: true

  - type: dropdown
    id: aggregator
    attributes:
      label: Относится к агрегатору
      options:
        - AITUNNEL
        - Polza.ai
        - Не применимо
