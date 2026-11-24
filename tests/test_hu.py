from __future__ import annotations

import numpy as np
import pydicom
import pytest

from ct_reconstruction.errors import HounsfieldError
from ct_reconstruction.hu import convert_slice_to_hu


def test_rescale_to_hu_and_padding(ct_factory):
    stored = np.array([[-2000, 1024], [1424, 2000]], dtype=np.int16)
    ds = pydicom.dcmread(
        ct_factory(
            "hu.dcm", stored, slope=1, intercept=-1024, padding=-2000
        )
    )
    hu, valid = convert_slice_to_hu(ds)
    assert hu.dtype == np.float32
    assert np.isnan(hu[0, 0])
    assert hu[0, 1] == 0
    assert hu[1, 0] == 400
    assert valid.tolist() == [[False, True], [True, True]]


def test_per_slice_slope_and_intercept(ct_factory):
    pixels = np.array([[100]], dtype=np.int16)
    ds = pydicom.dcmread(
        ct_factory("scaled.dcm", pixels, slope=2.5, intercept=-1000)
    )
    hu, _ = convert_slice_to_hu(ds)
    assert hu[0, 0] == -750


@pytest.mark.parametrize("mutation", ["missing", "derived", "localizer", "mr"])
def test_rejects_unconfirmed_hu(ct_factory, mutation):
    ds = pydicom.dcmread(ct_factory("bad.dcm", np.zeros((2, 2), dtype=np.int16)))
    if mutation == "missing":
        del ds.RescaleSlope
    elif mutation == "derived":
        ds.ImageType = ["DERIVED", "PRIMARY", "AXIAL"]
    elif mutation == "localizer":
        ds.ImageType = ["ORIGINAL", "PRIMARY", "LOCALIZER"]
    else:
        ds.Modality = "MR"
    with pytest.raises(HounsfieldError):
        convert_slice_to_hu(ds)
