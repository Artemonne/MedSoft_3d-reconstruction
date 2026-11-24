"""Clickable axial slice view used to choose a Region Growing seed."""

from __future__ import annotations

import numpy as np
from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtGui import QImage, QMouseEvent, QPixmap
from PySide6.QtWidgets import QLabel


class SliceView(QLabel):
    seed_selected = Signal(int, int)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setMinimumSize(260, 220)
        self.setStyleSheet("background:#111827; color:#94a3b8; border:1px solid #334155")
        self.setText("2D-срез появится после загрузки")
        self._image: QImage | None = None
        self._display_rect = (0, 0, 0, 0)
        self._seed_yx: tuple[int, int] | None = None

    def set_slice(self, values: np.ndarray, seed_yx: tuple[int, int] | None = None) -> None:
        finite = np.asarray(values, dtype=np.float32)
        low, high = -1000.0, 1000.0
        normalized = np.clip((finite - low) / (high - low), 0, 1)
        pixels = np.nan_to_num(normalized * 255, nan=0).astype(np.uint8)
        height, width = pixels.shape
        self._image = QImage(
            pixels.data, width, height, int(pixels.strides[0]), QImage.Format.Format_Grayscale8
        ).copy()
        self._seed_yx = seed_yx
        self._render()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._render()

    def _render(self) -> None:
        if self._image is None:
            return
        pixmap = QPixmap.fromImage(self._image).scaled(
            self.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation
        )
        if self._seed_yx is not None:
            from PySide6.QtGui import QColor, QPainter, QPen

            painter = QPainter(pixmap)
            painter.setPen(QPen(QColor("#ef4444"), 2))
            y, x = self._seed_yx
            px = x * pixmap.width() / self._image.width()
            py = y * pixmap.height() / self._image.height()
            painter.drawLine(int(px - 7), int(py), int(px + 7), int(py))
            painter.drawLine(int(px), int(py - 7), int(px), int(py + 7))
            painter.end()
        left = (self.width() - pixmap.width()) // 2
        top = (self.height() - pixmap.height()) // 2
        self._display_rect = (left, top, pixmap.width(), pixmap.height())
        self.setPixmap(pixmap)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if self._image is None or event.button() != Qt.MouseButton.LeftButton:
            return super().mousePressEvent(event)
        left, top, width, height = self._display_rect
        point: QPoint = event.position().toPoint()
        if not (left <= point.x() < left + width and top <= point.y() < top + height):
            return
        x = min(self._image.width() - 1, int((point.x() - left) * self._image.width() / width))
        y = min(self._image.height() - 1, int((point.y() - top) * self._image.height() / height))
        self.seed_selected.emit(y, x)

