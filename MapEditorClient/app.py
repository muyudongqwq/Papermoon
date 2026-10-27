"""Application entry point for the map editor."""

import sys

from PySide6.QtWidgets import QApplication

from MapEditorClient import APPLICATION_NAME
from MapEditorClient.window import MapEditorWindow


def main(path=None):
    application = QApplication.instance() or QApplication(sys.argv)
    application.setApplicationName(APPLICATION_NAME)
    window = MapEditorWindow(path)
    window.resize(1100, 720)
    window.show()
    return application.exec()

