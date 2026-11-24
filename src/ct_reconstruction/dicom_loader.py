"""Discovery, grouping and loading of classic CT DICOM series."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

import numpy as np
import pydicom
from pydicom.dataset import Dataset

from .errors import DicomLoadError
from .geometry import analyze_geometry
from .hu import convert_slice_to_hu
from .models import CTVolume, StudyInfo

MAX_VOXELS = 300_000_000

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


def load_series(candidate: SeriesCandidate, *, version: int = 1) -> CTVolume:
    datasets: list[Dataset] = []
    study_uid = ""
    for path in candidate.files:
        try:
            ds = pydicom.dcmread(path, force=False)
        except Exception as exc:
            raise DicomLoadError(
                "Один из файлов выбранной серии повреждён или недоступен"
            ) from exc
        if str(getattr(ds, "SeriesInstanceUID", "") or "") != candidate.series_instance_uid:
            raise DicomLoadError("Файл не принадлежит выбранной серии")
        if str(getattr(ds, "FrameOfReferenceUID", "") or "") != candidate.frame_of_reference_uid:
            raise DicomLoadError("В серии обнаружен другой FrameOfReferenceUID")
        current_study_uid = str(getattr(ds, "StudyInstanceUID", "") or "")
        if not current_study_uid:
            raise DicomLoadError("Отсутствует StudyInstanceUID")
        if study_uid and current_study_uid != study_uid:
            raise DicomLoadError("В выбранном стеке смешаны разные StudyInstanceUID")
        study_uid = current_study_uid
        datasets.append(ds)
    geometry_result = analyze_geometry(datasets)
    voxel_count = len(datasets) * int(datasets[0].Rows) * int(datasets[0].Columns)
    if voxel_count > MAX_VOXELS:
        gib = voxel_count * 5 / (1024**3)
        raise DicomLoadError(
            f"Объём слишком велик для безопасной обработки (минимум около {gib:.1f} ГиБ)"
        )
    hu_slices: list[np.ndarray] = []
    valid_slices: list[np.ndarray] = []
    for index in geometry_result.order:
        hu, valid = convert_slice_to_hu(datasets[index])
        hu_slices.append(hu)
        valid_slices.append(valid)
    volume = np.stack(hu_slices).astype(np.float32, copy=False)
    valid_volume = np.stack(valid_slices).astype(np.bool_, copy=False)
    first = datasets[geometry_result.order[0]]
    return CTVolume(
        data_hu=volume,
        valid_voxels=valid_volume,
        geometry=geometry_result.geometry,
        study=_study_info(first),
        series_instance_uid=candidate.series_instance_uid,
        frame_of_reference_uid=candidate.frame_of_reference_uid,
        source_count=len(datasets),
        version=version,
    )
