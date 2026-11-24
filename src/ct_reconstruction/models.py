"""GUI-independent data contracts for CT reconstruction."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping

import numpy as np
from numpy.typing import NDArray

FloatArray = NDArray[np.floating]
BoolArray = NDArray[np.bool_]


@dataclass(frozen=True, slots=True)
class StudyInfo:
    study_date: str | None = None
    study_description: str | None = None
    modality: str | None = None
    series_description: str | None = None
    patient_name: str | None = None
    patient_id: str | None = None
    patient_birth_date: str | None = None
    patient_sex: str | None = None

    @staticmethod
    def display(value: str | None) -> str:
        return value.strip() if value and value.strip() else "Нет данных"


@dataclass(frozen=True, slots=True)
class VolumeGeometry:
    spacing_zyx_mm: tuple[float, float, float]
    origin_lps_mm: FloatArray
    column_direction_lps: FloatArray
    row_direction_lps: FloatArray
    slice_direction_lps: FloatArray

    def index_zyx_to_lps(self, indices: FloatArray) -> FloatArray:
        values = np.asarray(indices, dtype=np.float64)
        dz, dr, dc = self.spacing_zyx_mm
        return (
            self.origin_lps_mm
            + values[..., 0, None] * dz * self.slice_direction_lps
            + values[..., 1, None] * dr * self.row_direction_lps
            + values[..., 2, None] * dc * self.column_direction_lps
        )

    @property
    def direction_xyz(self) -> FloatArray:
        return np.column_stack(
            (self.column_direction_lps, self.row_direction_lps, self.slice_direction_lps)
        )


@dataclass(frozen=True, slots=True)
class CTVolume:
    data_hu: NDArray[np.float32]
    valid_voxels: BoolArray
    geometry: VolumeGeometry
    study: StudyInfo
    series_instance_uid: str
    frame_of_reference_uid: str
    source_count: int
    version: int = 1

    def __post_init__(self) -> None:
        if self.data_hu.ndim != 3 or self.data_hu.shape != self.valid_voxels.shape:
            raise ValueError("HU volume and validity mask must be equally shaped 3D arrays")
        if self.data_hu.dtype != np.float32:
            raise ValueError("HU volume must use float32")


@dataclass(frozen=True, slots=True)
class Segmentation:
    mask: BoolArray
    method: str
    parameters: Mapping[str, object]
    volume_version: int
    version: int

    def __post_init__(self) -> None:
        if self.mask.ndim != 3 or self.mask.dtype != np.bool_:
            raise ValueError("Segmentation mask must be a 3D boolean array")


@dataclass(slots=True)
class Mesh:
    vertices_lps_mm: NDArray[np.float64]
    faces: NDArray[np.int64]
    segmentation_version: int
    operations: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.vertices_lps_mm = np.asarray(self.vertices_lps_mm, dtype=np.float64)
        self.faces = np.asarray(self.faces, dtype=np.int64)
        if self.vertices_lps_mm.ndim != 2 or self.vertices_lps_mm.shape[1:] != (3,):
            raise ValueError("Mesh vertices must have shape (N, 3)")
        if self.faces.ndim != 2 or self.faces.shape[1:] != (3,):
            raise ValueError("Mesh faces must have shape (M, 3)")
        if not np.isfinite(self.vertices_lps_mm).all():
            raise ValueError("Mesh contains non-finite vertices")
        if self.faces.size and (
            self.faces.min() < 0 or self.faces.max() >= len(self.vertices_lps_mm)
        ):
            raise ValueError("Mesh faces contain invalid vertex indices")

    def copy(self) -> "Mesh":
        return Mesh(
            self.vertices_lps_mm.copy(), self.faces.copy(),
            self.segmentation_version, self.operations.copy()
        )

