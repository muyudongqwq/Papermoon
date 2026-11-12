"""Application entry point for the formal GM client."""

import sys

from PySide6.QtWidgets import QApplication, QMessageBox

from GameMasterClient import APPLICATION_NAME
from GameMasterClient.ui_build import ensure_generated_ui


def main():
    application = QApplication.instance() or QApplication(sys.argv)
    application.setApplicationName(APPLICATION_NAME)
    try:
        ensure_generated_ui()
        from GameMasterClient.window import GameMasterWindow
    except Exception as error:
        QMessageBox.critical(None, "Papermoon GM Client", f"界面文件更新失败：\n{error}")
        return 1
    window = GameMasterWindow()
    window.show()
    window.show_main_menu()
    return application.exec()

