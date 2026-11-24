# Фактические результаты тестирования

Дата финального прогона: 24.11.2026

ОС: Windows 11 x64

Python: CPython 3.12 x64

Ветка: `feat/lab5-implementation`

Этот файл фиксирует только выполненные проверки. DICOM-наборы, STL и скриншоты находятся в игнорируемых каталогах и не входят в Git.

## Чистая установка и автоматические тесты

Создано отдельное окружение `tmp/clean-venv`:

```text
python -m venv tmp/clean-venv
tmp\clean-venv\Scripts\python.exe -m pip install -e ".[test]"
tmp\clean-venv\Scripts\python.exe -m pip check
No broken requirements found.

$env:QT_API='pyside6'
$env:QT_QPA_PLATFORM='offscreen'
tmp\clean-venv\Scripts\python.exe -m pytest -q
...................................................                      [100%]
51 passed in 9.23s
```

Из `%TEMP%`, без опоры на текущий каталог, импортирован установленный пакет и создано окно `MainWindow` размером 1400x860. Целевые тесты mesh/UI после последней правки: `13 passed in 5.17s`.

Тесты покрывают: разбиение серий по UID/Frame of Reference, сортировку по IOP/IPP, HU rescale и padding, отказ для неподтверждённых HU и непригодной геометрии, oblique LPS-преобразование, threshold, 6-связный Region Growing, Marching Cubes, топологические метрики, repair, независимый разбор binary STL, гонки фоновых задач и инвалидирование устаревших результатов GUI.

## Реальные обезличенные CT

Источник: публичная коллекция TCIA RIDER Pilot (CC BY 4.0, DOI `10.7937/m87f-mz83`). Через NBIA API локально загружены две classic single-frame CT-серии из разных исследований одного и того же публичного набора:

| SeriesInstanceUID | Размер | Spacing `[z,y,x]`, мм | HU | Независимая сверка |
|---|---:|---:|---:|---|
| `1.3.6.1.4.1.9328.50.2.132604` | 33×512×512 | 10.0×0.703125×0.703125 | −2048…3071 | VTK: dimensions/spacing/range совпали |
| `1.3.6.1.4.1.9328.50.2.50427` | 33×512×512 | 10.0×0.664062×0.664062 | −2048…3071 | VTK: dimensions/spacing/range совпали |

Это два разных `StudyInstanceUID`. Файлы DICOM размещались под `test-data/tcia/`; каталог исключён `.gitignore`.

Порог `400 HU`:

| Серия | Вокселей маски | Вершин MC | Треугольников MC | Boundary | Non-manifold | Компонент |
|---|---:|---:|---:|---:|---:|---:|
| `…132604` | 105 377 | 294 116 | 580 220 | 0 | 57 | 4 682 |
| `…50427` | 133 270 | 431 954 | 857 236 | 0 | 162 | 7 873 |

Полный pipeline на обеих сериях включал load → threshold → MC → metrics → smooth → topology-safe decimate → binary STL → независимый parser. Для `…132604` итог после упрощения — 496 804 треугольника, для `…50427` — 771 090; boundary/non-manifold/components не ухудшились. Bounds независимого STL parser совпали с исходной сеткой. Пиковый RSS процесса полного pipeline составил 569,4 MiB.

Это проверка на объёмах по 8,65 млн вокселей, но не стресс-тест предельной серии в сотни миллионов вокселей.

## Видимый GUI на Windows

Обычное видимое Qt/VTK-окно с реальным OpenGL прошло программно управляемый end-to-end сценарий на серии `…132604`:

```text
threshold 400 HU: 105377 voxels
threshold 1000 HU: 12169 voxels
Region Growing, seed (10,307,243), tolerance 50 HU: 566 voxels
decimate target 50%: actual removal 16.4%
repair keep-largest: components 4682 -> 1; non-manifold 57 -> 9
export: real_gui_audit.stl, 5 223 384 bytes
```

Визуально просмотрены axial CT, threshold/Region Growing маски, mesh, прокрутка панели, метрики до/после и итоговый статус. Исправлены чёрный/повторяющийся framebuffer на Windows (MSAA/shading) и обрезание длинных метрик.

Физические действия мышью через системный драйвер автоматизации выполнить не удалось: канал управления Windows возвращал ошибку подключения. Поэтому реальное ручное вращение/zoom/pan, щелчок seed и системный file dialog остаются `NOT TESTED`; внутренние обработчики и состояния проверены GUI-тестами и видимым сценарием.

## STL во внешнем приложении

Blender, MeshLab, 3D Slicer, Assimp и F3D в системе не найдены. Экспортированный STL успешно открылся установленным Paint 3D и приложение осталось отзывчивым. Геометрию внутри Paint 3D независимо измерить не удалось.

Независимая проверка без PyVista/VTK подтвердила binary STL header/count/size, конечность координат, triangle count и bounds; VTK round-trip также совпал. Поэтому синтаксис и физические размеры доказаны сильнее, чем визуальный внешний просмотр, но пункт внешнего редактора закрыт только частично.

## Что не проверено

- Enhanced CT/multi-frame и реальные JPEG/JPEG-LS/JPEG 2000 серии; они не заявлены основным профилем, Enhanced CT отклоняется.
- Реальная серия с gantry tilt, irregular spacing или несовместимыми orientation; такие данные намеренно отклоняются до реконструкции.
- Пиковая память на объёме, близком к программному лимиту 300 млн вокселей.
- Полностью ручное управление мышью и визуальное измерение STL во внешнем CAD/medical viewer.
