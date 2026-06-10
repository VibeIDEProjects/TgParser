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
git clone https://github.com/VibeIDEProjects/TgParser.git
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
# Установка
pip install tgparser-cli  # dist-имя: tgparser_cli

# Обновление
pip install --upgrade tgparser-cli

# Установить Playwright браузеры (требуется для web-парсера)
playwright install chromium
```

> **💡 После установки через pip** может потребоваться добавить папку `Scripts` в `PATH`, чтобы команда `tgparser` была доступна из любого терминала.
>
> **Windows:**
> 1. Найдите путь: обычно это `%APPDATA%\Python\Python<версия>\Scripts` (например, `%APPDATA%\Python\Python314\Scripts`)
> 2. Добавьте его в PATH через PowerShell (от администратора):
>    ```powershell
>    [Environment]::SetEnvironmentVariable("Path", $env:Path + ";$env:APPDATA\Python\Python314\Scripts", "User")
>    ```
>    Или вручную: **Системные свойства → Переменные среды** → добавить путь в `Path`.
>
> **Linux / macOS:**
> 1. Путь обычно: `~/.local/bin`
> 2. Добавьте в `~/.bashrc` (или `~/.zshrc`):
>    ```bash
>    export PATH="$HOME/.local/bin:$PATH"
>    source ~/.bashrc
>    ```
>
> **Автоматическая настройка:**
> Вместо ручного добавления можно воспользоваться встроенной командой:
> ```bash
> tgparser init    # проверит PATH и предложит добавить
> ```
>
> Проверить, что `tgparser` доступен:
> ```bash
> tgparser --help
> ```

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

#### Пути по умолчанию

Если в `config.yaml` ничего не задано:

| Назначение  | Linux / macOS      | Windows                                |
|-------------|--------------------|----------------------------------------|
| Сессии      | `~/.tgparser/sessions/` | `%USERPROFILE%\.tgparser\sessions\` |
| Экспорт     | `~/.tgparser/output/`   | `%USERPROFILE%\.tgparser\output\`   |

Папки создаются автоматически при первом запуске. Абсолютный путь в
`config.yaml` (`~/results`, `C:/myresults`) поддерживается — `~` раскрывается
в домашнюю директорию. Если указать относительный путь, не начинающийся с
`data/`, он будет интерпретирован относительно `~/.tgparser/`.

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
# Кросс-платформенные лаунчеры (рекомендуемый способ)
./bin/run_gui.sh        # Linux / macOS
.\bin\run_gui.bat     # Windows
python bin/run_gui.py   # универсальный

# Или, если установлено через pip:
tgparser gui
python -m tgparser.gui
```

GUI предоставляет удобный интерфейс для:
- Авторизации (web и MTProto)
- Парсинга каналов с настройками
- Просмотра и экспорта результатов
- **Просмотра файлов в `output_dir`** через встроенный проводник
  (дерево слева, превью справа) — кнопка **Browse Output**
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
TgParser/
├── src/tgparser/            # Исходный код
│   ├── auth/                # Авторизация (web, mtproto)
│   ├── parsers/             # Парсеры (mtproto_parser, web_parser)
│   ├── storage/             # Сохранение (JSON, CSV, TXT, Markdown, SQLite)
│   ├── models/              # Модели данных (Message)
│   ├── gui/                 # TUI на базе Textual
│   │   ├── screens/         # MainScreen, AuthScreen, ParseScreen,
│   │   │                    #   ResultScreen, FilesScreen, PreviewScreen
│   │   ├── app.py           # TgParserApp
│   │   └── _win32_hash_patch.py
│   ├── cli.py               # CLI (Click)
│   ├── config.py            # Загрузка конфигурации
│   └── utils.py             # Вспомогательные функции
├── tests/                   # pytest (193+ теста)
├── bin/                     # Утилиты сборки / запуска
│   ├── run_gui.{bat,py,sh}  # Лаунчеры GUI
│   ├── build_standalone.py  # PyInstaller-сборка
│   └── publish_to_pypi.py   # Локальная публикация в PyPI/TestPyPI
├── scripts/                 # Диагностические скрипты (см. scripts/README.md)
├── data/
│   ├── output/              # Результаты парсинга (JSON/CSV/MD)
│   └── sessions/            # Сохранённые сессии
├── logs/                    # Runtime-логи (только .gitkeep в репо)
├── docs/                    # Документация (roadmap, specs)
├── .github/workflows/       # CI: ci.yml, publish.yml
├── config.yaml              # Конфигурация (опционально)
├── .env.example             # Шаблон секретов (не заполняйте!)
├── .env                     # Реальные секреты (в .gitignore!)
├── pyproject.toml           # Настройки проекта
└── README.md                # Этот файл
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

## Утилиты в `bin/`

В `bin/` лежат **кросс-платформенные** скрипты, которые не
входят в сам пакет, но нужны при разработке и сборке.

| Скрипт | Назначение |
|---|---|
| `bin/run_gui.bat` | Windows-лаунчер GUI |
| `bin/run_gui.sh` | Linux/macOS-лаунчер GUI |
| `bin/run_gui.py` | Универсальный Python-лаунчер GUI |
| `bin/build_standalone.py` | Сборка standalone `.exe` через PyInstaller |
| `bin/publish_to_pypi.py` | Сборка + публикация в PyPI / TestPyPI |

### `bin/publish_to_pypi.py` — публикация пакета

Скрипт оборачивает `python -m build` + `twine upload` в одну
команду и поддерживает dry-run.

```bash
# Что попадёт в пакет (сборка, без upload)
python bin/publish_to_pypi.py

# Сначала прогон на TestPyPI
python bin/publish_to_pypi.py --test --upload

# Реальная публикация в PyPI
python bin/publish_to_pypi.py --upload
```

**Требования:**

1. `pip install build twine`
2. PyPI-токен — одним из способов:
   - `~/.pypirc`:
     ```ini
     [pypi]
     username = __token__
     password = pypi-XXXXXXXXXXXXXXXXXXXX
     ```
   - ENV-переменные `TWINE_USERNAME` / `TWINE_PASSWORD`
   - `keyring`

> ⚠️ **Не светите PyPI-токен в публичных ответах/репо.** Добавьте
> `~/.pypirc` в `.gitignore` (уже там) и используйте переменные
> окружения в CI.

### Релиз через GitHub Actions (рекомендуется)

В репозитории уже настроен workflow
[`.github/workflows/publish.yml`](.github/workflows/publish.yml),
который автоматически публикует пакет в PyPI при создании
**GitHub Release**:

1. `git tag v0.3.0 && git push origin v0.3.0` — отправляем тег.
2. На GitHub: **Releases → Draft a new release → выбрать тег**.
3. Workflow `Publish to PyPI` подхватывает релиз и публикует.

`PYPI_TOKEN` хранится в **Settings → Secrets → Actions**.

---

## Папка `scripts/`

Содержит **одноразовые отладочные** скрипты (`.py`), которые
запускаются вручную во время разработки. **Не** являются
runtime-кодом приложения и **не** автотестами.

Подробности и правило «логи → `../logs/`» — в
[`scripts/README.md`](scripts/README.md).

---

## Управление логами

`logs/` — runtime-логи приложения (например,
`closed_parse.log` — лог парсинга закрытого канала).

* **В репозитории** хранится только `logs/.gitkeep` (маркер
  папки).
* **Все** `.log`/`.txt` файлы внутри `logs/` автоматически
  игнорируются через `.gitignore` (`logs/*` + `!logs/.gitkeep`).
* Вывод диагностических скриптов из `scripts/` тоже
  перенаправляйте в `../logs/`.

Аналогично `data/output/` хранит только `.gitkeep`, а реальные
результаты парсинга (`.json`/`.csv`/`.md`) остаются локально.

---

## Секреты и `.env`

`.env` **никогда** не коммитится (в `.gitignore:1`). Шаблон —
[`.env.example`](.env.example):

```dotenv
# TgParser secrets — copy to .env and fill in
# Do NOT commit .env!

# MTProto API credentials from https://my.telegram.org/apps
TG_API_ID=
TG_API_HASH=
TG_PHONE=
```

> 🔒 **API Hash и номер телефона — это секреты.** Никогда не
> публикуйте их в issues, PR-описаниях, логах или скриншотах.
> Если они утекли — отзовите их в **my.telegram.org/apps** и
> пересоздайте.

---

## Лицензия

Проект распространяется под лицензией MIT. Подробнее — в файле [LICENSE](LICENSE).
