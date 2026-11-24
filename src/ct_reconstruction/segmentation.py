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
    accepted[seed_zyx] = True
    queue: deque[tuple[int, int, int]] = deque([seed_zyx])
    processed = 0
    offsets = ((-1, 0, 0), (1, 0, 0), (0, -1, 0), (0, 1, 0), (0, 0, -1), (0, 0, 1))
    while queue:
        if cancelled is not None and processed % 4096 == 0 and cancelled():
            raise SegmentationError("Наращивание области отменено")
        point = queue.popleft()
        point_hu = float(volume.data_hu[point])
        for dz, dy, dx in offsets:
            neighbor = (point[0] + dz, point[1] + dy, point[2] + dx)
            if any(neighbor[axis] < 0 or neighbor[axis] >= shape[axis] for axis in range(3)):
                continue
            if accepted[neighbor] or not volume.valid_voxels[neighbor]:
                continue
            if abs(float(volume.data_hu[neighbor]) - point_hu) <= tolerance_hu:
                accepted[neighbor] = True
                queue.append(neighbor)
        processed += 1
        if progress is not None and processed % 16384 == 0:
            progress(int(accepted.sum()))
    return Segmentation(
        mask=accepted,
        method="region_growing",
        parameters={"seed_zyx": seed_zyx, "tolerance_hu": float(tolerance_hu)},
        volume_version=volume.version,
        version=version,
    )
