# -*- coding: utf-8 -*-

################################################################################
## Form generated from reading UI file 'mapeditor.ui'
##
## Created by: Qt User Interface Compiler version 6.12.0
##
## WARNING! All changes made in this file will be lost when recompiling UI file!
################################################################################

from PySide6.QtCore import (QCoreApplication, QDate, QDateTime, QLocale,
    QMetaObject, QObject, QPoint, QRect,
    QSize, QTime, QUrl, Qt)
from PySide6.QtGui import (QAction, QBrush, QColor, QConicalGradient,
    QCursor, QFont, QFontDatabase, QGradient,
    QIcon, QImage, QKeySequence, QLinearGradient,
    QPainter, QPalette, QPixmap, QRadialGradient,
    QTransform)
from PySide6.QtWidgets import (QApplication, QCheckBox, QFormLayout, QGraphicsView,
    QGroupBox, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QMainWindow, QMenuBar, QSizePolicy,
    QSpacerItem, QSplitter, QStatusBar, QToolBar,
    QVBoxLayout, QWidget)

class Ui_MainWindow(object):
    def setupUi(self, MainWindow):
        if not MainWindow.objectName():
            MainWindow.setObjectName(u"MainWindow")
        MainWindow.resize(800, 600)
        self.actionNewMap = QAction(MainWindow)
        self.actionNewMap.setObjectName(u"actionNewMap")
        self.actionNewMap.setMenuRole(QAction.MenuRole.NoRole)
        self.actionOpenMap = QAction(MainWindow)
        self.actionOpenMap.setObjectName(u"actionOpenMap")
        self.actionOpenMap.setMenuRole(QAction.MenuRole.NoRole)
        self.actionSaveMap = QAction(MainWindow)
        self.actionSaveMap.setObjectName(u"actionSaveMap")
        self.actionSaveMap.setMenuRole(QAction.MenuRole.NoRole)
        self.actionAddLocation = QAction(MainWindow)
        self.actionAddLocation.setObjectName(u"actionAddLocation")
        self.actionAddLocation.setMenuRole(QAction.MenuRole.NoRole)
        self.actionConnectRoad = QAction(MainWindow)
        self.actionConnectRoad.setObjectName(u"actionConnectRoad")
        self.actionConnectRoad.setMenuRole(QAction.MenuRole.NoRole)
        self.actionDeleteSelected = QAction(MainWindow)
        self.actionDeleteSelected.setObjectName(u"actionDeleteSelected")
        self.actionDeleteSelected.setMenuRole(QAction.MenuRole.NoRole)
        self.centralwidget = QWidget(MainWindow)
        self.centralwidget.setObjectName(u"centralwidget")
        self.verticalLayout = QVBoxLayout(self.centralwidget)
        self.verticalLayout.setObjectName(u"verticalLayout")
        self.mainSplitter = QSplitter(self.centralwidget)
        self.mainSplitter.setObjectName(u"mainSplitter")
        self.mainSplitter.setOrientation(Qt.Orientation.Horizontal)
        self.objectList = QListWidget(self.mainSplitter)
        self.objectList.setObjectName(u"objectList")
        self.objectList.setMinimumSize(QSize(160, 0))
        self.objectList.setMaximumSize(QSize(220, 16777215))
        self.mainSplitter.addWidget(self.objectList)
        self.mapView = QGraphicsView(self.mainSplitter)
        self.mapView.setObjectName(u"mapView")
        self.mainSplitter.addWidget(self.mapView)
        self.propertyPanel = QWidget(self.mainSplitter)
        self.propertyPanel.setObjectName(u"propertyPanel")
        self.verticalLayout_5 = QVBoxLayout(self.propertyPanel)
        self.verticalLayout_5.setObjectName(u"verticalLayout_5")
        self.selectionLabel = QLabel(self.propertyPanel)
        self.selectionLabel.setObjectName(u"selectionLabel")
        font = QFont()
        font.setPointSize(12)
        font.setBold(True)
        self.selectionLabel.setFont(font)

        self.verticalLayout_5.addWidget(self.selectionLabel)

        self.verticalLayout_4 = QVBoxLayout()
        self.verticalLayout_4.setObjectName(u"verticalLayout_4")
        self.locationPropertiesGroup = QGroupBox(self.propertyPanel)
        self.locationPropertiesGroup.setObjectName(u"locationPropertiesGroup")
        self.verticalLayout_3 = QVBoxLayout(self.locationPropertiesGroup)
        self.verticalLayout_3.setObjectName(u"verticalLayout_3")
        self.formLayout_2 = QFormLayout()
        self.formLayout_2.setObjectName(u"formLayout_2")
        self.nameLabel = QLabel(self.locationPropertiesGroup)
        self.nameLabel.setObjectName(u"nameLabel")

        self.formLayout_2.setWidget(0, QFormLayout.ItemRole.LabelRole, self.nameLabel)

        self.nameEdit = QLineEdit(self.locationPropertiesGroup)
        self.nameEdit.setObjectName(u"nameEdit")

        self.formLayout_2.setWidget(0, QFormLayout.ItemRole.FieldRole, self.nameEdit)

        self.buildingCheck = QCheckBox(self.locationPropertiesGroup)
        self.buildingCheck.setObjectName(u"buildingCheck")
        font1 = QFont()
        font1.setPointSize(10)
        self.buildingCheck.setFont(font1)

        self.formLayout_2.setWidget(1, QFormLayout.ItemRole.SpanningRole, self.buildingCheck)

        self.highLevelCheck = QCheckBox(self.locationPropertiesGroup)
        self.highLevelCheck.setObjectName(u"highLevelCheck")
        self.highLevelCheck.setFont(font1)

        self.formLayout_2.setWidget(2, QFormLayout.ItemRole.SpanningRole, self.highLevelCheck)

        self.portCheck = QCheckBox(self.locationPropertiesGroup)
        self.portCheck.setObjectName(u"portCheck")
        self.portCheck.setFont(font1)

        self.formLayout_2.setWidget(3, QFormLayout.ItemRole.SpanningRole, self.portCheck)


        self.verticalLayout_3.addLayout(self.formLayout_2)


        self.verticalLayout_4.addWidget(self.locationPropertiesGroup)

        self.roadPropertiesGroup = QGroupBox(self.propertyPanel)
        self.roadPropertiesGroup.setObjectName(u"roadPropertiesGroup")
        self.verticalLayout_2 = QVBoxLayout(self.roadPropertiesGroup)
        self.verticalLayout_2.setObjectName(u"verticalLayout_2")
        self.label = QLabel(self.roadPropertiesGroup)
        self.label.setObjectName(u"label")

        self.verticalLayout_2.addWidget(self.label)

        self.roadConnectionsList = QListWidget(self.roadPropertiesGroup)
        self.roadConnectionsList.setObjectName(u"roadConnectionsList")
        self.roadConnectionsList.setMinimumSize(QSize(80, 80))
        self.roadConnectionsList.setMaximumSize(QSize(120, 120))

        self.verticalLayout_2.addWidget(self.roadConnectionsList)


        self.verticalLayout_4.addWidget(self.roadPropertiesGroup)


        self.verticalLayout_5.addLayout(self.verticalLayout_4)

        self.verticalSpacer = QSpacerItem(28, 164, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding)

        self.verticalLayout_5.addItem(self.verticalSpacer)

        self.mainSplitter.addWidget(self.propertyPanel)

        self.verticalLayout.addWidget(self.mainSplitter)

        MainWindow.setCentralWidget(self.centralwidget)
        self.menubar = QMenuBar(MainWindow)
        self.menubar.setObjectName(u"menubar")
        self.menubar.setGeometry(QRect(0, 0, 800, 22))
        MainWindow.setMenuBar(self.menubar)
        self.statusbar = QStatusBar(MainWindow)
        self.statusbar.setObjectName(u"statusbar")
        MainWindow.setStatusBar(self.statusbar)
        self.mainToolBar = QToolBar(MainWindow)
        self.mainToolBar.setObjectName(u"mainToolBar")
        MainWindow.addToolBar(Qt.ToolBarArea.TopToolBarArea, self.mainToolBar)

        self.mainToolBar.addAction(self.actionNewMap)
        self.mainToolBar.addAction(self.actionOpenMap)
        self.mainToolBar.addAction(self.actionSaveMap)
        self.mainToolBar.addAction(self.actionAddLocation)
        self.mainToolBar.addAction(self.actionConnectRoad)
        self.mainToolBar.addAction(self.actionDeleteSelected)

        self.retranslateUi(MainWindow)

        QMetaObject.connectSlotsByName(MainWindow)
    # setupUi

    def retranslateUi(self, MainWindow):
        MainWindow.setWindowTitle(QCoreApplication.translate("MainWindow", u"MainWindow", None))
        self.actionNewMap.setText(QCoreApplication.translate("MainWindow", u"\u65b0\u5730\u56fe", None))
        self.actionOpenMap.setText(QCoreApplication.translate("MainWindow", u"\u6253\u5f00", None))
        self.actionSaveMap.setText(QCoreApplication.translate("MainWindow", u"\u4fdd\u5b58", None))
        self.actionAddLocation.setText(QCoreApplication.translate("MainWindow", u"\u65b0\u5efa\u5730\u70b9", None))
        self.actionConnectRoad.setText(QCoreApplication.translate("MainWindow", u"\u8fde\u63a5\u9053\u8def", None))
#if QT_CONFIG(tooltip)
        self.actionConnectRoad.setToolTip(QCoreApplication.translate("MainWindow", u"\u81ea\u52a8\u8fde\u63a5\u65b0\u5efa\u7684\u8282\u70b9\u4e0e\u4e0a\u4e00\u4e2a\u8282\u70b9", None))
#endif // QT_CONFIG(tooltip)
        self.actionDeleteSelected.setText(QCoreApplication.translate("MainWindow", u"\u5220\u9664\u9009\u4e2d", None))
#if QT_CONFIG(tooltip)
        self.actionDeleteSelected.setToolTip(QCoreApplication.translate("MainWindow", u"\u5220\u9664\u5f53\u524d\u9009\u4e2d\u7684\u5730\u70b9\u6216\u9053\u8def", None))
#endif // QT_CONFIG(tooltip)
#if QT_CONFIG(shortcut)
        self.actionDeleteSelected.setShortcut(QCoreApplication.translate("MainWindow", u"Del", None))
#endif // QT_CONFIG(shortcut)
        self.selectionLabel.setText(QCoreApplication.translate("MainWindow", u"\u672a\u9009\u62e9\u5730\u56fe\u5bf9\u8c61", None))
        self.locationPropertiesGroup.setTitle(QCoreApplication.translate("MainWindow", u"\u5730\u70b9\u5c5e\u6027", None))
        self.nameLabel.setText(QCoreApplication.translate("MainWindow", u"\u540d\u79f0", None))
        self.buildingCheck.setText(QCoreApplication.translate("MainWindow", u"\u662f\u5426\u5efa\u7b51", None))
        self.highLevelCheck.setText(QCoreApplication.translate("MainWindow", u"\u662f\u5426\u5177\u6709\u9ad8\u5c42", None))
        self.portCheck.setText(QCoreApplication.translate("MainWindow", u"\u662f\u5426\u7801\u5934", None))
        self.roadPropertiesGroup.setTitle(QCoreApplication.translate("MainWindow", u"\u9053\u8def\u5c5e\u6027", None))
        self.label.setText(QCoreApplication.translate("MainWindow", u"\u8fde\u63a5\u5730\u70b9", None))
        self.mainToolBar.setWindowTitle(QCoreApplication.translate("MainWindow", u"toolBar", None))
    # retranslateUi

