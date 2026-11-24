from __future__ import annotations

import numpy as np
import pydicom
import pytest

from ct_reconstruction.errors import GeometryError
from ct_reconstruction.geometry import analyze_geometry


def test_sorts_by_physical_position_and_preserves_anisotropy(ct_factory):
    pixels = np.zeros((3, 4), dtype=np.int16)
    paths = [
        ct_factory("z5.dcm", pixels, position=(0, 0, 5), instance=1),
        ct_factory("z0.dcm", pixels, position=(0, 0, 0), instance=99),
        ct_factory("z2.dcm", pixels, position=(0, 0, 2.5), instance=5),
    ]
    result = analyze_geometry([pydicom.dcmread(path) for path in paths])
    assert result.order == (1, 2, 0)
    assert result.geometry.spacing_zyx_mm == pytest.approx((2.5, 0.7, 0.8))
    point = result.geometry.index_zyx_to_lps(np.array([2.0, 1.0, 3.0]))
    assert point == pytest.approx([2.4, 0.7, 5.0])


def test_slice_thickness_is_not_used_as_spacing(ct_factory):
    pixels = np.zeros((2, 2), dtype=np.int16)
    datasets = [
        pydicom.dcmread(ct_factory("a.dcm", pixels, position=(0, 0, 0))),
        pydicom.dcmread(ct_factory("b.dcm", pixels, position=(0, 0, 2))),
    ]
    assert datasets[0].SliceThickness == 5
    assert analyze_geometry(datasets).geometry.spacing_zyx_mm[0] == 2


@pytest.mark.parametrize(
    "positions, message",
    [
        ([(0, 0, 0), (0, 0, 2), (0, 0, 5)], "неравномерен"),
        ([(0, 0, 0), (0.2, 0, 2), (0.4, 0, 4)], "боковой сдвиг"),
        ([(0, 0, 0), (0, 0, 0)], "повторяющиеся"),
    ],
)
def test_rejects_untrustworthy_geometry(ct_factory, positions, message):
    pixels = np.zeros((2, 2), dtype=np.int16)
    datasets = [
        pydicom.dcmread(ct_factory(f"s{i}.dcm", pixels, position=position))
        for i, position in enumerate(positions)
    ]
    with pytest.raises(GeometryError, match=message):
        analyze_geometry(datasets)


def test_rejects_missing_geometry(ct_factory):
    pixels = np.zeros((2, 2), dtype=np.int16)
    ds1 = pydicom.dcmread(ct_factory("a.dcm", pixels, position=(0, 0, 0)))
    ds2 = pydicom.dcmread(ct_factory("b.dcm", pixels, position=(0, 0, 2)))
    del ds2.ImagePositionPatient
    with pytest.raises(GeometryError, match="ImagePositionPatient"):
        analyze_geometry([ds1, ds2])

