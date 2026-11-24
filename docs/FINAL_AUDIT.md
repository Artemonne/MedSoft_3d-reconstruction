# Финальный независимый аудит лабораторной № 5

Дата: 24.11.2026

Ветка: `feat/lab5-implementation`

Итоговая оценка аудитора: **27/30**

Вердикт: **готово к защите с оговорёнными ограничениями**

## Объём аудита

Полностью изучены оригинальное задание `sources/Лабораторная_5.pdf` (2 страницы), лекция № 10 `sources/10_3D_реконструкция_по_КТ.pdf` (19 страниц), `AGENTS.md`, требования, архитектура, тест-план, конспект лекции, Codex prompts, README и весь прикладной/тестовый код. PDF дополнительно рендерились постранично для визуальной проверки, а не оценивались только по извлечённому тексту.

Проверка проведена независимо от прежних заявлений проекта. Базовый результат был 35 тестов; после аудита — 51 тест и два реальных исследования.

## Найденные проблемы и исправления

| Критичность | Реальная проблема | Исправление и проверка |
|---|---|---|
| Высокая | Загрузка сначала декодировала все срезы и складывала промежуточные массивы. На больших CT это резко увеличивало peak RAM и могло убить процесс до доменной ошибки. | Двухпроходная загрузка: сначала metadata-only геометрия, затем по одному срезу в заранее выделенные `float32` HU и validity arrays. Добавлены voxel/available-memory guards и тест отсутствия накопления pixel arrays. |
| Высокая | HU могли считаться корректными для DERIVED/non-ORIGINAL данных и неподтверждённых единиц rescale; переполнение `float32` не отлавливалось. | Для reconstruction требуется ORIGINAL CT и HU/пустой `RescaleType`; нечисловые/небезопасные rescale и overflow отклоняются объяснимой ошибкой. |
| Высокая | Фоновые результаты могли прийти после изменения порога/seed и снова включить экспорт устаревшей сетки; часть тяжёлых metrics/export выполнялась в GUI-потоке. | Немедленная инвалидизация segmentation/mesh, generation tokens, отмена debounce, export/metrics в workers, безопасное закрытие окна, блокировка конфликтующих controls. |
| Высокая | Mesh repair мог объявить успех без уменьшения дефектов. Топологическое ухудшение не контролировалось. | Repair успешен только при фактическом уменьшении boundary/non-manifold/components; рост любого дефекта запрещён, no-op выдаёт ошибку, метрики до/после показываются. |
| Высокая | `decimate_pro(preserve_topology=True)` на реальных MC-сетках умножал non-manifold рёбра; прежняя логика либо портила mesh, либо полностью запрещала обработку уже дефектной сетки. | Non-manifold компоненты не трогаются; достаточно большие closed-manifold компоненты упрощаются отдельно с адаптивным reduction. После операции boundary/components должны совпасть, non-manifold не может вырасти. UI показывает фактический, а не обещанный процент. |
| Средняя | Объём вычислялся и показывался для закрытой, но non-manifold сетки, где он неоднозначен. | `volume_mm3=None`, если есть boundary или non-manifold edges. |
| Средняя | Region Growing на каждом шаге делал полный `mask.sum()`, а очередь хранила Python tuples; это ухудшало время/RAM на больших областях. | Очередь хранит flat integer indices, progress использует счётчик принятых voxels; семантика 6-связности и локального перепада сохранена. |
| Средняя | Marching Cubes создавал лишнюю полную `uint8` копию маски. | Padding выполняется как `bool`; float conversion оставлена внутреннему алгоритму только в необходимом объёме. |
| Средняя | Windows VTK-виджет реально отображал чёрный/дублированный framebuffer при MSAA/shaded volume; это не ловили offscreen-тесты. | MSAA отключён для embedded renderer, volume отображается без проблемного shading, mesh — flat + edges. Проверено видимым OpenGL-запуском. |
| Средняя | Длинные topology metrics обрезались; управление не помещалось по высоте. | Панель помещена в `QScrollArea`, label увеличен и показывает текущие и предыдущие метрики. |
| Средняя | Выбор нескольких серий имел неуникальные подписи; существовал риск выбора не той серии с одинаковым description. | В label добавлен suffix SeriesInstanceUID; Series/Frame of Reference по-прежнему не смешиваются. |
| Средняя | STL проверялся в основном повторным чтением тем же стеком, что могло скрыть симметричную ошибку writer/reader. | Добавлен независимый binary STL parser: размер, число граней, finite coordinates, bounds; отдельно проверены oblique LPS и ориентация normals. |
| Низкая | GUI не показывал Modality, Birth Date и Sex, хотя модель их извлекала; отсутствующие поля могли оцениваться неявно. | Поля добавлены, отсутствие отображается как «Нет данных». |

Намеренно не переписывались корректные модели, DICOM grouping, формула LPS-преобразования, threshold и базовая архитектура слоёв.

## DICOM, HU и геометрия

Приложение группирует по `(SeriesInstanceUID, FrameOfReferenceUID)`, фильтрует CT/ORIGINAL, сортирует срезы проекцией `ImagePositionPatient` на normal из `ImageOrientationPatient`, проверяет rows/columns, orientation, pixel spacing, регулярность шага и дубликаты позиций. `SliceThickness` не используется как фактический межсрезовый шаг.

HU вычисляются для каждого среза как `stored_pixel * RescaleSlope + RescaleIntercept` в `float32`; padding исключается из segmentation domain. Порог применяется к HU. Геометрия хранит spacing `[slice,row,column]` и DICOM LPS basis; MC-координаты переводятся в физические миллиметры с учётом padding offset и oblique orientation.

Поддерживаемый профиль сознательно ограничен classic single-frame, регулярной ортогональной CT. Enhanced CT, gantry tilt/shear, irregular spacing, отсутствующая достоверная геометрия и неподтверждённые HU отклоняются, а не реконструируются по `InstanceNumber` или `SliceThickness`.

## Region Growing и Marching Cubes

Region Growing использует выбранный seed `(z,y,x)`, 6-связность и локальный критерий `abs(neighbour-current) <= tolerance`; это не глобальная threshold mask. Padding/невалидный seed отклоняется, операция отменяема. Реальный GUI-прогон с seed `(10,307,243)` и tolerance 50 HU дал связную область 566 voxels.

Marching Cubes — настоящий Lewiner MC на binary mask, level 0.5, с padding для замыкания объектов на границе. Получаются triangle faces, физические LPS vertices и outward normals. Пустая маска даёт объяснимую ошибку.

## Mesh processing и STL

Smoothing изменяет координаты, не меняя boundary/component counts и не добавляя non-manifold edges. Decimation действительно уменьшает число треугольников, но для дефектных реальных поверхностей безопасная фактическая редукция может быть меньше целевых 50%; GUI это сообщает. Repair заполняет отверстия до заданного физического размера и по выбору оставляет крупнейшую компоненту; работа native filter изолирована отдельным процессом с timeout.

На реальной серии repair изменил `components 4682 → 1` и `non-manifold 57 → 9`, то есть был фактическим, а не пересчётом normals. Полностью устранять произвольные non-manifold junctions он не обещает.

Экспортируется именно `active_mesh`, показанная в 3D. Binary STL содержит LPS-координаты в миллиметрах; STL сам единицу не хранит. Независимый parser подтвердил triangle count и bounds, Paint 3D открыл файл без ошибки.

## Качество тестов

Исходные 35 тестов давали полезную базу, но переоценивали готовность:

- почти все DICOM были синтетическими и маленькими;
- не было доказательства bounded-memory decode;
- STL round-trip зависел от родственного VTK/PyVista стека;
- repair не обязан был доказать уменьшение дефекта;
- не проверялись existing non-manifold mesh и ухудшение topology после decimation;
- offscreen GUI не обнаруживал Windows OpenGL framebuffer defect;
- отсутствовали реальные исследования и end-to-end GUI pipeline.

Добавлены негативные HU/geometry/memory случаи, независимый STL parser, topology assertions, no-op repair, non-manifold processing, stale worker/state tests и реальные внешние прогоны. Финально: **51 passed in 9.23s** в заново установленном окружении; `pip check` — без конфликтов.

## Реальные публичные данные

Использована официальная обезличенная коллекция [TCIA RIDER Pilot](https://www.cancerimagingarchive.net/collection/rider-pilot/) с двумя разными `StudyInstanceUID`. Политика TCIA описывает [деидентификацию перед публикацией](https://www.cancerimagingarchive.net/submission-and-de-identification-overview/). Загрузка выполнялась локально через [NBIA Search REST API](https://wiki.cancerimagingarchive.net/display/Public/NBIA%2BSearch%2BREST%2BAPI%2BGuide).

Обе серии имеют 33×512×512 voxels; spacing и scalar range независимо совпали с `vtkDICOMImageReader`. Полные численные результаты приведены в `docs/TEST_RESULTS.md`. Датасеты не добавлены в Git.

## Оценка по заданиям

| Задание | Максимум | Оценка | Обоснование |
|---|---:|---:|---|
| Обязательная часть | 15 | **14.0** | Реальные CT, метаданные, HU, geometry, threshold, 3D и background state доказаны. Снято 1.0 за ограниченный classic single-frame профиль и отсутствие физической ручной проверки mouse/file-dialog. |
| Region Growing | 5 | **4.5** | Настоящий seed-based 6-connected алгоритм, tolerance, cancel, реальные данные. Снято 0.5: физический click-to-seed системной мышью не выполнен. |
| Marching Cubes | 3 | **3.0** | Реальная triangle surface, padding, oblique/spacing/LPS/normals и видимый OpenGL подтверждены. |
| Обработка поверхности | 4 | **3.0** | Smoothing, topology-safe decimation и фактический repair работают. Снято 1.0: repair не устраняет все виды non-manifold junctions, а безопасная редукция иногда существенно ниже 50%. |
| STL | 3 | **2.5** | Active mesh, binary parser, VTK round-trip, bounds и открытие Paint 3D подтверждены. Снято 0.5: внешний редактор не использован для визуального измерения/сравнения геометрии. |
| **Итого** | **30** | **27.0** | Высокая готовность, но 30/30 доказательствами не обеспечены. |

## Оставшиеся риски

- Реальные compressed JPEG/JPEG-LS/JPEG 2000 CT не испытаны, хотя decoder dependencies установлены; RLE и uncompressed покрыты тестами.
- Peak RSS 569,4 MiB измерен на 8,65 млн voxels, а не у лимита 300 млн. Лимиты предотвращают очевидный OOM, но worst-case MC topology всё ещё может быть очень тяжёлой.
- Без ресэмплинга не поддерживаются irregular spacing и gantry tilt; это честное ограничение, но может не принять конкретную серию преподавателя.
- Repair уменьшает измеряемые дефекты, но не является универсальным manifold reconstruction algorithm.
- Системная mouse automation была недоступна; rotate/zoom/pan и file picker проверены не физическими событиями ОС.
- Paint 3D открыл STL, но независимый внешний визуальный контроль размера/ориентации не выполнен.

## Готовность к защите

Работа готова демонстрировать основной и дополнительные сценарии. На защите следует заранее иметь одну поддерживаемую classic CT-серию и показать: выбор серии, изменение HU с изменением маски, seed/tolerance Region Growing, MC, метрики до/после обработки, фактический процент decimation, export active mesh и импорт STL с единицами mm.

Не следует утверждать поддержку любого DICOM, гарантированные 50% decimation, полное исправление любой сетки или подтверждённые 30/30. Корректная формулировка: приложение надёжно работает для заявленного профиля, опасные данные отклоняет, а оставшиеся ограничения известны и воспроизводимы.
