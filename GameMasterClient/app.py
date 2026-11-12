"""Application entry point for the formal GM client."""

import sys

from PySide6.QtWidgets import QApplication

from GameMasterClient import APPLICATION_NAME
from GameMasterClient.window import GameMasterWindow


def main():
    application = QApplication.instance() or QApplication(sys.argv)
    application.setApplicationName(APPLICATION_NAME)
    window = GameMasterWindow()
    window.resize(1280, 800)
    window.show()
    return application.exec()

