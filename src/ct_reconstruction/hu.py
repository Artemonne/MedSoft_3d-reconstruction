"""DICOM stored-value conversion to confirmed Hounsfield units."""

from __future__ import annotations

import numpy as np
from numpy.typing import NDArray
from pydicom.dataset import Dataset

from .errors import HounsfieldError


def _is_confirmed_classic_hu(ds: Dataset) -> bool:
    if str(getattr(ds, "Modality", "")).upper() != "CT":
        return False
    image_type = [str(item).upper() for item in getattr(ds, "ImageType", [])]
    if image_type and image_type[0] != "ORIGINAL":
        return False
    if len(image_type) >= 3 and image_type[2] == "LOCALIZER":
        return False
    multi_energy = str(getattr(ds, "MultienergyCTAcquisition", "NO")).upper()
    return multi_energy in {"", "NO"}


def convert_slice_to_hu(ds: Dataset) -> tuple[NDArray[np.float32], NDArray[np.bool_]]:
    """Decode one classic CT slice and return HU plus a valid-voxel mask."""
    if not _is_confirmed_classic_hu(ds):
        raise HounsfieldError(
            "Единицы пикселей не подтверждены как HU для классического ORIGINAL CT"
        )
    if not hasattr(ds, "RescaleSlope") or not hasattr(ds, "RescaleIntercept"):
        raise HounsfieldError("Отсутствуют обязательные RescaleSlope/RescaleIntercept")
    try:
        slope = float(ds.RescaleSlope)
        intercept = float(ds.RescaleIntercept)
    except (TypeError, ValueError) as exc:
        raise HounsfieldError("Некорректные коэффициенты преобразования HU") from exc
    if not np.isfinite([slope, intercept]).all() or slope == 0:
        raise HounsfieldError("Коэффициенты преобразования HU недопустимы")

    try:
        stored = np.asarray(ds.pixel_array)
    except Exception as exc:
        syntax = str(getattr(getattr(ds, "file_meta", None), "TransferSyntaxUID", ""))
        raise HounsfieldError(
            f"Не удалось декодировать PixelData (Transfer Syntax {syntax or 'не указана'})"
        ) from exc
    if stored.ndim != 2:
        raise HounsfieldError("Поддерживаются только однокадровые монохромные CT-срезы")

    valid = np.ones(stored.shape, dtype=np.bool_)
    if hasattr(ds, "PixelPaddingValue"):
        padding_low = float(ds.PixelPaddingValue)
        padding_high = float(getattr(ds, "PixelPaddingRangeLimit", padding_low))
        low, high = sorted((padding_low, padding_high))
        valid &= ~((stored >= low) & (stored <= high))

    hu64 = stored.astype(np.float64) * slope + intercept
    valid &= np.isfinite(hu64)
    hu = hu64.astype(np.float32)
    hu[~valid] = np.nan
    return hu, valid

