# Changelog

## v0.1.0 (2025-07-16)

Первый стабильный релиз. Все базовые возможности реализованы.

### Added

- Web-авторизация через QR-код (Playwright) с сохранением сессии
- MTProto-авторизация для открытых каналов (Telethon)
- Парсинг открытых каналов через MTProto API
- Парсинг закрытых каналов через web-версию Telegram (Playwright + BeautifulSoup)
- Обход защиты от копирования (CSS `user-select: none`, блокировка контекстного меню)
- Вывод данных: JSON, CSV, plain-text, SQLite
- Инкрементальный парсинг (только новые сообщения)
- CLI-интерфейс: `auth`, `parse open`, `parse closed`, `export`
- Обработка ошибок: retry при неудачном QR, FloodWait, таймауты
- 123 автоматических теста
- Документация: README, Roadmap, Product spec, Tech spec
