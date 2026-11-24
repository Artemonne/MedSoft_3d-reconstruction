from __future__ import annotations

import numpy as np

from ct_reconstruction.dicom_loader import discover_series
from ct_reconstruction.models import CTVolume, StudyInfo, VolumeGeometry
from ct_reconstruction.ui.main_window import MainWindow


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

    window.threshold.setValue(700)
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


def test_series_candidate_loads_through_background_gui_workflow(qtbot, ct_factory, tmp_path):
    stored = np.array([[1024, 1424], [0, 2000]], dtype=np.int16)
    ct_factory("second.dcm", stored, position=(0, 0, 1), instance=1)
    ct_factory("first.dcm", stored + 1, position=(0, 0, 0), instance=99)
    candidate = discover_series([tmp_path])[0]

    window = MainWindow()
    qtbot.addWidget(window)
    window._series_discovered((candidate,))
    qtbot.waitUntil(
        lambda: window.volume is not None and window.viewer.current_mode == "mask",
        timeout=5000,
    )
    assert window.volume.data_hu.shape == (2, 2, 2)
    assert window.volume.data_hu[0, 0, 0] == 1
    assert window.metadata_labels["slices"].text() == "2"
    assert window.metadata_labels["patient"].text() == "Test^Anonymous"
