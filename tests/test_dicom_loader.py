from __future__ import annotations

import numpy as np
import pydicom
import pytest
from pydicom.uid import generate_uid

import ct_reconstruction.dicom_loader as loader
from ct_reconstruction.dicom_loader import discover_series, load_series
from ct_reconstruction.errors import DicomLoadError


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


def test_corrupt_file_inside_selected_candidate_is_not_silently_skipped(
    ct_factory, tmp_path
):
    pixels = np.zeros((2, 2), dtype=np.int16)
    ct_factory("a.dcm", pixels, position=(0, 0, 0))
    ct_factory("b.dcm", pixels, position=(0, 0, 1))
    candidate = discover_series([tmp_path])[0]
    corrupt = tmp_path / "corrupt.dcm"
    corrupt.write_bytes(b"not a dicom file")
    candidate = type(candidate)(
        candidate.series_instance_uid,
        candidate.frame_of_reference_uid,
        candidate.description,
        (*candidate.files, corrupt),
    )
    with pytest.raises(DicomLoadError, match="повреждён"):
        load_series(candidate)


def test_rle_compressed_classic_ct_is_decoded(ct_factory, tmp_path):
    from pydicom.uid import RLELossless

    pixels = np.array([[1000, 1200], [1400, 1600]], dtype=np.int16)
    first = ct_factory("a.dcm", pixels, position=(0, 0, 0))
    second = ct_factory("b.dcm", pixels, position=(0, 0, 1))
    for path in (first, second):
        ds = pydicom.dcmread(path)
        ds.compress(RLELossless)
        ds.save_as(path, enforce_file_format=True)
    volume = load_series(discover_series([tmp_path])[0])
    assert volume.data_hu[:, 0, 0].tolist() == [-24.0, -24.0]


def test_same_series_different_frames_are_separate_candidates(ct_factory, tmp_path):
    pixels = np.zeros((2, 2), dtype=np.int16)
    ct_factory("a.dcm", pixels, current_frame_uid=generate_uid())
    ct_factory("b.dcm", pixels, current_frame_uid=generate_uid())
    assert len(discover_series([tmp_path])) == 2


def test_volume_size_limit_prevents_unbounded_allocation(ct_factory, tmp_path, monkeypatch):
    pixels = np.zeros((2, 2), dtype=np.int16)
    ct_factory("a.dcm", pixels, position=(0, 0, 0))
    ct_factory("b.dcm", pixels, position=(0, 0, 1))
    monkeypatch.setattr(loader, "MAX_VOXELS", 7)
    with pytest.raises(DicomLoadError, match="слишком велик"):
        load_series(discover_series([tmp_path])[0])

