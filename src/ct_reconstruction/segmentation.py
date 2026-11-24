"""Threshold and local-gradient region-growing segmentation."""

from __future__ import annotations

from collections import deque
from collections.abc import Callable

import numpy as np

from .errors import SegmentationError
from .models import CTVolume, Segmentation


def threshold_segmentation(
    volume: CTVolume, threshold_hu: float, *, version: int
) -> Segmentation:
    if not np.isfinite(threshold_hu):
        raise SegmentationError("Порог HU должен быть конечным числом")
    mask = volume.valid_voxels & (volume.data_hu >= float(threshold_hu))
    return Segmentation(
        mask=np.asarray(mask, dtype=np.bool_),
        method="threshold",
        parameters={"threshold_hu": float(threshold_hu)},
        volume_version=volume.version,
        version=version,
    )


def region_growing(
    volume: CTVolume,
    seed_zyx: tuple[int, int, int],
    tolerance_hu: float,
    *,
    version: int,
    cancelled: Callable[[], bool] | None = None,
    progress: Callable[[int], None] | None = None,
) -> Segmentation:
    """Grow a 6-connected region using local HU differences across each edge."""
    if not np.isfinite(tolerance_hu) or tolerance_hu < 0:
        raise SegmentationError("Чувствительность должна быть конечной и неотрицательной")
    shape = volume.data_hu.shape
    if len(seed_zyx) != 3 or any(i < 0 or i >= shape[axis] for axis, i in enumerate(seed_zyx)):
        raise SegmentationError("Исходная точка находится вне объёма")
    if not volume.valid_voxels[seed_zyx]:
        raise SegmentationError("Исходная точка попадает в недопустимый/padding-воксель")

    accepted = np.zeros(shape, dtype=np.bool_)
    accepted_flat = accepted.ravel()
    data_flat = volume.data_hu.ravel()
    valid_flat = volume.valid_voxels.ravel()
    _, rows, columns = shape
    plane_size = rows * columns
    seed_flat = (seed_zyx[0] * rows + seed_zyx[1]) * columns + seed_zyx[2]
    accepted_flat[seed_flat] = True
    # Flat integer indices keep the frontier substantially smaller than a deque
    # of Python (z, y, x) tuples for large homogeneous regions.
    queue: deque[int] = deque([seed_flat])
    processed = 0
    accepted_count = 1
    while queue:
        if cancelled is not None and processed % 4096 == 0 and cancelled():
            raise SegmentationError("Наращивание области отменено")
        point = queue.popleft()
        point_hu = float(data_flat[point])
        z, within_plane = divmod(point, plane_size)
        y, x = divmod(within_plane, columns)
        neighbors: list[int] = []
        if z:
            neighbors.append(point - plane_size)
        if z + 1 < shape[0]:
            neighbors.append(point + plane_size)
        if y:
            neighbors.append(point - columns)
        if y + 1 < rows:
            neighbors.append(point + columns)
        if x:
            neighbors.append(point - 1)
        if x + 1 < columns:
            neighbors.append(point + 1)
        for neighbor in neighbors:
            if accepted_flat[neighbor] or not valid_flat[neighbor]:
                continue
            if abs(float(data_flat[neighbor]) - point_hu) <= tolerance_hu:
                accepted_flat[neighbor] = True
                queue.append(neighbor)
                accepted_count += 1
        processed += 1
        if progress is not None and processed % 16384 == 0:
            progress(accepted_count)
    if progress is not None:
        progress(accepted_count)
    return Segmentation(
        mask=accepted,
        method="region_growing",
        parameters={"seed_zyx": seed_zyx, "tolerance_hu": float(tolerance_hu)},
        volume_version=volume.version,
        version=version,
    )
