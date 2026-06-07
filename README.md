# TgParser

**Telegram-канал парсер** — утилита для извлечения сообщений из открытых (MTProto API) и закрытых (Web HTML) Telegram-каналов.

[![Python Version](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Code style: ruff](https://img.shields.io/badge/code%20style-ruff-000000.svg)](https://github.com/astral-sh/ruff)

---

## Возможности

- **Авторизация** через QR-код (Web) или MTProto (Telethon) с сохранением сессии
- **Парсинг открытых каналов** — прямое чтение через MTProto API (Telethon)
- **Парсинг закрытых каналов** — чтение через web-версию Telegram (Playwright + BeautifulSoup)
- **Обход защиты от копирования** — автоматическое снятие CSS `user-select: none`, блокировки контекстного меню
- **Вывод данных** в JSON, CSV, plain-text или SQLite
- **Инкрементальный парсинг** — сохранение только новых сообщений
- **CLI-интерфейс** на базе Click

---

## Установка

### Из исходного кода

```bash
# Клонировать репозиторий
git clone https://github.com/borodatych/tgparser.git
cd tgparser

# Создать виртуальное окружение
python -m venv .venv
source .venv/bin/activate  # Linux/macOS
.venv\Scripts\activate     # Windows

# Установить пакет с dev-зависимостями
pip install -e ".[dev]"

# Установить Playwright браузеры (требуется для web-парсера)
playwright install chromium
```

### Через pip

```bash
pip install tgparser-cli
playwright install chromium
```

---

## Настройка

### 1. Переменные окружения

Скопируйте `.env.example` в `.env` и заполните:

```bash
cp .env.example .env
```

Обязательные переменные:

| Переменная | Описание |
|-----------|----------|
| `API_ID` | API ID из [my.telegram.org](https://my.telegram.org/apps) |
| `API_HASH` | API Hash оттуда же |
| `PHONE_NUMBER` | Номер телефона для MTProto-авторизации (в международном формате) |

### 2. Конфигурационный файл (опционально)

Создайте `config.yaml` в корне проекта:

```yaml
parsing:
  scroll_delay_ms: 1500    # задержка между скроллами (web-парсер)
  max_messages: 1000       # лимит сообщений за один запуск
  rate_limit_sleep: 30     # пауза при FloodWait (сек)

storage:
  output_dir: data/output
  session_dir: data/sessions
```

---

## Использование

### Авторизация

```bash
# Web-авторизация (QR-код) — для закрытых каналов
tgparser auth

# Принудительная переавторизация
tgparser auth --force

# MTProto-авторизация — для открытых каналов
tgparser auth --type mtproto
```

### Парсинг открытого канала (MTProto)

```bash
tgparser parse open @channel_username
```

Опции:
- `--limit N` — максимум сообщений (по умолчанию 100)
- `--since YYYY-MM-DD` — фильтр по дате (сообщения не старше указанной)
- `--until YYYY-MM-DD` — фильтр по дате (сообщения не новее указанной)
- `--offset N` — смещение от последнего сообщения

### Парсинг закрытого канала (Web)

```bash
tgparser parse closed https://t.me/channel_username
```

Опции:
- `--limit N` — максимум сообщений
- `--since YYYY-MM-DD` — фильтр по дате
- `--until YYYY-MM-DD` — фильтр по дате

> **Примечание:** Для закрытых каналов требуется предварительная web-авторизация (`tgparser auth`).

### Экспорт

```bash
# Вывод в консоль (plain-text)
tgparser export --input data/output/messages.json

# Сохранение в JSON
tgparser export --input data/output/messages.json --format json --output data/output/export.json

# Сохранение в CSV
tgparser export --input data/output/messages.json --format csv --output data/output/export.csv

# Сохранение в SQLite
tgparser export --input data/output/messages.json --format sqlite --output data/output/export.db

# Инкрементальный экспорт (только новые сообщения)
tgparser export --input data/output/messages.json --incremental
```

### GUI (графический интерфейс)

TgParser поставляется с текстовым графическим интерфейсом, построенным на [Textual](https://textual.textualize.io/).

```bash
# Запуск GUI
tgparser gui

# Или напрямую через модуль
python -m tgparser.gui
```

GUI предоставляет удобный интерфейс для:
- Авторизации (web и MTProto)
- Парсинга каналов с настройками
- Просмотра результатов
- Управления сохранёнными каналами

> **Примечание:** GUI — рекомендуемый способ взаимодействия для большинства пользователей.

---

## Примеры

### Сохранить 50 последних сообщений из открытого канала в JSON

```bash
tgparser parse open @python_news --limit 50 --format json --output data/output/python_news.json
```

### Сохранить сообщения из закрытого канала за последнюю неделю

```bash
tgparser parse closed https://t.me/private_channel --since 2025-01-01
```

### Экспортировать в CSV с инкрементальным режимом

```bash
tgparser parse open @tech_news --format csv --output data/output/tech_news.csv
tgparser export --input data/output/tech_news.csv --incremental
```

---

## Структура проекта

```
tgparser/
├── src/
│   └── tgparser/
│       ├── auth/          # Модули авторизации (web, mtproto)
│       ├── parsers/       # Парсеры (mtproto_parser, web_parser)
│       ├── storage/       # Вывод и хранение (JSON, CSV, TXT, SQLite)
│       ├── models/        # Модели данных (Message)
│       ├── cli.py         # CLI-интерфейс (Click)
│       ├── config.py      # Загрузка конфигурации
│       └── utils.py       # Вспомогательные функции
├── tests/                 # Тесты (pytest)
├── data/
│   ├── output/            # Результаты парсинга
│   └── sessions/          # Сохранённые сессии
├── docs/                  # Документация
├── config.yaml            # Конфигурация (опционально)
├── .env                   # Секреты (не в git)
├── pyproject.toml         # Настройки проекта
└── README.md              # Этот файл
```

## Совместимость

- **Python**: 3.11, 3.12
- **ОС**: Windows, Linux, macOS
- **Браузер**: Chromium (устанавливается через `playwright install chromium`)

---

## Разработка и тестирование

```bash
# Запуск всех тестов
pytest tests -v

# Запуск только smoke-тестов GUI
pytest tests/test_gui_smoke.py -v

# Запуск только интеграционных тестов GUI
pytest tests/test_gui_integration.py -v

# Форматирование кода
ruff format src/tgparser tests

# Линтинг
ruff check src/tgparser tests
```

## Сборка standalone-приложения

Для сборки в единый исполняемый файл используется PyInstaller:

```bash
# Установить зависимости
pip install -e ".[dev]"

# Собрать one-file executable
python bin/build_standalone.py

# Собрать one-directory bundle
python bin/build_standalone.py --onedir
```

Готовый исполняемый файл будет в папке `dist/`.

## Планы

- [x] Авторизация (Web + MTProto)
- [x] Парсинг открытых каналов (MTProto)
- [x] Парсинг закрытых каналов (Web)
- [x] Обход защиты от копирования
- [x] Вывод (JSON, CSV, TXT, SQLite)
- [x] Инкрементальный парсинг
- [ ] Поддержка Telegram Premium (MTProto)
- [ ] Парсинг комментариев
- [x] **GUI-интерфейс** (Фаза 7) — план в [docs/roadmap.md](docs/roadmap.md):
- [x] TUI (Textual) — текстовый графический интерфейс реализован
- [x] Окна: авторизация, парсинг, результаты/экспорт
- [x] Прогресс-бар и лог в реальном времени
- [x] Интеграция с существующими модулями
- [x] Тесты (smoke + интеграционные) и сборка (PyInstaller)

Полный roadmap: [docs/roadmap.md](docs/roadmap.md)

---

## Лицензия

Проект распространяется под лицензией MIT. Подробнее — в файле [LICENSE](LICENSE).
