"""VTK/PyVista widget for binary volume and triangulated surface display."""

from __future__ import annotations

import os
import numpy as np
import pyvista as pv
from PySide6.QtWidgets import QFrame, QVBoxLayout
from pyvistaqt import QtInteractor

from ..models import CTVolume, Mesh, Segmentation
from ..surface import to_pyvista


class Viewer3D(QFrame):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.plotter = QtInteractor(self)
        layout.addWidget(self.plotter.interactor)
        self.plotter.set_background("#0f172a")
        self.plotter.add_axes()
        self.current_mode = "empty"
        self._headless = os.environ.get("QT_QPA_PLATFORM", "").lower() == "offscreen"
        self._last_data = None

    def clear(self) -> None:
        self.plotter.clear()
        self.plotter.add_axes()
        self.current_mode = "empty"

    def show_mask(self, volume: CTVolume, segmentation: Segmentation) -> None:
        nz, ny, nx = segmentation.mask.shape
        dz, dr, dc = volume.geometry.spacing_zyx_mm
        grid = pv.ImageData(
            dimensions=(nx, ny, nz),
            spacing=(dc, dr, dz),
            origin=tuple(float(v) for v in volume.geometry.origin_lps_mm),
            direction_matrix=volume.geometry.direction_xyz,
        )
        grid.point_data["mask"] = segmentation.mask.ravel(order="C").astype(np.uint8)
        self._last_data = grid
        if self._headless:
            self.current_mode = "mask"
            return
        self.plotter.clear()
        actor = self.plotter.add_volume(
            grid,
            scalars="mask",
            opacity=[0.0, 0.85],
            cmap=["#0f172a", "#e2e8f0"],
            clim=(0, 1),
            shade=True,
            show_scalar_bar=False,
        )
        actor.prop.interpolation_type = "nearest"
        self.plotter.add_axes()
        self.plotter.reset_camera()
        self.current_mode = "mask"

    def show_mesh(self, mesh: Mesh) -> None:
        poly = to_pyvista(mesh)
        self._last_data = poly
        if self._headless:
            self.current_mode = "mesh"
            return
        self.plotter.clear()
        self.plotter.add_mesh(
            poly, color="#dbeafe", smooth_shading=True, show_edges=False
        )
        self.plotter.add_axes()
        self.plotter.reset_camera()
        self.current_mode = "mesh"

    def close_viewer(self) -> None:
        self.plotter.close()

