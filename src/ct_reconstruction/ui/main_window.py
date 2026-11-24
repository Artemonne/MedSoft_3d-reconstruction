"""Main application window joining DICOM, segmentation and mesh operations."""

from __future__ import annotations

import os
import threading
from PySide6.QtCore import QThreadPool, QTimer, Qt
from PySide6.QtWidgets import (
    QCheckBox, QDoubleSpinBox, QFileDialog, QFormLayout, QGroupBox, QHBoxLayout,
    QInputDialog, QLabel, QMainWindow, QMessageBox, QProgressBar, QPushButton, QSlider,
    QSpinBox, QSplitter, QStatusBar, QVBoxLayout, QWidget,
)

from ..dicom_loader import SeriesCandidate, discover_series, load_series
from ..mesh_processing import decimate_mesh, export_stl, mesh_metrics, repair_mesh, smooth_mesh
from ..models import CTVolume, Mesh, Segmentation
from ..segmentation import region_growing, threshold_segmentation
from ..surface import marching_cubes_surface
from .slice_view import SliceView
from .viewer_3d import Viewer3D
from .workers import TaskRunner


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("КТ 3D — лабораторная № 5")
        self.resize(1400, 860)
        self.thread_pool = QThreadPool.globalInstance()
        self._task_token = 0
        self._busy_tokens: set[int] = set()
        self._runners: dict[int, TaskRunner] = {}
        self._cancel_events: dict[int, threading.Event] = {}
        self.volume: CTVolume | None = None
        self.segmentation: Segmentation | None = None
        self.original_mesh: Mesh | None = None
        self.active_mesh: Mesh | None = None
        self.seed_zyx: tuple[int, int, int] | None = None
        self._segmentation_version = 0
        self._volume_version = 0
        self._closing = False
        self._original_mesh_metrics: dict[str, object] | None = None
        self._active_mesh_metrics: dict[str, object] | None = None
        self._build_ui()

        self.threshold_timer = QTimer(self)
        self.threshold_timer.setSingleShot(True)
        self.threshold_timer.setInterval(300)
        self.threshold_timer.timeout.connect(self.recalculate_threshold)

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        outer = QHBoxLayout(central)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        outer.addWidget(splitter)

        controls = QWidget()
        controls.setMinimumWidth(350)
        controls.setMaximumWidth(430)
        panel = QVBoxLayout(controls)
        self.load_button = QPushButton("Загрузить папку DICOM…")
        self.load_button.clicked.connect(self.choose_directory)
        panel.addWidget(self.load_button)

        metadata_box = QGroupBox("Исследование и геометрия")
        metadata_form = QFormLayout(metadata_box)
        self.metadata_labels: dict[str, QLabel] = {}
        for key, title in (
            ("study", "Исследование"), ("series", "Серия"), ("date", "Дата"),
            ("modality", "Модальность"), ("patient", "Пациент"),
            ("patient_id", "ID пациента"), ("patient_birth", "Дата рождения"),
            ("patient_sex", "Пол"),
            ("spacing", "Spacing, мм"), ("slices", "Срезов"),
        ):
            label = QLabel("Нет данных")
            label.setWordWrap(True)
            self.metadata_labels[key] = label
            metadata_form.addRow(title + ":", label)
        panel.addWidget(metadata_box)

        segment_box = QGroupBox("Сегментация")
        segment_form = QFormLayout(segment_box)
        self.threshold = QSpinBox()
        self.threshold.setRange(-2048, 4096)
        self.threshold.setValue(400)
        self.threshold.setSuffix(" HU")
        self.threshold.valueChanged.connect(self._threshold_changed)
        segment_form.addRow("Порог ≥", self.threshold)
        self.tolerance = QDoubleSpinBox()
        self.tolerance.setRange(0, 4096)
        self.tolerance.setValue(50)
        self.tolerance.setSuffix(" HU")
        self.tolerance.valueChanged.connect(self._region_parameters_changed)
        segment_form.addRow("Перепад", self.tolerance)
        self.region_button = QPushButton("Region Growing от seed")
        self.region_button.clicked.connect(self.recalculate_region)
        segment_form.addRow(self.region_button)
        self.seed_label = QLabel("Seed не выбран")
        segment_form.addRow("Seed (z,y,x):", self.seed_label)
        panel.addWidget(segment_box)

        surface_box = QGroupBox("Поверхность")
        surface_layout = QVBoxLayout(surface_box)
        self.marching_button = QPushButton("Построить Marching Cubes")
        self.marching_button.clicked.connect(self.build_surface)
        self.mask_button = QPushButton("Показать маску")
        self.mask_button.clicked.connect(self.show_current_mask)
        self.smooth_button = QPushButton("Сгладить")
        self.smooth_button.clicked.connect(self.smooth_surface)
        self.decimate_button = QPushButton("Упростить на 50%")
        self.decimate_button.clicked.connect(self.decimate_surface)
        repair_row = QHBoxLayout()
        self.hole_size = QDoubleSpinBox()
        self.hole_size.setRange(0.1, 1000)
        self.hole_size.setValue(5)
        self.hole_size.setSuffix(" мм")
        self.keep_largest = QCheckBox("оставить крупнейший компонент")
        self.repair_button = QPushButton("Исправить сетку")
        self.repair_button.clicked.connect(self.repair_surface)
        self.reset_mesh_button = QPushButton("Сбросить обработку")
        self.reset_mesh_button.clicked.connect(self.reset_mesh)
        for widget in (self.marching_button, self.mask_button, self.smooth_button, self.decimate_button):
            surface_layout.addWidget(widget)
        repair_row.addWidget(self.hole_size)
        surface_layout.addLayout(repair_row)
        surface_layout.addWidget(self.keep_largest)
        surface_layout.addWidget(self.repair_button)
        surface_layout.addWidget(self.reset_mesh_button)
        self.metrics_label = QLabel("Сетка не построена")
        self.metrics_label.setWordWrap(True)
        surface_layout.addWidget(self.metrics_label)
        panel.addWidget(surface_box)

        self.export_button = QPushButton("Экспортировать показанную сетку в STL…")
        self.export_button.clicked.connect(self.export_surface)
        panel.addWidget(self.export_button)
        self.cancel_button = QPushButton("Отменить текущую операцию")
        self.cancel_button.clicked.connect(self.cancel_current_task)
        panel.addWidget(self.cancel_button)
        panel.addStretch(1)
        splitter.addWidget(controls)

        views = QSplitter(Qt.Orientation.Vertical)
        self.viewer = Viewer3D()
        views.addWidget(self.viewer)
        slice_panel = QWidget()
        slice_layout = QVBoxLayout(slice_panel)
        self.slice_view = SliceView()
        self.slice_view.seed_selected.connect(self.select_seed)
        self.slice_slider = QSlider(Qt.Orientation.Horizontal)
        self.slice_slider.valueChanged.connect(self.update_slice_view)
        slice_layout.addWidget(self.slice_view)
        slice_layout.addWidget(self.slice_slider)
        views.addWidget(slice_panel)
        views.setSizes([600, 260])
        splitter.addWidget(views)
        splitter.setSizes([380, 1020])

        self.setStatusBar(QStatusBar())
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 0)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setFixedWidth(140)
        self.progress_bar.hide()
        self.statusBar().addPermanentWidget(self.progress_bar)
        self.statusBar().showMessage("Готово. Выберите папку с DICOM-срезами.")
        self._update_actions()

    def choose_directory(self) -> None:
        directory = QFileDialog.getExistingDirectory(self, "Выберите папку DICOM")
        if directory:
            self.statusBar().showMessage("Поиск DICOM-серий…")
            self._submit(lambda: discover_series([directory]), self._series_discovered)

    def _series_discovered(self, candidates: tuple[SeriesCandidate, ...]) -> None:
        if not candidates:
            self._show_error("В выбранной папке не найдено подходящих CT DICOM-серий")
            return
        candidate = candidates[0]
        if len(candidates) > 1:
            names = [item.display_name for item in candidates]
            selected, ok = QInputDialog.getItem(self, "Выбор серии", "Серия:", names, 0, False)
            if not ok:
                self.statusBar().showMessage("Загрузка отменена")
                return
            candidate = candidates[names.index(selected)]
        self._volume_version += 1
        version = self._volume_version
        self.statusBar().showMessage("Декодирование и проверка геометрии…")
        self._submit(lambda: load_series(candidate, version=version), self._volume_loaded)

    def _volume_loaded(self, volume: CTVolume) -> None:
        self.volume = volume
        self.seed_zyx = None
        self.seed_label.setText("Seed не выбран")
        self._invalidate_segmentation()
        self._populate_metadata()
        self.slice_slider.setRange(0, volume.data_hu.shape[0] - 1)
        self.slice_slider.setValue(volume.data_hu.shape[0] // 2)
        self.update_slice_view()
        self.recalculate_threshold()

    def _populate_metadata(self) -> None:
        assert self.volume is not None
        study = self.volume.study
        dz, dr, dc = self.volume.geometry.spacing_zyx_mm
        self.metadata_labels["study"].setText(study.display(study.study_description))
        self.metadata_labels["series"].setText(study.display(study.series_description))
        self.metadata_labels["date"].setText(study.display(study.study_date))
        self.metadata_labels["modality"].setText(study.display(study.modality))
        self.metadata_labels["patient"].setText(study.display(study.patient_name))
        self.metadata_labels["patient_id"].setText(study.display(study.patient_id))
        self.metadata_labels["patient_birth"].setText(
            study.display(study.patient_birth_date)
        )
        self.metadata_labels["patient_sex"].setText(study.display(study.patient_sex))
        self.metadata_labels["spacing"].setText(f"срез {dz:g}; строка {dr:g}; столбец {dc:g}")
        self.metadata_labels["slices"].setText(str(self.volume.source_count))

    def recalculate_threshold(self) -> None:
        if self.volume is None:
            return
        self._segmentation_version += 1
        version = self._segmentation_version
        volume = self.volume
        threshold = self.threshold.value()
        self._invalidate_mesh()
        self.statusBar().showMessage("Пересчёт пороговой маски…")
        self._submit(
            lambda: threshold_segmentation(volume, threshold, version=version),
            self._segmentation_ready,
        )

    def _threshold_changed(self) -> None:
        if self.volume is not None:
            self._invalidate_segmentation()
        self.threshold_timer.start()

    def _region_parameters_changed(self) -> None:
        if self.segmentation is not None and self.segmentation.method == "region_growing":
            self._invalidate_segmentation()

    def recalculate_region(self) -> None:
        if self.volume is None or self.seed_zyx is None:
            self._show_error("Сначала выберите seed щелчком по 2D-срезу")
            return
        self._segmentation_version += 1
        version = self._segmentation_version
        volume, seed, tolerance = self.volume, self.seed_zyx, self.tolerance.value()
        cancel_event = threading.Event()
        self._invalidate_mesh()
        self.statusBar().showMessage("Region Growing…")
        self._submit(
            lambda: region_growing(
                volume, seed, tolerance, version=version, cancelled=cancel_event.is_set
            ),
            self._segmentation_ready,
            cancel_event=cancel_event,
        )

    def _segmentation_ready(self, segmentation: Segmentation) -> None:
        if self.volume is None or segmentation.volume_version != self.volume.version:
            return
        self.segmentation = segmentation
        self.viewer.show_mask(self.volume, segmentation)
        count = int(segmentation.mask.sum())
        self.statusBar().showMessage(f"Маска обновлена: {count:,} вокселей")
        self._update_actions()

    def select_seed(self, y: int, x: int) -> None:
        if self.volume is None:
            return
        z = self.slice_slider.value()
        invalidate_region = (
            self.segmentation is not None
            and self.segmentation.method == "region_growing"
        )
        self.seed_zyx = (z, y, x)
        self.seed_label.setText(f"{z}, {y}, {x} ({self.volume.data_hu[z, y, x]:g} HU)")
        if invalidate_region:
            self._invalidate_segmentation()
        self.update_slice_view()
        self._update_actions()

    def update_slice_view(self) -> None:
        if self.volume is None:
            return
        z = self.slice_slider.value()
        seed = self.seed_zyx[1:] if self.seed_zyx and self.seed_zyx[0] == z else None
        self.slice_view.set_slice(self.volume.data_hu[z], seed)

    def build_surface(self) -> None:
        if self.volume is None or self.segmentation is None:
            return
        segmentation, geometry = self.segmentation, self.volume.geometry
        self.statusBar().showMessage("Marching Cubes…")
        self._submit(
            lambda: self._mesh_and_metrics(
                marching_cubes_surface(segmentation, geometry)
            ),
            self._mesh_ready,
        )

    @staticmethod
    def _mesh_and_metrics(mesh: Mesh) -> tuple[Mesh, dict[str, object]]:
        return mesh, mesh_metrics(mesh)

    def _mesh_ready(self, payload: tuple[Mesh, dict[str, object]]) -> None:
        mesh, metrics = payload
        if self.segmentation is None or mesh.segmentation_version != self.segmentation.version:
            return
        self.original_mesh = mesh.copy()
        self.active_mesh = mesh
        self._original_mesh_metrics = metrics
        self._active_mesh_metrics = metrics
        self._show_mesh(mesh, metrics)

    def _processed_mesh_ready(self, payload: tuple[Mesh, dict[str, object]]) -> None:
        mesh, metrics = payload
        if self.segmentation is None or mesh.segmentation_version != self.segmentation.version:
            return
        self.active_mesh = mesh
        self._active_mesh_metrics = metrics
        self._show_mesh(mesh, metrics)

    def _show_mesh(self, mesh: Mesh, values: dict[str, object]) -> None:
        self.viewer.show_mesh(mesh)
        self.metrics_label.setText(
            f"Вершин: {values['vertices']:,}; треугольников: {values['triangles']:,}; "
            f"границ: {values['boundary_edges']}; компонент: {values['components']}"
        )
        self.statusBar().showMessage("Поверхность отображена")
        self._update_actions()

    def show_current_mask(self) -> None:
        if self.volume is not None and self.segmentation is not None:
            self.viewer.show_mask(self.volume, self.segmentation)
            self._update_actions()

    def smooth_surface(self) -> None:
        if self.active_mesh is not None:
            source = self.active_mesh
            self.statusBar().showMessage("Сглаживание поверхности…")
            self._submit(
                lambda: self._mesh_and_metrics(smooth_mesh(source)),
                self._processed_mesh_ready,
            )

    def decimate_surface(self) -> None:
        if self.active_mesh is not None:
            source = self.active_mesh
            self.statusBar().showMessage("Упрощение поверхности…")
            self._submit(
                lambda: self._mesh_and_metrics(decimate_mesh(source, reduction=0.5)),
                self._processed_mesh_ready,
            )

    def repair_surface(self) -> None:
        if self.active_mesh is not None:
            source = self.active_mesh
            size, largest = self.hole_size.value(), self.keep_largest.isChecked()
            self.statusBar().showMessage("Исправление дефектов сетки…")
            self._submit(
                lambda: self._mesh_and_metrics(
                    repair_mesh(
                        source,
                        hole_size_mm=size,
                        keep_largest_component=largest,
                    )
                ),
                self._processed_mesh_ready,
            )

    def reset_mesh(self) -> None:
        if self.original_mesh is not None and self._original_mesh_metrics is not None:
            self.active_mesh = self.original_mesh.copy()
            self._active_mesh_metrics = self._original_mesh_metrics
            self._show_mesh(self.active_mesh, self._active_mesh_metrics)

    def export_surface(self) -> None:
        if self.active_mesh is None or self.segmentation is None:
            return
        if self.active_mesh.segmentation_version != self.segmentation.version:
            self._show_error("Сетка устарела; постройте поверхность для текущей маски")
            return
        filename, _ = QFileDialog.getSaveFileName(self, "Сохранить STL", "model.stl", "STL (*.stl)")
        if filename:
            mesh = self.active_mesh
            self.statusBar().showMessage("Экспорт STL…")
            self._submit(
                lambda: export_stl(mesh, filename),
                lambda saved: self.statusBar().showMessage(f"Сохранено: {saved.name}"),
            )

    def _submit(self, function, callback, *, cancel_event: threading.Event | None = None) -> None:
        self.threshold_timer.stop()
        self._task_token += 1
        token = self._task_token
        runner = TaskRunner(token, function)
        runner.signals.succeeded.connect(
            lambda returned, result: callback(result)
            if returned == self._task_token else None
        )
        runner.signals.failed.connect(
            lambda returned, message: self._show_error(message)
            if returned == self._task_token else None
        )
        runner.signals.finished.connect(self._task_finished)
        self._busy_tokens.add(token)
        self._runners[token] = runner
        if cancel_event is not None:
            self._cancel_events[token] = cancel_event
        self._update_actions()
        self.thread_pool.start(runner)

    def _task_finished(self, token: int) -> None:
        self._busy_tokens.discard(token)
        self._runners.pop(token, None)
        self._cancel_events.pop(token, None)
        self._update_actions()
        if self._closing and not self._busy_tokens:
            QTimer.singleShot(0, self.close)

    def cancel_current_task(self) -> None:
        if not self._cancel_events:
            return
        for event in self._cancel_events.values():
            event.set()
        self._task_token += 1
        self.statusBar().showMessage("Отмена Region Growing запрошена…")
        self._update_actions()

    def _invalidate_segmentation(self) -> None:
        self.segmentation = None
        self._invalidate_mesh()
        self.viewer.clear()

    def _invalidate_mesh(self) -> None:
        self.original_mesh = None
        self.active_mesh = None
        self._original_mesh_metrics = None
        self._active_mesh_metrics = None
        self.metrics_label.setText("Сетка не построена")
        self._update_actions()

    def _update_actions(self) -> None:
        busy = bool(self._busy_tokens) or self._closing
        self.load_button.setEnabled(not busy)
        self.cancel_button.setEnabled(bool(self._cancel_events) and not self._closing)
        self.progress_bar.setVisible(bool(self._busy_tokens) and not self._closing)
        self.threshold.setEnabled(not busy)
        self.tolerance.setEnabled(not busy)
        self.slice_slider.setEnabled(not busy and self.volume is not None)
        self.slice_view.setEnabled(not busy and self.volume is not None)
        self.region_button.setEnabled(not busy and self.volume is not None and self.seed_zyx is not None)
        self.marching_button.setEnabled(not busy and self.segmentation is not None)
        self.mask_button.setEnabled(not busy and self.segmentation is not None)
        mesh_ready = not busy and self.active_mesh is not None
        for widget in (self.smooth_button, self.decimate_button, self.repair_button, self.reset_mesh_button):
            widget.setEnabled(mesh_ready)
        self.export_button.setEnabled(
            mesh_ready and self.viewer.current_mode == "mesh"
        )
        self.hole_size.setEnabled(mesh_ready)
        self.keep_largest.setEnabled(mesh_ready)

    def _show_error(self, message: str) -> None:
        self.statusBar().showMessage(message)
        if os.environ.get("QT_QPA_PLATFORM", "").lower() != "offscreen":
            QMessageBox.warning(self, "Ошибка", message)

    def closeEvent(self, event) -> None:
        if self._busy_tokens:
            self._closing = True
            for cancel_event in self._cancel_events.values():
                cancel_event.set()
            self.statusBar().showMessage(
                "Завершение фоновой операции перед закрытием окна…"
            )
            self._update_actions()
            event.ignore()
            return
        self.viewer.close_viewer()
        super().closeEvent(event)
