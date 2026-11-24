from __future__ import annotations

import numpy as np
from pydicom.uid import generate_uid

from ct_reconstruction.dicom_loader import discover_series, load_series


def test_discovers_separate_series_and_loads_sorted_volume(ct_factory, tmp_path):
    other_series = generate_uid()
    pixels = np.array([[1024, 1424], [0, 2000]], dtype=np.int16)
    ct_factory("late.dcm", pixels, position=(0, 0, 2), instance=1)
    ct_factory("early.dcm", pixels + 1, position=(0, 0, 0), instance=20)
    ct_factory(
        "other.dcm", pixels, position=(0, 0, 0), current_series_uid=other_series
    )
    (tmp_path / "not-dicom.txt").write_text("no patient data", encoding="utf-8")

    candidates = discover_series([tmp_path])
    assert len(candidates) == 2
    selected = next(item for item in candidates if len(item.files) == 2)
    volume = load_series(selected, version=7)
    assert volume.data_hu.shape == (2, 2, 2)
    assert volume.data_hu[0, 0, 0] == 1
    assert volume.data_hu[1, 0, 0] == 0
    assert volume.version == 7
    assert volume.study.patient_name == "Test^Anonymous"


def test_missing_optional_patient_fields_are_none(ct_factory, tmp_path):
    pixels = np.zeros((2, 2), dtype=np.int16)
    ct_factory("a.dcm", pixels, position=(0, 0, 0), include_patient=False)
    ct_factory("b.dcm", pixels, position=(0, 0, 1), include_patient=False)
    volume = load_series(discover_series([tmp_path])[0])
    assert volume.study.patient_name is None
    assert volume.study.display(volume.study.patient_name) == "Нет данных"

