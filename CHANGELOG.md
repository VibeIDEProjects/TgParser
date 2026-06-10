# Changelog

## v0.3.0 (2026-06-10)

GUI overhaul, Markdown rendering, file browser.

### Added

- **FilesScreen** (новый экран в GUI): дерево каталогов слева,
  превью файла справа. Понимает Markdown / JSON (с подсветкой
  синтаксиса) / CSV (как таблицу) / text / hex-дамп / картинки.
  Кнопка **Browse Output** в Quick Actions открывает его.
- **`bin/run_gui.{bat,py,sh}`** — кросс-платформенные лаунчеры
  для запуска GUI без `python -m tgparser.gui`.
- **`bin/publish_to_pypi.py`** — утилита для сборки и
  публикации пакета в PyPI / TestPyPI (см. раздел README).
- **GitHub Actions: `.github/workflows/publish.yml`** —
  автоматическая публикация в PyPI при создании GitHub Release.
- **Markdown-экспорт** (`writer.py`): вставляет жёсткие переносы
  (`  ` в конце строки) перед каждым `
`, чтобы многострочные
  сообщения рендерились корректно в любом Markdown-вьюере.
- **FilesScreen** обрабатывает несколько файлов подряд без
  ``DuplicateIds`` (pre-view container `VerticalScroll`).
- **`scripts/`** — теперь часть репозитория: README объясняет,
  для чего папка и куда писать логи (в `../logs/`, а не сюда).
- `tests/test_gui_smoke.py` — регрессионные тесты на
  `FilesScreen` (multi-select, layout left/right, scroll).
- `tests/test_input_hash.py`, `tests/test_input_hash_real.py`,
  `tests/test_utils.py`, `tests/test_win32_hash_patch.py`.

### Changed

- **`tgparser.gui`** — `MainScreen`: кнопки `View Results` и
  `Browse Output` открывают экран даже без выбранного канала
  (fallback на первый канал из таблицы).
- **`result_screen.py:_load_messages`** — ищет сообщения в трёх
  layouts: `combined <channel>_all.json`, timestamped
  `<channel>_<YYYYMMDD_HHMMSS>.json`, legacy
  `<channel>/<ts>.json`. Использует `#status-message` Static
  вместо несуществующего `_render_status()`.
- **`main_screen.py:add_channel`** — устойчив к отсутствию
  приватного `_row_locations` API; всегда передаёт `key=` в
  `DataTable.add_column`.
- **`.gitignore`** — `logs/*` + `!logs/.gitkeep`,
  `scripts/README.md` явно отслеживается, `.vibe/.window-lock.json`
  untrack'нут (VibeIDE runtime-файл, не должен коммититься).

### Fixed

- **`writer.py`** — hard breaks в Markdown-экспорте (были
  превращены в один абзац).
- **`MainScreen.action_export`** — корректно работает без
  выбранного канала (раньше выдавал `Select a channel first`
  на `btn-view` без явного выбора).
- **`FilesScreen`** — `query_one("#preview-content")` больше
  не падает на `WrongType`, когда активен Markdown/DataTable.

