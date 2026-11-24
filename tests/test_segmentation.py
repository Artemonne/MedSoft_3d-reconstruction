from __future__ import annotations

import numpy as np
import pytest

from ct_reconstruction.errors import SegmentationError
from ct_reconstruction.models import CTVolume, StudyInfo, VolumeGeometry
from ct_reconstruction.segmentation import region_growing, threshold_segmentation


def make_volume(values, valid=None):
    data = np.asarray(values, dtype=np.float32)
    if valid is None:
        valid = np.ones(data.shape, dtype=np.bool_)
    geometry = VolumeGeometry(
        (1.0, 1.0, 1.0), np.zeros(3), np.array([1.0, 0, 0]),
        np.array([0, 1.0, 0]), np.array([0, 0, 1.0])
    )
    return CTVolume(data, np.asarray(valid, dtype=np.bool_), geometry, StudyInfo(), "s", "f", data.shape[0])


def test_threshold_uses_hu_and_validity_mask():
    volume = make_volume([[[-1000, 399, 400, 1000]]], [[[True, True, True, False]]])
    result = threshold_segmentation(volume, 400, version=2)
    assert result.mask.tolist() == [[[False, False, True, False]]]
    assert result.parameters == {"threshold_hu": 400.0}


def test_region_growing_uses_local_gradient():
    volume = make_volume([[[0, 4, 8, 30]]])
    assert region_growing(volume, (0, 0, 0), 4, version=1).mask.tolist() == [[[True, True, True, False]]]
    assert region_growing(volume, (0, 0, 0), 3, version=2).mask.tolist() == [[[True, False, False, False]]]


def test_region_growing_is_six_connected():
    volume = make_volume([[[0, 100], [100, 0]]])
    result = region_growing(volume, (0, 0, 0), 0, version=1)
    assert result.mask.sum() == 1


def test_region_growing_can_reach_voxel_through_another_path():
    volume = make_volume([[[0, 10], [4, 8]]])
    result = region_growing(volume, (0, 0, 0), 4, version=1)
    assert result.mask.all()


def test_region_growing_cancellation_never_publishes_partial_mask():
    volume = make_volume(np.zeros((4, 4, 4), dtype=np.float32))
    with pytest.raises(SegmentationError, match="отменено"):
        region_growing(
            volume, (0, 0, 0), 0, version=1, cancelled=lambda: True
        )


def test_region_growing_reports_incremental_count_without_rescanning_result():
    volume = make_volume(np.zeros((30, 30, 30), dtype=np.float32))
    updates: list[int] = []
    result = region_growing(
        volume, (0, 0, 0), 0, version=1, progress=updates.append
    )
    assert updates
    assert updates == sorted(updates)
    assert updates[-1] == result.mask.size


@pytest.mark.parametrize(
    "seed,tolerance,valid,message",
    [((-1, 0, 0), 1, None, "вне"), ((0, 0, 0), -1, None, "неотрицательной"),
     ((0, 0, 0), 1, [[[False]]], "padding")],
)
def test_region_growing_rejects_bad_parameters(seed, tolerance, valid, message):
    volume = make_volume([[[0]]], valid)
    with pytest.raises(SegmentationError, match=message):
        region_growing(volume, seed, tolerance, version=1)
