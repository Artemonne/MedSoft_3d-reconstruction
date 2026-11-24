# IMPLEMENTATION_PROGRESS

Последнее обновление: 24.11.2026.

## Текущий этап

Этап 4 — доступная автоматическая и синтетическая проверка завершена; ожидаются внешние данные для ручной приёмки.

## Реализовано

- Создана ветка `feat/lab5-implementation`.
- Добавлены `pyproject.toml`, `requirements.txt`, `.gitignore` и src-layout.
- Определены GUI-независимые модели CT-объёма, геометрии, сегментации и сетки.
- Определены доменные исключения для понятных ошибок.
- Реализовано обнаружение CT DICOM без привязки к расширению, группировка по SeriesInstanceUID и FrameOfReferenceUID.
- Реализована строгая геометрическая сортировка по IOP/IPP с отказом для дубликатов, нерегулярного шага и gantry shear.
- Реализовано посрезовое преобразование stored values в подтверждённые HU и исключение Pixel Padding.
- Реализовано формирование float32 HU-объёма и безопасное чтение необязательных метаданных.
- Реализованы threshold и 6-связный Region Growing с локальным перепадом HU.
- Реализован Marching Cubes с padding и преобразованием вершин в физические LPS-координаты.
- Реализованы сглаживание, decimation, изолированный mesh repair и STL-экспорт активной сетки.
- Реализован русский PySide6 GUI: выбор папки/серии, метаданные, 2D-срез и seed, 3D-маска/поверхность, все операции и метрики.
- Фоновые расчёты используют QThreadPool; устаревшие результаты отбрасываются, mesh инвалидируется при новой сегментации.

## Фактически проверено

- Исходное рабочее дерево было чистым; этап 0 содержится в `7fbab40`.
- Доступен Python 3.12.9 x64.
- Полный стек установлен в `.venv`; `pip check`: `No broken requirements found`.
- Offscreen `QApplication` и `QtInteractor` успешно созданы и закрыты.
- 34 автоматических теста проходят.
- Видимое окно, volume rendering и surface rendering запускались на синтетическом объёме и штатно закрылись с кодом 0.
- STL повторно прочитан PyVista; грани и физические bounds совпали.
- Проверены RLE Lossless decode, разделение одинакового SeriesUID по FrameOfReferenceUID, лимит объёма и timeout repair.
- Region Growing реагирует на отмену; результаты остальных отменённых фоновых задач отбрасываются.
- `docs/TEST_RESULTS.md` содержит трассировку R01–R14 и T01–T30 с PASS/PARTIAL/NOT TESTED.

## Не проверено

- Загрузка реальной обезличенной DICOM-серии: данных в проекте нет.
- Внешний просмотр STL в Blender/MeshLab/3D Slicer.
- Полный ручной сценарий выбора файлов мышью и вращения модели человеком.
- Реальные DICOM-серии отсутствуют в проекте.

## Оставшиеся ошибки и риски

- Форматы реальных файлов преподавателя неизвестны.
- Enhanced CT/multi-frame, нерегулярный шаг и gantry tilt не поддерживаются; приложение должно объяснить отказ.
- Headless Qt не имеет OpenGL; автоматический GUI-тест проверяет данные сцены без render, а реальный Windows render проверен отдельными smoke-запусками.

## Последний успешный Git-коммит

`baef4ac test: document final verification results`

## Следующая конкретная задача

Перед защитой вручную прогнать две обезличенные реальные CT-серии и открыть экспорт в Blender/MeshLab/3D Slicer; дописать факты в TEST_RESULTS.

## Команды

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e ".[test]"
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m ct_reconstruction
```

