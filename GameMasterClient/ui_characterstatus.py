# -*- coding: utf-8 -*-

################################################################################
## Form generated from reading UI file 'characterstatus.ui'
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
from PySide6.QtWidgets import (QApplication, QDialog, QGridLayout, QHBoxLayout,
    QLabel, QListWidget, QListWidgetItem, QProgressBar,
    QPushButton, QScrollArea, QSizePolicy, QSpacerItem,
    QSplitter, QStackedWidget, QVBoxLayout, QWidget)

class Ui_characterStatusDialog(object):
    def setupUi(self, characterStatusDialog):
        if not characterStatusDialog.objectName():
            characterStatusDialog.setObjectName(u"characterStatusDialog")
        characterStatusDialog.resize(598, 444)
        self.verticalLayout_3 = QVBoxLayout(characterStatusDialog)
        self.verticalLayout_3.setObjectName(u"verticalLayout_3")
        self.splitter = QSplitter(characterStatusDialog)
        self.splitter.setObjectName(u"splitter")
        self.splitter.setOrientation(Qt.Orientation.Horizontal)
        self.splitter.setChildrenCollapsible(False)
        self.characterSummaryPanel = QWidget(self.splitter)
        self.characterSummaryPanel.setObjectName(u"characterSummaryPanel")
        self.characterSummaryPanel.setMinimumSize(QSize(360, 0))
        self.verticalLayout = QVBoxLayout(self.characterSummaryPanel)
        self.verticalLayout.setObjectName(u"verticalLayout")
        self.verticalLayout.setContentsMargins(0, 0, 0, 0)
        self.characterNameLabel = QLabel(self.characterSummaryPanel)
        self.characterNameLabel.setObjectName(u"characterNameLabel")

        self.verticalLayout.addWidget(self.characterNameLabel)

        self.horizontalLayout_3 = QHBoxLayout()
        self.horizontalLayout_3.setObjectName(u"horizontalLayout_3")
        self.hpLabel = QLabel(self.characterSummaryPanel)
        self.hpLabel.setObjectName(u"hpLabel")

        self.horizontalLayout_3.addWidget(self.hpLabel)

        self.hpProgressBar = QProgressBar(self.characterSummaryPanel)
        self.hpProgressBar.setObjectName(u"hpProgressBar")
        self.hpProgressBar.setValue(24)

        self.horizontalLayout_3.addWidget(self.hpProgressBar)


        self.verticalLayout.addLayout(self.horizontalLayout_3)

        self.horizontalLayout_2 = QHBoxLayout()
        self.horizontalLayout_2.setObjectName(u"horizontalLayout_2")
        self.mpLabel = QLabel(self.characterSummaryPanel)
        self.mpLabel.setObjectName(u"mpLabel")

        self.horizontalLayout_2.addWidget(self.mpLabel)

        self.mpProgressBar = QProgressBar(self.characterSummaryPanel)
        self.mpProgressBar.setObjectName(u"mpProgressBar")
        self.mpProgressBar.setValue(24)

        self.horizontalLayout_2.addWidget(self.mpProgressBar)


        self.verticalLayout.addLayout(self.horizontalLayout_2)

        self.horizontalLayout = QHBoxLayout()
        self.horizontalLayout.setObjectName(u"horizontalLayout")
        self.locationLabel = QLabel(self.characterSummaryPanel)
        self.locationLabel.setObjectName(u"locationLabel")

        self.horizontalLayout.addWidget(self.locationLabel)

        self.phaseLabel = QLabel(self.characterSummaryPanel)
        self.phaseLabel.setObjectName(u"phaseLabel")

        self.horizontalLayout.addWidget(self.phaseLabel)


        self.verticalLayout.addLayout(self.horizontalLayout)

        self.isBattleLabel = QLabel(self.characterSummaryPanel)
        self.isBattleLabel.setObjectName(u"isBattleLabel")
        self.isBattleLabel.setMinimumSize(QSize(0, 75))

        self.verticalLayout.addWidget(self.isBattleLabel)

        self.splitter.addWidget(self.characterSummaryPanel)
        self.statusListWidget = QListWidget(self.splitter)
        self.statusListWidget.setObjectName(u"statusListWidget")
        self.statusListWidget.setMinimumSize(QSize(110, 0))
        self.statusListWidget.setMaximumSize(QSize(145, 16777215))
        self.splitter.addWidget(self.statusListWidget)

        self.verticalLayout_3.addWidget(self.splitter)

        self.horizontalLayout_4 = QHBoxLayout()
        self.horizontalLayout_4.setObjectName(u"horizontalLayout_4")
        self.actionScrollArea = QScrollArea(characterStatusDialog)
        self.actionScrollArea.setObjectName(u"actionScrollArea")
        self.actionScrollArea.setWidgetResizable(True)
        self.actionButtonContents = QWidget()
        self.actionButtonContents.setObjectName(u"actionButtonContents")
        self.actionButtonContents.setGeometry(QRect(0, 0, 243, 224))
        self.actionButtonLayout = QGridLayout(self.actionButtonContents)
        self.actionButtonLayout.setObjectName(u"actionButtonLayout")
        self.verticalSpacer = QSpacerItem(20, 40, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding)

        self.actionButtonLayout.addItem(self.verticalSpacer, 0, 0, 1, 1)

        self.verticalSpacer_2 = QSpacerItem(20, 40, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding)

        self.actionButtonLayout.addItem(self.verticalSpacer_2, 0, 1, 1, 1)

        self.actionScrollArea.setWidget(self.actionButtonContents)

        self.horizontalLayout_4.addWidget(self.actionScrollArea)

        self.actionDetailStack = QStackedWidget(characterStatusDialog)
        self.actionDetailStack.setObjectName(u"actionDetailStack")
        self.actionEmptyPage = QWidget()
        self.actionEmptyPage.setObjectName(u"actionEmptyPage")
        self.actionDetailStack.addWidget(self.actionEmptyPage)
        self.actionDetailPage = QWidget()
        self.actionDetailPage.setObjectName(u"actionDetailPage")
        self.actionDetailStack.addWidget(self.actionDetailPage)

        self.horizontalLayout_4.addWidget(self.actionDetailStack)

        self.verticalLayout_2 = QVBoxLayout()
        self.verticalLayout_2.setObjectName(u"verticalLayout_2")
        self.verticalSpacer_3 = QSpacerItem(20, 40, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding)

        self.verticalLayout_2.addItem(self.verticalSpacer_3)

        self.closeButton = QPushButton(characterStatusDialog)
        self.closeButton.setObjectName(u"closeButton")

        self.verticalLayout_2.addWidget(self.closeButton)


        self.horizontalLayout_4.addLayout(self.verticalLayout_2)


        self.verticalLayout_3.addLayout(self.horizontalLayout_4)


        self.retranslateUi(characterStatusDialog)

        QMetaObject.connectSlotsByName(characterStatusDialog)
    # setupUi

    def retranslateUi(self, characterStatusDialog):
        characterStatusDialog.setWindowTitle(QCoreApplication.translate("characterStatusDialog", u"\u89d2\u8272\u72b6\u6001", None))
        self.characterNameLabel.setText(QCoreApplication.translate("characterStatusDialog", u"TextLabel", None))
        self.hpLabel.setText(QCoreApplication.translate("characterStatusDialog", u"TextLabel", None))
        self.mpLabel.setText(QCoreApplication.translate("characterStatusDialog", u"TextLabel", None))
        self.locationLabel.setText(QCoreApplication.translate("characterStatusDialog", u"TextLabel", None))
        self.phaseLabel.setText(QCoreApplication.translate("characterStatusDialog", u"TextLabel", None))
        self.isBattleLabel.setText(QCoreApplication.translate("characterStatusDialog", u"TextLabel", None))
        self.closeButton.setText(QCoreApplication.translate("characterStatusDialog", u"\u5173\u95ed", None))
    # retranslateUi

