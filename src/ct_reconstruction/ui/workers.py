"""Small QRunnable wrapper used for GUI-independent background calculations."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QObject, QRunnable, Signal, Slot


class TaskSignals(QObject):
    succeeded = Signal(int, object)
    failed = Signal(int, str)
    finished = Signal(int)


class TaskRunner(QRunnable):
    def __init__(self, token: int, function: Callable[[], Any]) -> None:
        super().__init__()
        self.token = token
        self.function = function
        self.signals = TaskSignals()

    @Slot()
    def run(self) -> None:
        try:
            result = self.function()
        except Exception as exc:
            self.signals.failed.emit(self.token, str(exc))
        else:
            self.signals.succeeded.emit(self.token, result)
        finally:
            self.signals.finished.emit(self.token)
