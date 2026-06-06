# TgParser — Roadmap

<!-- vibeVersion: 1.0.0 -->
<!-- Последнее обновление: 2025-07-16 (Фаза 6 завершена) -->

## Фаза 0: Подготовка проекта

- [x] Идея зафиксирована в `docs/idea.md`
- [x] Создан роадмап (`docs/roadmap.md`)
- [x] Создана продуктовая спецификация (`docs/product.md`)
- [x] Создана техническая спецификация (`docs/tech.md`)
- [x] Инициализация проекта: `pyproject.toml`, виртуальное окружение, линтеры
- [x] Настройка `.env` для секретов — `.env.example` создан, скопировать в `.env` и заполнить

## Фаза 1: Авторизация

- [x] Web-авторизация через QR-код (Playwright) — `src/tgparser/auth/web_auth.py`
- [x] Сохранение сессии в файл (переиспользование) — `data/sessions/web_session.json` (cookies + localStorage)
- [x] MTProto-авторизация для открытых каналов (Telethon) — `src/tgparser/auth/mtproto_auth.py`
- [x] Обработка ошибок авторизации (неверный QR → retry ×3, таймаут, закрытие браузера)
- [x] CLI-команда: `tgparser auth` (с опциями `--type`, `--force`)
- [x] Тесты на auth-модуль — 11 тестов в `tests/test_web_auth.py`

## Фаза 2: Парсер открытых каналов (MTProto API)

- [x] Получение списка сообщений канала через Telethon
- [x] Извлечение: текст, медиа (ссылки), дата, автор, реакции
- [x] Пагинация (offset_id, limit)
- [x] Фильтрация по дате
- [x] Обработка rate-limit (FloodWaitError)
- [x] CLI-команда: `tgparser parse open @channel`
- [x] Тесты на парсер открытых каналов

## Фаза 3: Парсер закрытых каналов (Web HTML)

- [x] Открытие web-версии Telegram в headful-браузере (Playwright) — `web_parser.py`
- [x] Загрузка существующей сессии (cookies/localStorage) — через `WebAuth.restore_session`
- [x] Навигация к каналу по ссылке `t.me/...` — `_navigate_to_channel` + `_extract_hash`
- [x] Парсинг HTML сообщений (BeautifulSoup / DOM API)
- [x] Извлечение: текст, медиа (URL), дата, автор — `_extract_text`, `_extract_media_urls`, etc.
- [x] Скроллинг для подгрузки истории — `_scroll_and_collect`, `_scroll_up`
	- [x] CLI-команда: `tgparser parse closed <url>`
- [x] Тесты на парсер закрытых каналов — 40 тестов в `tests/test_web_parser.py`

## Фаза 4: Обход защиты от копирования

- [x] Детекция запрета копирования (CSS `user-select: none`, блокировка контекстного меню)
- [x] Снятие защиты через инъекцию JS (`user-select: text`, отмена `oncopy`) — `_bypass_copy_protection`
- [x] Извлечение текста через `textContent` напрямую из DOM — реализовано в `_extract_text`
- [x] Обработка блокировки правой кнопки мыши — `COPY_PROTECTION_JS`
- [x] Тесты на обход защиты — покрыты существующими тестами

## Фаза 5: Вывод и хранение

- [x] Вывод в JSON
- [x] Вывод в CSV
- [x] Вывод в plain-text
- [x] Сохранение в SQLite (опционально)
- [x] Инкрементальный парсинг (только новые сообщения)
- [x] CLI-команда: `tgparser export`

## Фаза 6: Релиз и документация

- [x] `README.md` с примерами использования
- [x] Проверка на Windows/Linux
- [x] Релиз v0.1.0

---

## Легенда

- `[x]` — выполнено
- `[ ]` — запланировано
- `~[ ]~` — отменено/неактуально
