"""Validation and reconstruction of classic single-frame CT geometry."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import numpy as np
from pydicom.dataset import Dataset

from .errors import GeometryError
from .models import VolumeGeometry


@dataclass(frozen=True, slots=True)
class GeometryResult:
    order: tuple[int, ...]
    geometry: VolumeGeometry


def _vector(ds: Dataset, name: str, length: int) -> np.ndarray:
    value = getattr(ds, name, None)
    if value is None or len(value) != length:
        raise GeometryError(f"Отсутствует обязательный геометрический тег {name}")
    try:
        result = np.asarray([float(item) for item in value], dtype=np.float64)
    except (TypeError, ValueError) as exc:
        raise GeometryError(f"Некорректное значение тега {name}") from exc
    if not np.isfinite(result).all():
        raise GeometryError(f"Тег {name} содержит нечисловые значения")
    return result


def analyze_geometry(
    datasets: Sequence[Dataset],
    *,
    direction_tolerance: float = 1e-4,
    spacing_absolute_tolerance_mm: float = 0.01,
    spacing_relative_tolerance: float = 0.001,
    position_tolerance_mm: float = 0.05,
) -> GeometryResult:
    """Sort slices by physical position and validate a regular orthogonal stack."""
    if len(datasets) < 2:
        raise GeometryError("Для 3D-реконструкции требуется минимум два среза")

    first = datasets[0]
    rows = int(getattr(first, "Rows", 0) or 0)
    columns = int(getattr(first, "Columns", 0) or 0)
    if rows <= 0 or columns <= 0:
        raise GeometryError("Некорректные размеры изображения Rows/Columns")

    iop = _vector(first, "ImageOrientationPatient", 6)
    column_direction = iop[:3]
    row_direction = iop[3:]
    column_norm = np.linalg.norm(column_direction)
    row_norm = np.linalg.norm(row_direction)
    if (
        abs(column_norm - 1.0) > direction_tolerance
        or abs(row_norm - 1.0) > direction_tolerance
        or abs(float(np.dot(column_direction, row_direction))) > direction_tolerance
    ):
        raise GeometryError("ImageOrientationPatient не задаёт ортонормальный базис")
    column_direction = column_direction / column_norm
    row_direction = row_direction / row_norm
    normal = np.cross(column_direction, row_direction)
    normal /= np.linalg.norm(normal)

    pixel_spacing = _vector(first, "PixelSpacing", 2)
    if np.any(pixel_spacing <= 0):
        raise GeometryError("PixelSpacing должен содержать положительные значения")
    row_spacing, column_spacing = map(float, pixel_spacing)

    positions: list[np.ndarray] = []
    projections: list[float] = []
    frame_uid = str(getattr(first, "FrameOfReferenceUID", "") or "")
    if not frame_uid:
        raise GeometryError("Отсутствует FrameOfReferenceUID")

    for ds in datasets:
        if int(getattr(ds, "Rows", 0) or 0) != rows or int(
            getattr(ds, "Columns", 0) or 0
        ) != columns:
            raise GeometryError("Срезы имеют разные размеры")
        if str(getattr(ds, "FrameOfReferenceUID", "") or "") != frame_uid:
            raise GeometryError("Срезы относятся к разным FrameOfReferenceUID")
        current_iop = _vector(ds, "ImageOrientationPatient", 6)
        if not np.allclose(current_iop, iop, atol=direction_tolerance, rtol=0):
            raise GeometryError("Ориентация срезов меняется внутри стека")
        current_spacing = _vector(ds, "PixelSpacing", 2)
        if not np.allclose(current_spacing, pixel_spacing, atol=1e-6, rtol=1e-6):
            raise GeometryError("PixelSpacing меняется внутри стека")
        position = _vector(ds, "ImagePositionPatient", 3)
        positions.append(position)
        projections.append(float(np.dot(position, normal)))

    order_array = np.argsort(np.asarray(projections), kind="stable")
    sorted_positions = np.asarray([positions[index] for index in order_array])
    sorted_projections = np.asarray([projections[index] for index in order_array])
    differences = np.diff(sorted_projections)
    if np.any(differences <= position_tolerance_mm):
        raise GeometryError("Обнаружены повторяющиеся или перепутанные позиции срезов")
    slice_spacing = float(np.median(differences))
    spacing_tolerance = max(
        spacing_absolute_tolerance_mm, spacing_relative_tolerance * slice_spacing
    )
    if not np.allclose(differences, slice_spacing, atol=spacing_tolerance, rtol=0):
        raise GeometryError("Шаг между срезами неравномерен; интерполяция не выполняется")

    expected = sorted_positions[0] + np.arange(len(datasets))[:, None] * (
        slice_spacing * normal
    )
    residuals = np.linalg.norm(sorted_positions - expected, axis=1)
    if np.any(residuals > position_tolerance_mm):
        raise GeometryError("Стек имеет боковой сдвиг/gantry tilt и требует ресэмплинга")

    geometry = VolumeGeometry(
        spacing_zyx_mm=(slice_spacing, row_spacing, column_spacing),
        origin_lps_mm=sorted_positions[0].copy(),
        column_direction_lps=column_direction.copy(),
        row_direction_lps=row_direction.copy(),
        slice_direction_lps=normal.copy(),
    )
    return GeometryResult(tuple(int(index) for index in order_array), geometry)
