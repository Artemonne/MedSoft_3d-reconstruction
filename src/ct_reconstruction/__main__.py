"""Application entry point."""

from __future__ import annotations

import os
import sys
import multiprocessing


def main() -> int:
    multiprocessing.freeze_support()
    os.environ.setdefault("QT_API", "pyside6")
    from PySide6.QtWidgets import QApplication

    from .ui.main_window import MainWindow

    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("КТ 3D — лабораторная № 5")
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())

