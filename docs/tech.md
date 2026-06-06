# TgParser — Техническая спецификация (TECH.md)

<!-- vibeVersion: 1.0.0 -->

## 1. Технологический стек

| Компонент | Выбор | Обоснование |
|-----------|-------|-------------|
| Язык | **Python 3.11+** | Богатая экосистема для парсинга и работы с Telegram API |
| MTProto-клиент | **Telethon** | Стабильный, асинхронный, лучшая поддержка каналов |
| Браузерная автоматизация | **Playwright** (sync API) | Надёжнее Selenium, умеет управлять Chromium |
| HTML-парсинг | **BeautifulSoup4** + lxml | Де-факто стандарт, устойчив к битому HTML |
| CLI | **Click** или **Typer** | Удобный фреймворк для CLI с автодокументированием |
| Конфигурация | **python-dotenv** + YAML | `.env` для секретов, `config.yaml` для настроек |
| Хранение данных | **SQLite** (опционально) через sqlite3 из stdlib | Нулевые зависимости для базового случая |
| Тестирование | **pytest** + pytest-asyncio | Стандарт индустрии |
| Линтинг | **ruff** | Быстрый, заменяет flake8 + isort + black |

## 2. Архитектура

```
tgparser/
├── cli.py                  # Точка входа, команды Click/Typer
├── auth/
│   ├── __init__.py
│   ├── web_auth.py         # QR-авторизация через Playwright
│   └── mtproto_auth.py     # MTProto-авторизация через Telethon
├── parsers/
│   ├── __init__.py
│   ├── open_channel.py     # Парсер открытых каналов (Telethon)
│   ├── closed_channel.py   # Парсер закрытых каналов (Playwright + BS4)
│   └── anti_copy.py        # Обход запрета копирования
├── models/
│   ├── __init__.py
│   └── message.py          # Модель Message (dataclass)
├── storage/
│   ├── __init__.py
│   ├── json_writer.py
│   ├── csv_writer.py
│   └── sqlite_writer.py
├── config.py               # Загрузка конфигурации
└── utils.py                # Логгирование, retry, helpers
```

## 3. Модель данных

```python
@dataclass
class Message:
    id: int                    # ID сообщения в канале
    channel: str               # @username или invite-ссылка
    date: datetime             # UTC
    author: str | None         # Подпись автора (если есть)
    text: str                  # Текст сообщения
    media_urls: list[str]      # Ссылки на медиа (фото, видео, документы)
    reactions: dict | None     # Реакции (эмодзи → кол-во)
    is_forwarded: bool         # Переслано?
    raw_source: str            # "mtproto" | "web"
```

## 4. Поток авторизации (web QR)

```
Пользователь → tgparser auth
  → Playwright запускает Chromium (headful)
  → Открывает https://web.telegram.org/
  → Ждёт появления QR-кода (<canvas> с qr-кодом)
  → Показывает QR в окне браузера
  → Пользователь сканирует телефоном
  → Ждёт редиректа на /chat
  → Сохраняет cookies + localStorage в data/session.json
  → Браузер закрывается
```

**Состав сессии:**
- Cookies (все домены `.telegram.org`)
- localStorage (ключи `tg_*`, `user_auth`)
- Опционально: скриншот QR для headless-режима (идея: сохранить QR как PNG и показать путь)

## 5. Парсинг открытых каналов

```python
# open_channel.py
async def parse_open_channel(client: TelegramClient, channel: str, limit: int = 100, offset_date: datetime | None = None) -> list[Message]:
    # 1. Получить entity канала
    # 2. iter_messages() с offset_date и limit
    # 3. Преобразовать Message (Telethon) → Message (наша модель)
    # 4. Обработать SleepOnRatelimitError через retry
```

**Обработка медиа:**
- Фото → `message.photo` → получаем URL через `client.download_media(bytes, file=bytes)` или сохраняем file_id
- Документы → аналогично, сохраняем `file_name` и `mime_type`

## 6. Парсинг закрытых каналов

### 6.1. Стратегия

1. Playwright открывает web.telegram.org с сохранённой сессией
2. Переходит по invite-ссылке канала
3. Ждёт загрузки списка сообщений (селектор `.messages-container` или аналог)
4. Скроллит вверх для подгрузки истории (эмуляция `wheel` или `scrollTo`)
5. На каждом шаге извлекает DOM-узлы сообщений

### 6.2. Селекторы (актуальные на июнь 2026)

Telegram Web K (последняя версия) использует:
- Контейнер сообщений: `.MessageList` (блочный элемент с `overflow-y: auto`)
- Одно сообщение: `.Message` или `[data-message-id]`
- Текст: `.text-content` или `.Message .content .text`
- Автор: `.Message .sender-name`
- Дата: `.Message .time` или `[data-timestamp]`

> **Примечание:** селекторы нестабильны — нужен fallback на несколько вариантов + логгирование при mismatches.

### 6.3. Обход запрета копирования

Защита реализуется через:
- `user-select: none` в CSS
- Перехват событий `copy`, `cut`, `contextmenu`
- `oncopy="return false"`

**Стратегия обхода (в порядке применения):**

```python
# anti_copy.py
def bypass_copy_protection(page: Page):
    # 1. Сброс CSS
    page.evaluate("""
        document.querySelectorAll('*').forEach(el => {
            el.style.userSelect = 'text';
            el.style.webkitUserSelect = 'text';
        });
    """)
    
    # 2. Снятие обработчиков
    page.evaluate("""
        document.querySelectorAll('*').forEach(el => {
            el.oncopy = null;
            el.oncut = null;
            el.oncontextmenu = null;
        });
    """)
    
    # 3. Извлечение текста напрямую из DOM
    # Вместо копирования — читаем textContent каждого .Message
```

### 6.4. Скроллинг

```python
def scroll_and_extract(page: Page, max_messages: int) -> list[Message]:
    messages = []
    last_count = 0
    no_new_count = 0
    
    while len(messages) < max_messages:
        # Скроллим вверх
        page.evaluate("document.querySelector('.MessageList').scrollTop = 0")
        page.wait_for_timeout(1500)  # Ждём подгрузки
        
        # Извлекаем
        new_messages = extract_visible_messages(page)
        
        if len(new_messages) == last_count:
            no_new_count += 1
            if no_new_count >= 3:
                break  # Больше нет истории
        else:
            no_new_count = 0
        
        last_count = len(new_messages)
        messages = new_messages
    
    return messages[:max_messages]
```

## 7. Конфигурация

### `.env` (секреты, не коммитить)
```
TG_API_ID=12345678
TG_API_HASH=abcdef1234567890abcdef1234567890
TG_PHONE=+79001234567
```

### `config.yaml` (настройки, коммитить)
```yaml
session_dir: data/sessions/
output_dir: data/output/

defaults:
  message_limit: 100
  output_format: json
  
parsing:
  scroll_delay_ms: 1500
  max_scroll_attempts: 50
  
browser:
  headless: false        # false для QR-авторизации, true для фонового парсинга
  slow_mo: 100           # задержка между действиями (ms)
```

## 8. Обработка ошибок

| Ошибка | Стратегия |
|--------|-----------|
| `FloodWaitError` | Sleep N секунд, retry |
| `SessionExpiredError` | Сообщение: «сессия протухла, выполните `tgparser auth`» |
| `ChannelPrivateError` | Сообщение: «нет доступа к каналу» |
| `NetworkError` | Exponential backoff: 1s, 2s, 4s, 8s, max 3 retry |
| `TimeoutError` (Playwright) | Увеличить таймаут, retry 2 раза |
| HTML селектор не найден | Логгировать WARNING, попробовать fallback-селектор |
| Капча / Cloudflare | Сообщение: «обнаружена капча, требуется ручное вмешательство», открыть headful |

## 9. План тестирования

### Модульные тесты
- `test_anti_copy.py` — инъекция JS с разными комбинациями защиты
- `test_message_model.py` — сериализация/десериализация Message
- `test_config.py` — загрузка конфигурации с дефолтами

### Интеграционные тесты
- `test_auth_flow.py` — мок сессии, проверка логики (без реального браузера)
- `test_open_channel.py` — парсинг тестового канала (с моком Telethon)
- `test_closed_channel.py` — парсинг сохранённого HTML

### E2E тесты (ручные)
- Реальная авторизация через QR
- Парсинг реального открытого канала
- Парсинг реального закрытого канала с защитой от копирования

## 10. Безопасность

- **API ID/Hash не коммитятся** — `.env` в `.gitignore`
- **Сессии в `data/sessions/`** — директория в `.gitignore`
- **Нет телеметрии**, нет внешних запросов кроме `api.telegram.org` и `web.telegram.org`
- **Локальное хранение:** все данные — на машине пользователя
- **Playwright в headful-режиме только для авторизации** — минимизация раскрытия UI

## 11. Зависимости

```toml
[project]
dependencies = [
    "telethon>=1.35",
    "playwright>=1.45",
    "beautifulsoup4>=4.12",
    "lxml>=5.2",
    "click>=8.1",
    "python-dotenv>=1.0",
    "pyyaml>=6.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.2",
    "pytest-asyncio>=0.23",
    "ruff>=0.4",
]
```
