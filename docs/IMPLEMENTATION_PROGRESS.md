# IMPLEMENTATION_PROGRESS

Последнее обновление: 24.11.2026.

## Текущий этап

Этап 1 — настройка проекта и реализация обязательной части.

## Реализовано

- Создана ветка `feat/lab5-implementation`.
- Добавлены `pyproject.toml`, `requirements.txt`, `.gitignore` и src-layout.
- Определены GUI-независимые модели CT-объёма, геометрии, сегментации и сетки.
- Определены доменные исключения для понятных ошибок.
- Реализовано обнаружение CT DICOM без привязки к расширению, группировка по SeriesInstanceUID и FrameOfReferenceUID.
- Реализована строгая геометрическая сортировка по IOP/IPP с отказом для дубликатов, нерегулярного шага и gantry shear.
- Реализовано посрезовое преобразование stored values в подтверждённые HU и исключение Pixel Padding.
- Реализовано формирование float32 HU-объёма и безопасное чтение необязательных метаданных.

## Фактически проверено

- Исходное рабочее дерево было чистым; этап 0 содержится в `7fbab40`.
- Доступен Python 3.12.9 x64.
- Полный стек установлен в `.venv`; `pip check`: `No broken requirements found`.
- Offscreen `QApplication` и `QtInteractor` успешно созданы и закрыты.
- 14 тестов DICOM/HU/геометрии проходят.

## Не проверено

- Реальный показ GUI и ручная загрузка DICOM.
- Segmentation, mesh и экспорт.
- Реальные DICOM-серии отсутствуют в проекте.

## Оставшиеся ошибки и риски

- Форматы реальных файлов преподавателя неизвестны.

## Последний успешный Git-коммит

`d9b863b chore: initialize Python desktop application`

## Следующая конкретная задача

Реализовать threshold и Region Growing, затем Marching Cubes с физическими координатами.

## Команды

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e ".[test]"
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m ct_reconstruction
```

