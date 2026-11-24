from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from pydicom.dataset import FileDataset, FileMetaDataset
from pydicom.uid import CTImageStorage, ExplicitVRLittleEndian, generate_uid


@pytest.fixture
def ct_factory(tmp_path: Path):
    series_uid = generate_uid()
    study_uid = generate_uid()
    frame_uid = generate_uid()

    def create(
        name: str,
        pixels: np.ndarray,
        *,
        position=(0.0, 0.0, 0.0),
        orientation=(1.0, 0.0, 0.0, 0.0, 1.0, 0.0),
        spacing=(0.7, 0.8),
        slope=1.0,
        intercept=-1024.0,
        instance=1,
        current_series_uid=series_uid,
        current_frame_uid=frame_uid,
        padding=None,
        include_patient=True,
    ) -> Path:
        path = tmp_path / name
        meta = FileMetaDataset()
        meta.MediaStorageSOPClassUID = CTImageStorage
        meta.MediaStorageSOPInstanceUID = generate_uid()
        meta.TransferSyntaxUID = ExplicitVRLittleEndian
        meta.ImplementationClassUID = generate_uid()
        ds = FileDataset(str(path), {}, file_meta=meta, preamble=b"\0" * 128)
        ds.SOPClassUID = CTImageStorage
        ds.SOPInstanceUID = meta.MediaStorageSOPInstanceUID
        ds.StudyInstanceUID = study_uid
        ds.SeriesInstanceUID = current_series_uid
        ds.FrameOfReferenceUID = current_frame_uid
        ds.Modality = "CT"
        ds.ImageType = ["ORIGINAL", "PRIMARY", "AXIAL"]
        ds.MultienergyCTAcquisition = "NO"
        ds.Rows, ds.Columns = pixels.shape
        ds.ImagePositionPatient = list(position)
        ds.ImageOrientationPatient = list(orientation)
        ds.PixelSpacing = list(spacing)
        ds.SliceThickness = 5.0
        ds.InstanceNumber = instance
        ds.RescaleSlope = slope
        ds.RescaleIntercept = intercept
        ds.SamplesPerPixel = 1
        ds.PhotometricInterpretation = "MONOCHROME2"
        ds.BitsAllocated = 16
        ds.BitsStored = 16
        ds.HighBit = 15
        ds.PixelRepresentation = 1
        ds.SeriesDescription = "Synthetic CT"
        ds.StudyDescription = "Geometry test"
        ds.StudyDate = "20261124"
        if include_patient:
            ds.PatientName = "Test^Anonymous"
            ds.PatientID = "SYNTHETIC"
        if padding is not None:
            ds.PixelPaddingValue = int(padding)
        ds.PixelData = np.asarray(pixels, dtype=np.int16).tobytes()
        ds.save_as(path, enforce_file_format=True)
        return path

    create.series_uid = series_uid
    create.frame_uid = frame_uid
    return create

