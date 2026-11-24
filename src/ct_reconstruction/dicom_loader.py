"""Discovery, grouping and loading of classic CT DICOM series."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import numpy as np
import pydicom
from pydicom.dataset import Dataset

from .errors import DicomLoadError
from .geometry import analyze_geometry
from .hu import convert_slice_to_hu
from .models import CTVolume, StudyInfo

MAX_VOXELS = 300_000_000
LOAD_BYTES_PER_VOXEL = np.dtype(np.float32).itemsize + np.dtype(np.bool_).itemsize
AVAILABLE_MEMORY_FRACTION = 0.60

@dataclass(frozen=True, slots=True)
class SeriesCandidate:
    series_instance_uid: str
    frame_of_reference_uid: str
    description: str
    files: tuple[Path, ...]

    @property
    def display_name(self) -> str:
        text = self.description.strip() or "Без описания"
        return f"{text} — {len(self.files)} срезов"


def expand_input_paths(paths: Iterable[str | Path]) -> tuple[Path, ...]:
    files: list[Path] = []
    for raw in paths:
        path = Path(raw)
        if path.is_dir():
            files.extend(item for item in path.rglob("*") if item.is_file())
        elif path.is_file():
            files.append(path)
    return tuple(dict.fromkeys(files))


def discover_series(paths: Iterable[str | Path]) -> tuple[SeriesCandidate, ...]:
    """Read metadata only and group CT images by series and frame of reference."""
    groups: dict[tuple[str, str], list[tuple[Path, Dataset]]] = {}
    for path in expand_input_paths(paths):
        try:
            ds = pydicom.dcmread(path, stop_before_pixels=True, force=False)
        except Exception:
            continue
        if str(getattr(ds, "Modality", "")).upper() != "CT":
            continue
        series_uid = str(getattr(ds, "SeriesInstanceUID", "") or "")
        frame_uid = str(getattr(ds, "FrameOfReferenceUID", "") or "")
        if not series_uid or not frame_uid:
            continue
        groups.setdefault((series_uid, frame_uid), []).append((path, ds))
    candidates = []
    for (series_uid, frame_uid), entries in groups.items():
        description = str(getattr(entries[0][1], "SeriesDescription", "") or "")
        candidates.append(
            SeriesCandidate(series_uid, frame_uid, description, tuple(p for p, _ in entries))
        )
    return tuple(sorted(candidates, key=lambda item: item.display_name.casefold()))


def _optional_text(ds: Dataset, name: str) -> str | None:
    value = getattr(ds, name, None)
    text = str(value).strip() if value is not None else ""
    return text or None


def _study_info(ds: Dataset) -> StudyInfo:
    return StudyInfo(
        study_date=_optional_text(ds, "StudyDate"),
        study_description=_optional_text(ds, "StudyDescription"),
        modality=_optional_text(ds, "Modality"),
        series_description=_optional_text(ds, "SeriesDescription"),
        patient_name=_optional_text(ds, "PatientName"),
        patient_id=_optional_text(ds, "PatientID"),
        patient_birth_date=_optional_text(ds, "PatientBirthDate"),
        patient_sex=_optional_text(ds, "PatientSex"),
    )


def _available_memory_bytes() -> int | None:
    """Return currently available physical memory on Windows without a dependency."""
    try:
        import ctypes

        class MemoryStatus(ctypes.Structure):
            _fields_ = [
                ("length", ctypes.c_ulong),
                ("memory_load", ctypes.c_ulong),
                ("total_physical", ctypes.c_ulonglong),
                ("available_physical", ctypes.c_ulonglong),
                ("total_page_file", ctypes.c_ulonglong),
                ("available_page_file", ctypes.c_ulonglong),
                ("total_virtual", ctypes.c_ulonglong),
                ("available_virtual", ctypes.c_ulonglong),
                ("available_extended_virtual", ctypes.c_ulonglong),
            ]

        status = MemoryStatus()
        status.length = ctypes.sizeof(status)
        if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            return None
        return int(status.available_physical)
    except (AttributeError, OSError):
        return None


def _check_volume_allocation(voxel_count: int, slice_voxels: int) -> None:
    if voxel_count > MAX_VOXELS:
        gib = voxel_count * LOAD_BYTES_PER_VOXEL / (1024**3)
        raise DicomLoadError(
            f"Объём слишком велик для безопасной обработки (только HU и маска "
            f"валидности займут около {gib:.1f} ГиБ)"
        )

    # The final arrays use five bytes per voxel.  One decoded slice is converted
    # through float64 and float32 temporary arrays; keeping this workspace per
    # slice is the reason the loader deliberately does not retain PixelData for
    # the complete series.
    estimated_peak = voxel_count * LOAD_BYTES_PER_VOXEL + slice_voxels * 16
    available = _available_memory_bytes()
    if available is not None and estimated_peak > available * AVAILABLE_MEMORY_FRACTION:
        needed_gib = estimated_peak / (1024**3)
        available_gib = available / (1024**3)
        raise DicomLoadError(
            "Недостаточно свободной памяти для безопасной загрузки: "
            f"нужно около {needed_gib:.1f} ГиБ, доступно {available_gib:.1f} ГиБ"
        )


def _validate_series_identity(
    ds: Dataset, candidate: SeriesCandidate, expected_study_uid: str
) -> str:
    if str(getattr(ds, "SeriesInstanceUID", "") or "") != candidate.series_instance_uid:
        raise DicomLoadError("Файл не принадлежит выбранной серии")
    if str(getattr(ds, "FrameOfReferenceUID", "") or "") != candidate.frame_of_reference_uid:
        raise DicomLoadError("В серии обнаружен другой FrameOfReferenceUID")
    study_uid = str(getattr(ds, "StudyInstanceUID", "") or "")
    if not study_uid:
        raise DicomLoadError("Отсутствует StudyInstanceUID")
    if expected_study_uid and study_uid != expected_study_uid:
        raise DicomLoadError("В выбранном стеке смешаны разные StudyInstanceUID")
    return study_uid


def load_series(candidate: SeriesCandidate, *, version: int = 1) -> CTVolume:
    if not candidate.files:
        raise DicomLoadError("Выбранная серия не содержит файлов")

    # First pass reads metadata only.  Geometry must be validated before any
    # large volume allocation, and PixelData for all slices must never be kept
    # alive at once.
    metadata: list[Dataset] = []
    study_uid = ""
    for path in candidate.files:
        try:
            ds = pydicom.dcmread(path, stop_before_pixels=True, force=False)
        except Exception as exc:
            raise DicomLoadError(
                "Один из файлов выбранной серии повреждён или недоступен"
            ) from exc
        study_uid = _validate_series_identity(ds, candidate, study_uid)
        metadata.append(ds)

    geometry_result = analyze_geometry(metadata)
    rows = int(metadata[0].Rows)
    columns = int(metadata[0].Columns)
    slice_voxels = rows * columns
    voxel_count = len(metadata) * slice_voxels
    _check_volume_allocation(voxel_count, slice_voxels)

    volume = np.empty((len(metadata), rows, columns), dtype=np.float32)
    valid_volume = np.empty((len(metadata), rows, columns), dtype=np.bool_)
    for output_index, source_index in enumerate(geometry_result.order):
        path = candidate.files[source_index]
        try:
            ds = pydicom.dcmread(path, force=False)
        except Exception as exc:
            raise DicomLoadError(
                "Один из файлов выбранной серии повреждён или недоступен"
            ) from exc
        _validate_series_identity(ds, candidate, study_uid)
        hu, valid = convert_slice_to_hu(ds)
        if hu.shape != (rows, columns) or valid.shape != (rows, columns):
            raise DicomLoadError("Размер декодированного среза не совпадает с метаданными")
        volume[output_index] = hu
        valid_volume[output_index] = valid

    first = metadata[geometry_result.order[0]]
    return CTVolume(
        data_hu=volume,
        valid_voxels=valid_volume,
        geometry=geometry_result.geometry,
        study=_study_info(first),
        series_instance_uid=candidate.series_instance_uid,
        frame_of_reference_uid=candidate.frame_of_reference_uid,
        source_count=len(metadata),
        version=version,
    )
