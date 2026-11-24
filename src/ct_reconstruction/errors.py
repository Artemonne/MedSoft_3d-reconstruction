"""Domain errors shown to users without exposing patient data or paths."""


class CTReconstructionError(Exception):
    """Base class for expected application errors."""


class DicomLoadError(CTReconstructionError):
    """A DICOM file or series cannot be read safely."""


class GeometryError(CTReconstructionError):
    """Slice geometry cannot form a trustworthy 3D volume."""


class HounsfieldError(CTReconstructionError):
    """Pixel values cannot be confirmed or converted to HU."""


class SegmentationError(CTReconstructionError):
    """Segmentation parameters or results are invalid."""


class MeshError(CTReconstructionError):
    """A surface operation cannot produce a valid mesh."""

