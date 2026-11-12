# -*- coding: utf-8 -*-

################################################################################
## Form generated from reading UI file 'groupmanager.ui'
##
## Created by: Qt User Interface Compiler version 6.12.0
##
## WARNING! All changes made in this file will be lost when recompiling UI file!
################################################################################

from PySide6.QtCore import (QCoreApplication, QDate, QDateTime, QLocale,
    QMetaObject, QObject, QPoint, QRect,
    QSize, QTime, QUrl, Qt)
from PySide6.QtGui import (QBrush, QColor, QConicalGradient, QCursor,
    QFont, QFontDatabase, QGradient, QIcon,
    QImage, QKeySequence, QLinearGradient, QPainter,
    QPalette, QPixmap, QRadialGradient, QTransform)
from PySide6.QtWidgets import (QAbstractButton, QApplication, QDialog, QDialogButtonBox,
    QGridLayout, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QSizePolicy, QVBoxLayout, QWidget)

class Ui_groupEditorDialog(object):
    def setupUi(self, groupEditorDialog):
        if not groupEditorDialog.objectName():
            groupEditorDialog.setObjectName(u"groupEditorDialog")
        groupEditorDialog.resize(641, 521)
        self.verticalLayout_2 = QVBoxLayout(groupEditorDialog)
        self.verticalLayout_2.setObjectName(u"verticalLayout_2")
        self.verticalLayout = QVBoxLayout()
        self.verticalLayout.setObjectName(u"verticalLayout")
        self.gridLayout = QGridLayout()
        self.gridLayout.setObjectName(u"gridLayout")
        self.label = QLabel(groupEditorDialog)
        self.label.setObjectName(u"label")

        self.gridLayout.addWidget(self.label, 0, 0, 1, 1)

        self.groupNameEdit = QLineEdit(groupEditorDialog)
        self.groupNameEdit.setObjectName(u"groupNameEdit")

        self.gridLayout.addWidget(self.groupNameEdit, 0, 1, 1, 1)


        self.verticalLayout.addLayout(self.gridLayout)

        self.label_2 = QLabel(groupEditorDialog)
        self.label_2.setObjectName(u"label_2")

        self.verticalLayout.addWidget(self.label_2)

        self.groupMemberContent = QListWidget(groupEditorDialog)
        self.groupMemberContent.setObjectName(u"groupMemberContent")

        self.verticalLayout.addWidget(self.groupMemberContent)

        self.groupDialogButtons = QDialogButtonBox(groupEditorDialog)
        self.groupDialogButtons.setObjectName(u"groupDialogButtons")
        self.groupDialogButtons.setOrientation(Qt.Orientation.Horizontal)
        self.groupDialogButtons.setStandardButtons(QDialogButtonBox.StandardButton.Cancel|QDialogButtonBox.StandardButton.Ok)
        self.groupDialogButtons.setCenterButtons(False)

        self.verticalLayout.addWidget(self.groupDialogButtons)


        self.verticalLayout_2.addLayout(self.verticalLayout)


        self.retranslateUi(groupEditorDialog)
        self.groupDialogButtons.accepted.connect(groupEditorDialog.accept)
        self.groupDialogButtons.rejected.connect(groupEditorDialog.reject)

        QMetaObject.connectSlotsByName(groupEditorDialog)
    # setupUi

    def retranslateUi(self, groupEditorDialog):
        groupEditorDialog.setWindowTitle(QCoreApplication.translate("groupEditorDialog", u"\u5206\u7ec4\u7f16\u8f91", None))
        self.label.setText(QCoreApplication.translate("groupEditorDialog", u"\u5206\u7ec4\u540d\u79f0", None))
        self.label_2.setText(QCoreApplication.translate("groupEditorDialog", u"\u9009\u62e9\u6210\u5458", None))
    # retranslateUi

