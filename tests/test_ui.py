from __future__ import annotations

import threading

import numpy as np
from PySide6.QtCore import QPoint, QThread, Qt

from ct_reconstruction.models import CTVolume, StudyInfo, VolumeGeometry
from ct_reconstruction.ui.main_window import MainWindow
from ct_reconstruction.ui.slice_view import SliceView


def make_volume() -> CTVolume:
    data = np.full((4, 5, 6), -1000, dtype=np.float32)
    data[1:3, 1:4, 2:5] = 600
    geometry = VolumeGeometry(
        (2.0, 0.7, 0.8),
        np.array([10.0, 20.0, 30.0]),
        np.array([1.0, 0, 0]),
        np.array([0, 1.0, 0]),
        np.array([0, 0, 1.0]),
    )
    study = StudyInfo(
        study_description="Test study", series_description="Test series",
        modality="CT", patient_name=None, patient_id=None
    )
    return CTVolume(data, np.ones_like(data, dtype=np.bool_), geometry, study, "series", "frame", 4)


def test_main_window_threshold_surface_and_invalidation(qtbot):
    window = MainWindow()
    qtbot.addWidget(window)
    assert window.viewer.plotter.render_window.GetMultiSamples() == 0
    interactor = window.viewer.plotter.interactor
    assert interactor.GetEnabled()
    assert interactor.GetInteractorStyle().GetClassName() == "vtkInteractorStyleTrackballCamera"
    window._volume_loaded(make_volume())
    qtbot.waitUntil(lambda: window.viewer.current_mode == "mask", timeout=5000)
    assert window.segmentation.mask.sum() == 18
    assert window.metadata_labels["patient"].text() == "Нет данных"
    assert window.viewer.current_mode == "mask"

    window.build_surface()
    qtbot.waitUntil(lambda: not window._busy_tokens, timeout=5000)
    assert window.active_mesh is not None, window.statusBar().currentMessage()
    assert window.viewer.current_mode == "mesh"
    assert window.export_button.isEnabled()
    assert "non-manifold" in window.metrics_label.text()
    window.decimate_surface()
    qtbot.waitUntil(lambda: not window._busy_tokens, timeout=5000)
    assert "До операции" in window.metrics_label.text()
    assert "удалено" in window.statusBar().currentMessage()
    window.show_current_mask()
    assert window.viewer.current_mode == "mask"
    assert not window.export_button.isEnabled()
    window.reset_mesh()
    assert window.viewer.current_mode == "mesh"
    assert window.export_button.isEnabled()

    window.threshold.setValue(700)
    assert window.segmentation is None
    assert window.active_mesh is None
    assert not window.export_button.isEnabled()
    qtbot.wait(350)
    qtbot.waitUntil(lambda: window.segmentation is not None and window.segmentation.mask.sum() == 0, timeout=5000)
    assert window.active_mesh is None
    assert not window.export_button.isEnabled()

    window.select_seed(1, 2)
    window.tolerance.setValue(0)
    window.recalculate_region()
    qtbot.waitUntil(
        lambda: window.segmentation is not None
        and window.segmentation.method == "region_growing",
        timeout=5000,
    )
    assert window.segmentation.mask.sum() == 18

    window.tolerance.setValue(1)
    assert window.segmentation is None
    assert window.active_mesh is None


def test_folder_picker_loads_series_through_background_gui_workflow(
    qtbot, monkeypatch, ct_factory, tmp_path
):
    import ct_reconstruction.ui.main_window as main_window_module

    stored = np.array([[1024, 1424], [0, 2000]], dtype=np.int16)
    ct_factory("second.dcm", stored, position=(0, 0, 1), instance=1)
    ct_factory("first.dcm", stored + 1, position=(0, 0, 0), instance=99)

    window = MainWindow()
    qtbot.addWidget(window)
    monkeypatch.setattr(
        main_window_module.QFileDialog,
        "getExistingDirectory",
        lambda *args: str(tmp_path),
    )
    window.choose_directory()
    qtbot.waitUntil(
        lambda: window.volume is not None and window.viewer.current_mode == "mask",
        timeout=5000,
    )
    assert window.volume.data_hu.shape == (2, 2, 2)
    assert window.volume.data_hu[0, 0, 0] == 1
    assert window.metadata_labels["slices"].text() == "2"
    assert window.metadata_labels["patient"].text() == "Test^Anonymous"
    assert window.metadata_labels["modality"].text() == "CT"
    assert window.metadata_labels["patient_birth"].text() == "Нет данных"
    assert window.metadata_labels["patient_sex"].text() == "Нет данных"


def test_slice_view_selects_seed_from_real_mouse_click(qtbot):
    view = SliceView()
    qtbot.addWidget(view)
    view.resize(400, 300)
    view.show()
    view.set_slice(np.arange(32, dtype=np.float32).reshape(4, 8))
    selected: list[tuple[int, int]] = []
    view.seed_selected.connect(lambda y, x: selected.append((y, x)))

    left, top, width, height = view._display_rect
    qtbot.mouseClick(
        view,
        Qt.MouseButton.LeftButton,
        pos=QPoint(left + width // 2, top + height // 2),
    )

    assert selected == [(2, 4)]


def test_busy_operation_disables_parameters_and_pending_threshold(qtbot):
    window = MainWindow()
    qtbot.addWidget(window)
    window._volume_loaded(make_volume())
    qtbot.waitUntil(lambda: not window._busy_tokens, timeout=5000)

    window.threshold.setValue(500)
    release = threading.Event()
    window._submit(lambda: release.wait(2), lambda _result: None)
    assert not window.threshold_timer.isActive()
    assert not window.threshold.isEnabled()
    assert not window.tolerance.isEnabled()
    assert not window.slice_slider.isEnabled()
    assert not window.slice_view.isEnabled()
    assert not window.progress_bar.isHidden()
    assert not window.cancel_button.isEnabled()
    release.set()
    qtbot.waitUntil(lambda: not window._busy_tokens, timeout=5000)


def test_mesh_metrics_and_stl_export_run_outside_gui_thread(
    qtbot, monkeypatch, tmp_path
):
    import ct_reconstruction.ui.main_window as main_window_module

    window = MainWindow()
    qtbot.addWidget(window)
    window._volume_loaded(make_volume())
    qtbot.waitUntil(lambda: window.segmentation is not None, timeout=5000)
    gui_thread = QThread.currentThread()
    metric_threads: list[QThread] = []
    export_threads: list[QThread] = []
    real_metrics = main_window_module.mesh_metrics
    real_export = main_window_module.export_stl

    def tracked_metrics(mesh):
        metric_threads.append(QThread.currentThread())
        return real_metrics(mesh)

    def tracked_export(mesh, path):
        export_threads.append(QThread.currentThread())
        return real_export(mesh, path)

    monkeypatch.setattr(main_window_module, "mesh_metrics", tracked_metrics)
    monkeypatch.setattr(main_window_module, "export_stl", tracked_export)
    window.build_surface()
    qtbot.waitUntil(lambda: window.active_mesh is not None, timeout=5000)
    assert metric_threads and all(thread is not gui_thread for thread in metric_threads)

    destination = tmp_path / "background.stl"
    monkeypatch.setattr(
        main_window_module.QFileDialog,
        "getSaveFileName",
        lambda *args: (str(destination), "STL (*.stl)"),
    )
    window.export_surface()
    qtbot.waitUntil(lambda: destination.is_file() and not window._busy_tokens, timeout=5000)
    assert export_threads and all(thread is not gui_thread for thread in export_threads)


def test_close_waits_for_worker_without_destroying_viewer(qtbot):
    window = MainWindow()
    qtbot.addWidget(window)
    window.show()
    release = threading.Event()
    window._submit(lambda: release.wait(2), lambda _result: None)
    qtbot.waitUntil(lambda: bool(window._busy_tokens), timeout=1000)

    assert not window.close()
    assert window._closing
    assert window.isVisible()
    assert not window.cancel_button.isEnabled()

    release.set()
    qtbot.waitUntil(lambda: not window.isVisible(), timeout=5000)
