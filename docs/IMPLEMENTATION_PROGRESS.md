# Ход реализации

Последнее обновление: 24.11.2026.

## Текущий этап

Финальная доработка завершена. Реализация соответствует всем пунктам оригинальной лабораторной на заявленном профиле classic single-frame CT. Осталась только ручная репетиция по `docs/DEFENSE_CHECKLIST.md`.

## Реализовано

- GUI-загрузка папки, обнаружение и выбор CT-серии без смешивания Series/Frame of Reference.
- Двухпроходное bounded-memory чтение, геометрическая сортировка IOP/IPP и физическая LPS-геометрия.
- Посрезовое преобразование stored values в подтверждённые HU с исключением Pixel Padding.
- Threshold и 6-связный Region Growing от выбранного кликом seed с регулируемым локальным перепадом HU.
- 3D binary mask и настоящий Marching Cubes с физическими координатами.
- Smoothing, topology-safe decimation и фактический repair с метриками до/после.
- Экспорт именно показанной active mesh в binary STL.
- Фоновые операции, защита от stale results, прогресс, отмена Region Growing и безопасное закрытие окна.
- Scrollable GUI, понятные метаданные/ошибки и VTK TrackballCamera.

## Фактически проверено

- Чистая установка Python 3.12: `pip check` без конфликтов; импорт из другого каталога успешен.
- Финальный прогон рабочего окружения: `52 passed in 5.09s`.
- Видимый запуск: `APP_VISIBLE True`, окно 1400×860.
- Qt mouse click выбирает правильную координату seed; folder-picker проходит полный background workflow.
- Две обезличенные серии TCIA RIDER Pilot из разных исследований: каждая 33×512×512.
- На обеих сериях повторены load, HU threshold, Region Growing, Marching Cubes, smoothing, decimation и независимый STL parse.
- На серии `…132604` repair: components `4682→1`, non-manifold `57→9`.
- Финальный STL открыт Paint 3D, окно `Responding=True`; triangle count и bounds независимо совпали.
- Peak RSS ранее измеренного полного pipeline: 569,4 MiB.

## Git

- Корень и ветка проверены: `feat/lab5-implementation`.
- В индексе нет `.venv`, DICOM, STL, caches или локальных настроек.
- При диагностике 18 847 локальных файлов корректно игнорировались; 18 732 из них принадлежат сохранённому `.venv`. После двух финальных STL — 18 849 ignored, 0 посторонних untracked.
- DICOM и рабочее окружение сохранены локально, `git push` не выполнялся.

## Известные ограничения вне рубрикатора

- Enhanced CT/multi-frame, gantry tilt/shear и irregular spacing не ресэмплируются, а отклоняются с объяснением.
- Реальные JPEG/JPEG-LS/JPEG 2000 серии не испытаны; uncompressed и RLE покрыты.
- Стресс-тест около лимита 300 млн voxels не выполнялся.
- Системный Windows automation helper недоступен, поэтому человеку нужно повторить rotate/zoom/pan и визуальный просмотр STL перед защитой.

## Команды

```powershell
.\.venv\Scripts\python.exe -m pip check
$env:QT_API = "pyside6"
$env:QT_QPA_PLATFORM = "offscreen"
.\.venv\Scripts\python.exe -m pytest -q
Remove-Item Env:QT_QPA_PLATFORM -ErrorAction SilentlyContinue
.\.venv\Scripts\python.exe -m ct_reconstruction
```
