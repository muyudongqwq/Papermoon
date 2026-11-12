# -*- coding: utf-8 -*-

################################################################################
## Form generated from reading UI file 'gamemaster.ui'
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
from PySide6.QtWidgets import (QApplication, QComboBox, QFormLayout, QFrame,
    QGraphicsView, QGridLayout, QGroupBox, QHBoxLayout,
    QHeaderView, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QMainWindow, QMenuBar, QPushButton,
    QScrollArea, QSizePolicy, QSpacerItem, QSpinBox,
    QSplitter, QStackedWidget, QStatusBar, QTableWidget,
    QTableWidgetItem, QTextEdit, QVBoxLayout, QWidget)

class Ui_MainWindow(object):
    def setupUi(self, MainWindow):
        if not MainWindow.objectName():
            MainWindow.setObjectName(u"MainWindow")
        MainWindow.resize(836, 745)
        self.centralwidget = QWidget(MainWindow)
        self.centralwidget.setObjectName(u"centralwidget")
        self.verticalLayout = QVBoxLayout(self.centralwidget)
        self.verticalLayout.setObjectName(u"verticalLayout")
        self.mainStack = QStackedWidget(self.centralwidget)
        self.mainStack.setObjectName(u"mainStack")
        self.mainMenuPage = QWidget()
        self.mainMenuPage.setObjectName(u"mainMenuPage")
        self.label = QLabel(self.mainMenuPage)
        self.label.setObjectName(u"label")
        self.label.setGeometry(QRect(10, 10, 131, 41))
        font = QFont()
        font.setPointSize(16)
        self.label.setFont(font)
        self.layoutWidget = QWidget(self.mainMenuPage)
        self.layoutWidget.setObjectName(u"layoutWidget")
        self.layoutWidget.setGeometry(QRect(7, 63, 831, 521))
        self.horizontalLayout_4 = QHBoxLayout(self.layoutWidget)
        self.horizontalLayout_4.setObjectName(u"horizontalLayout_4")
        self.horizontalLayout_4.setContentsMargins(0, 0, 0, 0)
        self.horizontalSpacer_7 = QSpacerItem(40, 20, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        self.horizontalLayout_4.addItem(self.horizontalSpacer_7)

        self.horizontalLayout_2 = QHBoxLayout()
        self.horizontalLayout_2.setObjectName(u"horizontalLayout_2")
        self.horizontalSpacer = QSpacerItem(40, 20, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        self.horizontalLayout_2.addItem(self.horizontalSpacer)

        self.mainMenuPanel = QFrame(self.layoutWidget)
        self.mainMenuPanel.setObjectName(u"mainMenuPanel")
        self.mainMenuPanel.setMinimumSize(QSize(240, 360))
        self.mainMenuPanel.setFrameShape(QFrame.Shape.StyledPanel)
        self.mainMenuPanel.setFrameShadow(QFrame.Shadow.Raised)
        self.verticalLayout_2 = QVBoxLayout(self.mainMenuPanel)
        self.verticalLayout_2.setObjectName(u"verticalLayout_2")
        self.newGameButton = QPushButton(self.mainMenuPanel)
        self.newGameButton.setObjectName(u"newGameButton")
        self.newGameButton.setMinimumSize(QSize(220, 42))
        font1 = QFont()
        font1.setPointSize(12)
        font1.setBold(True)
        self.newGameButton.setFont(font1)

        self.verticalLayout_2.addWidget(self.newGameButton)

        self.loadGameButton = QPushButton(self.mainMenuPanel)
        self.loadGameButton.setObjectName(u"loadGameButton")
        self.loadGameButton.setMinimumSize(QSize(220, 42))
        self.loadGameButton.setFont(font1)

        self.verticalLayout_2.addWidget(self.loadGameButton)

        self.exitButton = QPushButton(self.mainMenuPanel)
        self.exitButton.setObjectName(u"exitButton")
        self.exitButton.setMinimumSize(QSize(220, 42))
        self.exitButton.setFont(font1)

        self.verticalLayout_2.addWidget(self.exitButton)


        self.horizontalLayout_2.addWidget(self.mainMenuPanel)

        self.horizontalSpacer_2 = QSpacerItem(40, 20, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        self.horizontalLayout_2.addItem(self.horizontalSpacer_2)


        self.horizontalLayout_4.addLayout(self.horizontalLayout_2)

        self.horizontalSpacer_8 = QSpacerItem(40, 20, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        self.horizontalLayout_4.addItem(self.horizontalSpacer_8)

        self.mainStack.addWidget(self.mainMenuPage)
        self.setupPage = QWidget()
        self.setupPage.setObjectName(u"setupPage")
        self.verticalLayout_7 = QVBoxLayout(self.setupPage)
        self.verticalLayout_7.setObjectName(u"verticalLayout_7")
        self.horizontalLayout = QHBoxLayout()
        self.horizontalLayout.setObjectName(u"horizontalLayout")
        self.verticalLayout_3 = QVBoxLayout()
        self.verticalLayout_3.setObjectName(u"verticalLayout_3")
        self.backToMenuButton = QPushButton(self.setupPage)
        self.backToMenuButton.setObjectName(u"backToMenuButton")
        font2 = QFont()
        font2.setPointSize(12)
        self.backToMenuButton.setFont(font2)

        self.verticalLayout_3.addWidget(self.backToMenuButton)

        self.setupTitleLabel = QLabel(self.setupPage)
        self.setupTitleLabel.setObjectName(u"setupTitleLabel")
        self.setupTitleLabel.setFont(font1)

        self.verticalLayout_3.addWidget(self.setupTitleLabel)


        self.horizontalLayout.addLayout(self.verticalLayout_3)

        self.horizontalSpacer_3 = QSpacerItem(761, 20, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        self.horizontalLayout.addItem(self.horizontalSpacer_3)


        self.verticalLayout_7.addLayout(self.horizontalLayout)

        self.setupScrollArea = QScrollArea(self.setupPage)
        self.setupScrollArea.setObjectName(u"setupScrollArea")
        self.setupScrollArea.setMinimumSize(QSize(800, 500))
        self.setupScrollArea.setWidgetResizable(True)
        self.scrollAreaWidgetContents = QWidget()
        self.scrollAreaWidgetContents.setObjectName(u"scrollAreaWidgetContents")
        self.scrollAreaWidgetContents.setGeometry(QRect(0, 0, 900, 1200))
        self.scrollAreaWidgetContents.setMinimumSize(QSize(900, 1200))
        self.verticalLayout_4 = QVBoxLayout(self.scrollAreaWidgetContents)
        self.verticalLayout_4.setObjectName(u"verticalLayout_4")
        self.mapSetupGroup = QGroupBox(self.scrollAreaWidgetContents)
        self.mapSetupGroup.setObjectName(u"mapSetupGroup")
        self.gridLayout = QGridLayout(self.mapSetupGroup)
        self.gridLayout.setObjectName(u"gridLayout")
        self.mapPathEdit = QLineEdit(self.mapSetupGroup)
        self.mapPathEdit.setObjectName(u"mapPathEdit")
        self.mapPathEdit.setReadOnly(True)

        self.gridLayout.addWidget(self.mapPathEdit, 0, 1, 1, 2)

        self.importMapButton = QPushButton(self.mapSetupGroup)
        self.importMapButton.setObjectName(u"importMapButton")

        self.gridLayout.addWidget(self.importMapButton, 1, 0, 1, 2)

        self.horizontalSpacer_4 = QSpacerItem(728, 20, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        self.gridLayout.addItem(self.horizontalSpacer_4, 1, 3, 2, 1)

        self.clearMapButton = QPushButton(self.mapSetupGroup)
        self.clearMapButton.setObjectName(u"clearMapButton")

        self.gridLayout.addWidget(self.clearMapButton, 2, 0, 1, 2)

        self.mapSummaryLabel = QLabel(self.mapSetupGroup)
        self.mapSummaryLabel.setObjectName(u"mapSummaryLabel")

        self.gridLayout.addWidget(self.mapSummaryLabel, 2, 2, 1, 1)

        self.grailLocationCombo = QComboBox(self.mapSetupGroup)
        self.grailLocationCombo.setObjectName(u"grailLocationCombo")

        self.gridLayout.addWidget(self.grailLocationCombo, 3, 0, 1, 1)


        self.verticalLayout_4.addWidget(self.mapSetupGroup)

        self.characterSetupGroup = QGroupBox(self.scrollAreaWidgetContents)
        self.characterSetupGroup.setObjectName(u"characterSetupGroup")
        self.gridLayout_2 = QGridLayout(self.characterSetupGroup)
        self.gridLayout_2.setObjectName(u"gridLayout_2")
        self.characterTable = QTableWidget(self.characterSetupGroup)
        self.characterTable.setObjectName(u"characterTable")

        self.gridLayout_2.addWidget(self.characterTable, 0, 0, 1, 2)

        self.importCharacterButton = QPushButton(self.characterSetupGroup)
        self.importCharacterButton.setObjectName(u"importCharacterButton")

        self.gridLayout_2.addWidget(self.importCharacterButton, 1, 0, 1, 1)

        self.viewCharacterButton = QPushButton(self.characterSetupGroup)
        self.viewCharacterButton.setObjectName(u"viewCharacterButton")

        self.gridLayout_2.addWidget(self.viewCharacterButton, 1, 1, 1, 1)

        self.horizontalSpacer_5 = QSpacerItem(678, 20, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        self.gridLayout_2.addItem(self.horizontalSpacer_5, 1, 2, 1, 1)

        self.removeCharacterButton = QPushButton(self.characterSetupGroup)
        self.removeCharacterButton.setObjectName(u"removeCharacterButton")

        self.gridLayout_2.addWidget(self.removeCharacterButton, 2, 0, 1, 1)

        self.setRelationshipButton = QPushButton(self.characterSetupGroup)
        self.setRelationshipButton.setObjectName(u"setRelationshipButton")

        self.gridLayout_2.addWidget(self.setRelationshipButton, 2, 1, 1, 1)


        self.verticalLayout_4.addWidget(self.characterSetupGroup)

        self.label_2 = QLabel(self.scrollAreaWidgetContents)
        self.label_2.setObjectName(u"label_2")
        font3 = QFont()
        font3.setPointSize(12)
        font3.setBold(False)
        self.label_2.setFont(font3)

        self.verticalLayout_4.addWidget(self.label_2)

        self.ruleSetupGroup = QGroupBox(self.scrollAreaWidgetContents)
        self.ruleSetupGroup.setObjectName(u"ruleSetupGroup")
        self.horizontalLayout_3 = QHBoxLayout(self.ruleSetupGroup)
        self.horizontalLayout_3.setObjectName(u"horizontalLayout_3")
        self.formLayout = QFormLayout()
        self.formLayout.setObjectName(u"formLayout")
        self.grailAppearanceLineEdit = QLineEdit(self.ruleSetupGroup)
        self.grailAppearanceLineEdit.setObjectName(u"grailAppearanceLineEdit")

        self.formLayout.setWidget(1, QFormLayout.ItemRole.LabelRole, self.grailAppearanceLineEdit)

        self.maximumTurnsLineEdit = QLineEdit(self.ruleSetupGroup)
        self.maximumTurnsLineEdit.setObjectName(u"maximumTurnsLineEdit")

        self.formLayout.setWidget(0, QFormLayout.ItemRole.LabelRole, self.maximumTurnsLineEdit)

        self.grailReadyLineEdit = QLineEdit(self.ruleSetupGroup)
        self.grailReadyLineEdit.setObjectName(u"grailReadyLineEdit")

        self.formLayout.setWidget(2, QFormLayout.ItemRole.LabelRole, self.grailReadyLineEdit)


        self.horizontalLayout_3.addLayout(self.formLayout)

        self.horizontalSpacer_6 = QSpacerItem(465, 20, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        self.horizontalLayout_3.addItem(self.horizontalSpacer_6)


        self.verticalLayout_4.addWidget(self.ruleSetupGroup)

        self.verticalSpacer = QSpacerItem(20, 319, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding)

        self.verticalLayout_4.addItem(self.verticalSpacer)

        self.setupScrollArea.setWidget(self.scrollAreaWidgetContents)

        self.verticalLayout_7.addWidget(self.setupScrollArea)

        self.gameStartButton = QPushButton(self.setupPage)
        self.gameStartButton.setObjectName(u"gameStartButton")
        self.gameStartButton.setMinimumSize(QSize(0, 50))

        self.verticalLayout_7.addWidget(self.gameStartButton)

        self.mainStack.addWidget(self.setupPage)
        self.gamePage = QWidget()
        self.gamePage.setObjectName(u"gamePage")
        self.gamePageLayout = QVBoxLayout(self.gamePage)
        self.gamePageLayout.setObjectName(u"gamePageLayout")
        self.gameHeaderLayout = QHBoxLayout()
        self.gameHeaderLayout.setObjectName(u"gameHeaderLayout")
        self.globalTurnLabel = QLabel(self.gamePage)
        self.globalTurnLabel.setObjectName(u"globalTurnLabel")

        self.gameHeaderLayout.addWidget(self.globalTurnLabel)

        self.gamePhaseLabel = QLabel(self.gamePage)
        self.gamePhaseLabel.setObjectName(u"gamePhaseLabel")

        self.gameHeaderLayout.addWidget(self.gamePhaseLabel)

        self.currentActorLabel = QLabel(self.gamePage)
        self.currentActorLabel.setObjectName(u"currentActorLabel")

        self.gameHeaderLayout.addWidget(self.currentActorLabel)

        self.horizontalSpacer_9 = QSpacerItem(40, 20, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        self.gameHeaderLayout.addItem(self.horizontalSpacer_9)

        self.nextTurnButton = QPushButton(self.gamePage)
        self.nextTurnButton.setObjectName(u"nextTurnButton")
        self.nextTurnButton.setEnabled(False)

        self.gameHeaderLayout.addWidget(self.nextTurnButton)

        self.endGameButton = QPushButton(self.gamePage)
        self.endGameButton.setObjectName(u"endGameButton")

        self.gameHeaderLayout.addWidget(self.endGameButton)


        self.gamePageLayout.addLayout(self.gameHeaderLayout)

        self.gameContentLayout = QVBoxLayout()
        self.gameContentLayout.setObjectName(u"gameContentLayout")
        self.gameMainLayout = QHBoxLayout()
        self.gameMainLayout.setObjectName(u"gameMainLayout")
        self.gameCharacterScrollArea = QScrollArea(self.gamePage)
        self.gameCharacterScrollArea.setObjectName(u"gameCharacterScrollArea")
        self.gameCharacterScrollArea.setWidgetResizable(True)
        self.gameCharacterButtonContainer = QWidget()
        self.gameCharacterButtonContainer.setObjectName(u"gameCharacterButtonContainer")
        self.gameCharacterButtonContainer.setGeometry(QRect(0, 0, 129, 553))
        self.gameCharacterButtonLayout = QVBoxLayout(self.gameCharacterButtonContainer)
        self.gameCharacterButtonLayout.setObjectName(u"gameCharacterButtonLayout")
        self.gameCharacterScrollArea.setWidget(self.gameCharacterButtonContainer)

        self.gameMainLayout.addWidget(self.gameCharacterScrollArea)

        self.gameCenterLayout = QVBoxLayout()
        self.gameCenterLayout.setObjectName(u"gameCenterLayout")
        self.gameMapView = QGraphicsView(self.gamePage)
        self.gameMapView.setObjectName(u"gameMapView")

        self.gameCenterLayout.addWidget(self.gameMapView)

        self.gameLogEdit = QTextEdit(self.gamePage)
        self.gameLogEdit.setObjectName(u"gameLogEdit")
        self.gameLogEdit.setReadOnly(True)

        self.gameCenterLayout.addWidget(self.gameLogEdit)

        self.gameCenterLayout.setStretch(0, 3)
        self.gameCenterLayout.setStretch(1, 1)

        self.gameMainLayout.addLayout(self.gameCenterLayout)

        self.decisionGroup = QGroupBox(self.gamePage)
        self.decisionGroup.setObjectName(u"decisionGroup")
        self.verticalLayout_8 = QVBoxLayout(self.decisionGroup)
        self.verticalLayout_8.setObjectName(u"verticalLayout_8")
        self.decisionContentLayout = QVBoxLayout()
        self.decisionContentLayout.setObjectName(u"decisionContentLayout")
        self.currentRequestLabel = QLabel(self.decisionGroup)
        self.currentRequestLabel.setObjectName(u"currentRequestLabel")

        self.decisionContentLayout.addWidget(self.currentRequestLabel)

        self.decisionPromptLabel = QLabel(self.decisionGroup)
        self.decisionPromptLabel.setObjectName(u"decisionPromptLabel")
        self.decisionPromptLabel.setWordWrap(True)

        self.decisionContentLayout.addWidget(self.decisionPromptLabel)

        self.decisionInputStack = QStackedWidget(self.decisionGroup)
        self.decisionInputStack.setObjectName(u"decisionInputStack")
        self.choiceDecisionPage = QWidget()
        self.choiceDecisionPage.setObjectName(u"choiceDecisionPage")
        self.verticalLayout_9 = QVBoxLayout(self.choiceDecisionPage)
        self.verticalLayout_9.setObjectName(u"verticalLayout_9")
        self.decisionOptionList = QListWidget(self.choiceDecisionPage)
        self.decisionOptionList.setObjectName(u"decisionOptionList")

        self.verticalLayout_9.addWidget(self.decisionOptionList)

        self.decisionInputStack.addWidget(self.choiceDecisionPage)
        self.numberDecisionPage = QWidget()
        self.numberDecisionPage.setObjectName(u"numberDecisionPage")
        self.widget = QWidget(self.numberDecisionPage)
        self.widget.setObjectName(u"widget")
        self.widget.setGeometry(QRect(10, 20, 73, 44))
        self.verticalLayout_10 = QVBoxLayout(self.widget)
        self.verticalLayout_10.setObjectName(u"verticalLayout_10")
        self.verticalLayout_10.setContentsMargins(0, 0, 0, 0)
        self.numberDecisionLabel = QLabel(self.widget)
        self.numberDecisionLabel.setObjectName(u"numberDecisionLabel")

        self.verticalLayout_10.addWidget(self.numberDecisionLabel)

        self.spinBox = QSpinBox(self.widget)
        self.spinBox.setObjectName(u"spinBox")
        self.spinBox.setMaximum(9999999)

        self.verticalLayout_10.addWidget(self.spinBox)

        self.decisionInputStack.addWidget(self.numberDecisionPage)
        self.textDecisionPage = QWidget()
        self.textDecisionPage.setObjectName(u"textDecisionPage")
        self.decisionTextEdit = QLineEdit(self.textDecisionPage)
        self.decisionTextEdit.setObjectName(u"decisionTextEdit")
        self.decisionTextEdit.setGeometry(QRect(10, 30, 201, 20))
        self.decisionInputStack.addWidget(self.textDecisionPage)

        self.decisionContentLayout.addWidget(self.decisionInputStack)


        self.verticalLayout_8.addLayout(self.decisionContentLayout)

        self.decisionButtonLayout = QHBoxLayout()
        self.decisionButtonLayout.setObjectName(u"decisionButtonLayout")
        self.decisionBackButton = QPushButton(self.decisionGroup)
        self.decisionBackButton.setObjectName(u"decisionBackButton")
        self.decisionBackButton.setEnabled(False)

        self.decisionButtonLayout.addWidget(self.decisionBackButton)

        self.decisionConfirmButton = QPushButton(self.decisionGroup)
        self.decisionConfirmButton.setObjectName(u"decisionConfirmButton")
        self.decisionConfirmButton.setEnabled(False)

        self.decisionButtonLayout.addWidget(self.decisionConfirmButton)


        self.verticalLayout_8.addLayout(self.decisionButtonLayout)


        self.gameMainLayout.addWidget(self.decisionGroup)

        self.gameMainLayout.setStretch(0, 1)
        self.gameMainLayout.setStretch(1, 3)
        self.gameMainLayout.setStretch(2, 2)

        self.gameContentLayout.addLayout(self.gameMainLayout)

        self.checkpointGroup = QGroupBox(self.gamePage)
        self.checkpointGroup.setObjectName(u"checkpointGroup")
        sizePolicy = QSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        sizePolicy.setHorizontalStretch(0)
        sizePolicy.setVerticalStretch(0)
        sizePolicy.setHeightForWidth(self.checkpointGroup.sizePolicy().hasHeightForWidth())
        self.checkpointGroup.setSizePolicy(sizePolicy)
        self.checkpointGroup.setMinimumSize(QSize(0, 70))
        self.checkpointLayout = QHBoxLayout(self.checkpointGroup)
        self.checkpointLayout.setObjectName(u"checkpointLayout")
        self.checkpointStatusLabel = QLabel(self.checkpointGroup)
        self.checkpointStatusLabel.setObjectName(u"checkpointStatusLabel")

        self.checkpointLayout.addWidget(self.checkpointStatusLabel)

        self.saveGameButton = QPushButton(self.checkpointGroup)
        self.saveGameButton.setObjectName(u"saveGameButton")
        self.saveGameButton.setEnabled(False)

        self.checkpointLayout.addWidget(self.saveGameButton)

        self.horizontalSpacer_10 = QSpacerItem(40, 20, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        self.checkpointLayout.addItem(self.horizontalSpacer_10)

        self.GMCommandEdit = QLineEdit(self.checkpointGroup)
        self.GMCommandEdit.setObjectName(u"GMCommandEdit")

        self.checkpointLayout.addWidget(self.GMCommandEdit)

        self.commandExecutionButton = QPushButton(self.checkpointGroup)
        self.commandExecutionButton.setObjectName(u"commandExecutionButton")

        self.checkpointLayout.addWidget(self.commandExecutionButton)


        self.gameContentLayout.addWidget(self.checkpointGroup)

        self.gameContentLayout.setStretch(0, 1)

        self.gamePageLayout.addLayout(self.gameContentLayout)

        self.gamePageLayout.setStretch(1, 1)
        self.mainStack.addWidget(self.gamePage)
        self.placementPage = QWidget()
        self.placementPage.setObjectName(u"placementPage")
        self.placementTitleLabel = QLabel(self.placementPage)
        self.placementTitleLabel.setObjectName(u"placementTitleLabel")
        self.placementTitleLabel.setGeometry(QRect(0, 30, 81, 16))
        self.placementBackButton = QPushButton(self.placementPage)
        self.placementBackButton.setObjectName(u"placementBackButton")
        self.placementBackButton.setGeometry(QRect(0, 0, 75, 24))
        self.placementProgressLabel = QLabel(self.placementPage)
        self.placementProgressLabel.setObjectName(u"placementProgressLabel")
        self.placementProgressLabel.setGeometry(QRect(0, 50, 81, 16))
        self.splitter = QSplitter(self.placementPage)
        self.splitter.setObjectName(u"splitter")
        self.splitter.setGeometry(QRect(0, 70, 724, 347))
        self.splitter.setOrientation(Qt.Orientation.Horizontal)
        self.placementCharacterList = QListWidget(self.splitter)
        self.placementCharacterList.setObjectName(u"placementCharacterList")
        self.splitter.addWidget(self.placementCharacterList)
        self.placementMapView = QGraphicsView(self.splitter)
        self.placementMapView.setObjectName(u"placementMapView")
        self.splitter.addWidget(self.placementMapView)
        self.placementDetailGroup = QGroupBox(self.splitter)
        self.placementDetailGroup.setObjectName(u"placementDetailGroup")
        self.placementDetailGroup.setMinimumSize(QSize(200, 300))
        self.verticalLayout_6 = QVBoxLayout(self.placementDetailGroup)
        self.verticalLayout_6.setObjectName(u"verticalLayout_6")
        self.groupEditButton = QPushButton(self.placementDetailGroup)
        self.groupEditButton.setObjectName(u"groupEditButton")
        self.groupEditButton.setMaximumSize(QSize(75, 16777215))

        self.verticalLayout_6.addWidget(self.groupEditButton)

        self.verticalLayout_5 = QVBoxLayout()
        self.verticalLayout_5.setObjectName(u"verticalLayout_5")
        self.setLocationScrollArea = QScrollArea(self.placementDetailGroup)
        self.setLocationScrollArea.setObjectName(u"setLocationScrollArea")
        sizePolicy1 = QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        sizePolicy1.setHorizontalStretch(0)
        sizePolicy1.setVerticalStretch(1)
        sizePolicy1.setHeightForWidth(self.setLocationScrollArea.sizePolicy().hasHeightForWidth())
        self.setLocationScrollArea.setSizePolicy(sizePolicy1)
        self.setLocationScrollArea.setMinimumSize(QSize(190, 19))
        self.setLocationScrollArea.setMaximumSize(QSize(16777215, 16777215))
        self.setLocationScrollArea.setWidgetResizable(True)
        self.scrollAreaWidgetContents_2 = QWidget()
        self.scrollAreaWidgetContents_2.setObjectName(u"scrollAreaWidgetContents_2")
        self.scrollAreaWidgetContents_2.setGeometry(QRect(0, 0, 171, 292))
        self.scrollAreaWidgetContents_2.setMinimumSize(QSize(0, 292))
        self.placementRowsLayout = QVBoxLayout(self.scrollAreaWidgetContents_2)
        self.placementRowsLayout.setObjectName(u"placementRowsLayout")
        self.saberPlacementLayout = QHBoxLayout()
        self.saberPlacementLayout.setObjectName(u"saberPlacementLayout")
        self.saberGroupLabel = QLabel(self.scrollAreaWidgetContents_2)
        self.saberGroupLabel.setObjectName(u"saberGroupLabel")

        self.saberPlacementLayout.addWidget(self.saberGroupLabel)

        self.saberLocation = QComboBox(self.scrollAreaWidgetContents_2)
        self.saberLocation.setObjectName(u"saberLocation")

        self.saberPlacementLayout.addWidget(self.saberLocation)


        self.placementRowsLayout.addLayout(self.saberPlacementLayout)

        self.archerPlacementLayout = QHBoxLayout()
        self.archerPlacementLayout.setObjectName(u"archerPlacementLayout")
        self.archerGroupLabel = QLabel(self.scrollAreaWidgetContents_2)
        self.archerGroupLabel.setObjectName(u"archerGroupLabel")

        self.archerPlacementLayout.addWidget(self.archerGroupLabel)

        self.archerLocation = QComboBox(self.scrollAreaWidgetContents_2)
        self.archerLocation.setObjectName(u"archerLocation")

        self.archerPlacementLayout.addWidget(self.archerLocation)


        self.placementRowsLayout.addLayout(self.archerPlacementLayout)

        self.lancerPlacementLayout = QHBoxLayout()
        self.lancerPlacementLayout.setObjectName(u"lancerPlacementLayout")
        self.lancerGroupLabel = QLabel(self.scrollAreaWidgetContents_2)
        self.lancerGroupLabel.setObjectName(u"lancerGroupLabel")

        self.lancerPlacementLayout.addWidget(self.lancerGroupLabel)

        self.lancerLocation = QComboBox(self.scrollAreaWidgetContents_2)
        self.lancerLocation.setObjectName(u"lancerLocation")

        self.lancerPlacementLayout.addWidget(self.lancerLocation)


        self.placementRowsLayout.addLayout(self.lancerPlacementLayout)

        self.riderPlacementLayout = QHBoxLayout()
        self.riderPlacementLayout.setObjectName(u"riderPlacementLayout")
        self.riderGroupLabel = QLabel(self.scrollAreaWidgetContents_2)
        self.riderGroupLabel.setObjectName(u"riderGroupLabel")

        self.riderPlacementLayout.addWidget(self.riderGroupLabel)

        self.riderLocation = QComboBox(self.scrollAreaWidgetContents_2)
        self.riderLocation.setObjectName(u"riderLocation")

        self.riderPlacementLayout.addWidget(self.riderLocation)


        self.placementRowsLayout.addLayout(self.riderPlacementLayout)

        self.casterPlacementLayout = QHBoxLayout()
        self.casterPlacementLayout.setObjectName(u"casterPlacementLayout")
        self.casterGroupLabel = QLabel(self.scrollAreaWidgetContents_2)
        self.casterGroupLabel.setObjectName(u"casterGroupLabel")

        self.casterPlacementLayout.addWidget(self.casterGroupLabel)

        self.casterLocation = QComboBox(self.scrollAreaWidgetContents_2)
        self.casterLocation.setObjectName(u"casterLocation")

        self.casterPlacementLayout.addWidget(self.casterLocation)


        self.placementRowsLayout.addLayout(self.casterPlacementLayout)

        self.assassinPlacementLayout = QHBoxLayout()
        self.assassinPlacementLayout.setObjectName(u"assassinPlacementLayout")
        self.assassinGroupLabel = QLabel(self.scrollAreaWidgetContents_2)
        self.assassinGroupLabel.setObjectName(u"assassinGroupLabel")

        self.assassinPlacementLayout.addWidget(self.assassinGroupLabel)

        self.assassinLocation = QComboBox(self.scrollAreaWidgetContents_2)
        self.assassinLocation.setObjectName(u"assassinLocation")

        self.assassinPlacementLayout.addWidget(self.assassinLocation)


        self.placementRowsLayout.addLayout(self.assassinPlacementLayout)

        self.berserkerPlacementLayout = QHBoxLayout()
        self.berserkerPlacementLayout.setObjectName(u"berserkerPlacementLayout")
        self.berserkerGroupLabel = QLabel(self.scrollAreaWidgetContents_2)
        self.berserkerGroupLabel.setObjectName(u"berserkerGroupLabel")

        self.berserkerPlacementLayout.addWidget(self.berserkerGroupLabel)

        self.berserkerLocation = QComboBox(self.scrollAreaWidgetContents_2)
        self.berserkerLocation.setObjectName(u"berserkerLocation")

        self.berserkerPlacementLayout.addWidget(self.berserkerLocation)


        self.placementRowsLayout.addLayout(self.berserkerPlacementLayout)

        self.extraPlacementLayout = QHBoxLayout()
        self.extraPlacementLayout.setObjectName(u"extraPlacementLayout")
        self.extraGroupLabel = QLabel(self.scrollAreaWidgetContents_2)
        self.extraGroupLabel.setObjectName(u"extraGroupLabel")

        self.extraPlacementLayout.addWidget(self.extraGroupLabel)

        self.extraLocation = QComboBox(self.scrollAreaWidgetContents_2)
        self.extraLocation.setObjectName(u"extraLocation")

        self.extraPlacementLayout.addWidget(self.extraLocation)


        self.placementRowsLayout.addLayout(self.extraPlacementLayout)

        self.setLocationScrollArea.setWidget(self.scrollAreaWidgetContents_2)

        self.verticalLayout_5.addWidget(self.setLocationScrollArea)

        self.horizontalLayout_6 = QHBoxLayout()
        self.horizontalLayout_6.setObjectName(u"horizontalLayout_6")
        self.addPlacementGroupButton = QPushButton(self.placementDetailGroup)
        self.addPlacementGroupButton.setObjectName(u"addPlacementGroupButton")

        self.horizontalLayout_6.addWidget(self.addPlacementGroupButton)

        self.removePlacementGroupButton = QPushButton(self.placementDetailGroup)
        self.removePlacementGroupButton.setObjectName(u"removePlacementGroupButton")

        self.horizontalLayout_6.addWidget(self.removePlacementGroupButton)


        self.verticalLayout_5.addLayout(self.horizontalLayout_6)

        self.horizontalLayout_5 = QHBoxLayout()
        self.horizontalLayout_5.setObjectName(u"horizontalLayout_5")
        self.resetChooseButton = QPushButton(self.placementDetailGroup)
        self.resetChooseButton.setObjectName(u"resetChooseButton")
        self.resetChooseButton.setMaximumSize(QSize(150, 150))

        self.horizontalLayout_5.addWidget(self.resetChooseButton)

        self.characterConfirmButton = QPushButton(self.placementDetailGroup)
        self.characterConfirmButton.setObjectName(u"characterConfirmButton")
        self.characterConfirmButton.setMaximumSize(QSize(150, 150))

        self.horizontalLayout_5.addWidget(self.characterConfirmButton)


        self.verticalLayout_5.addLayout(self.horizontalLayout_5)


        self.verticalLayout_6.addLayout(self.verticalLayout_5)

        self.splitter.addWidget(self.placementDetailGroup)
        self.mainStack.addWidget(self.placementPage)
        self.groupMemberPage = QWidget()
        self.groupMemberPage.setObjectName(u"groupMemberPage")
        self.groupMemberGroup = QGroupBox(self.groupMemberPage)
        self.groupMemberGroup.setObjectName(u"groupMemberGroup")
        self.groupMemberGroup.setGeometry(QRect(0, 0, 671, 501))
        self.layoutWidget1 = QWidget(self.groupMemberGroup)
        self.layoutWidget1.setObjectName(u"layoutWidget1")
        self.layoutWidget1.setGeometry(QRect(10, 20, 258, 224))
        self.gridLayout_3 = QGridLayout(self.layoutWidget1)
        self.gridLayout_3.setObjectName(u"gridLayout_3")
        self.gridLayout_3.setContentsMargins(0, 0, 0, 0)
        self.customGroupTable = QTableWidget(self.layoutWidget1)
        self.customGroupTable.setObjectName(u"customGroupTable")

        self.gridLayout_3.addWidget(self.customGroupTable, 0, 0, 1, 2)

        self.removeGroupButton = QPushButton(self.layoutWidget1)
        self.removeGroupButton.setObjectName(u"removeGroupButton")

        self.gridLayout_3.addWidget(self.removeGroupButton, 1, 1, 1, 1)

        self.newGroupButton = QPushButton(self.layoutWidget1)
        self.newGroupButton.setObjectName(u"newGroupButton")

        self.gridLayout_3.addWidget(self.newGroupButton, 1, 0, 1, 1)

        self.confirmGroupButton = QPushButton(self.layoutWidget1)
        self.confirmGroupButton.setObjectName(u"confirmGroupButton")

        self.gridLayout_3.addWidget(self.confirmGroupButton, 2, 0, 1, 1)

        self.resetGroupButton = QPushButton(self.layoutWidget1)
        self.resetGroupButton.setObjectName(u"resetGroupButton")

        self.gridLayout_3.addWidget(self.resetGroupButton, 2, 1, 1, 1)

        self.mainStack.addWidget(self.groupMemberPage)

        self.verticalLayout.addWidget(self.mainStack)

        MainWindow.setCentralWidget(self.centralwidget)
        self.menubar = QMenuBar(MainWindow)
        self.menubar.setObjectName(u"menubar")
        self.menubar.setGeometry(QRect(0, 0, 836, 22))
        MainWindow.setMenuBar(self.menubar)
        self.statusbar = QStatusBar(MainWindow)
        self.statusbar.setObjectName(u"statusbar")
        MainWindow.setStatusBar(self.statusbar)

        self.retranslateUi(MainWindow)

        self.mainStack.setCurrentIndex(2)
        self.decisionInputStack.setCurrentIndex(0)


        QMetaObject.connectSlotsByName(MainWindow)
    # setupUi

    def retranslateUi(self, MainWindow):
        MainWindow.setWindowTitle(QCoreApplication.translate("MainWindow", u"Papermoon GM\u7ec8\u7aef", None))
        self.label.setText(QCoreApplication.translate("MainWindow", u"Papermoon", None))
        self.newGameButton.setText(QCoreApplication.translate("MainWindow", u"\u65b0\u6e38\u620f", None))
        self.loadGameButton.setText(QCoreApplication.translate("MainWindow", u"\u52a0\u8f7d\u6e38\u620f", None))
        self.exitButton.setText(QCoreApplication.translate("MainWindow", u"\u9000\u51fa", None))
        self.backToMenuButton.setText(QCoreApplication.translate("MainWindow", u"\u8fd4\u56de", None))
        self.setupTitleLabel.setText(QCoreApplication.translate("MainWindow", u"\u65b0\u6e38\u620f\u914d\u7f6e", None))
        self.mapSetupGroup.setTitle(QCoreApplication.translate("MainWindow", u"\u5730\u56fe", None))
        self.importMapButton.setText(QCoreApplication.translate("MainWindow", u"\u5bfc\u5165\u5730\u56fe", None))
        self.clearMapButton.setText(QCoreApplication.translate("MainWindow", u"\u6e05\u9664\u5730\u56fe", None))
        self.mapSummaryLabel.setText(QCoreApplication.translate("MainWindow", u"TextLabel", None))
        self.characterSetupGroup.setTitle(QCoreApplication.translate("MainWindow", u"\u53c2\u6218\u89d2\u8272", None))
        self.importCharacterButton.setText(QCoreApplication.translate("MainWindow", u"\u5bfc\u5165\u89d2\u8272", None))
        self.viewCharacterButton.setText(QCoreApplication.translate("MainWindow", u"\u67e5\u770b\u89d2\u8272", None))
        self.removeCharacterButton.setText(QCoreApplication.translate("MainWindow", u"\u79fb\u9664\u89d2\u8272", None))
        self.setRelationshipButton.setText(QCoreApplication.translate("MainWindow", u"\u8bbe\u7f6e\u4e3b\u4ece", None))
        self.label_2.setText(QCoreApplication.translate("MainWindow", u"\u5728\u6b64\u5bfc\u5165\u5730\u56fe\u548c\u53c2\u6218\u89d2\u8272", None))
        self.ruleSetupGroup.setTitle(QCoreApplication.translate("MainWindow", u"\u6e38\u620f\u89c4\u5219", None))
        self.maximumTurnsLineEdit.setText("")
        self.gameStartButton.setText(QCoreApplication.translate("MainWindow", u"\u521b\u5efa\u6e38\u620f", None))
        self.globalTurnLabel.setText(QCoreApplication.translate("MainWindow", u"\u5f53\u524d\u56de\u5408:", None))
        self.gamePhaseLabel.setText(QCoreApplication.translate("MainWindow", u"\u5f53\u524d\u9636\u6bb5:", None))
        self.currentActorLabel.setText(QCoreApplication.translate("MainWindow", u"\u884c\u52a8\u8005:", None))
        self.nextTurnButton.setText(QCoreApplication.translate("MainWindow", u"\u4e0b\u4e00\u56de\u5408", None))
        self.endGameButton.setText(QCoreApplication.translate("MainWindow", u"\u5f3a\u5236\u7ed3\u675f", None))
        self.decisionGroup.setTitle(QCoreApplication.translate("MainWindow", u"\u5f53\u524d\u64cd\u4f5c", None))
        self.currentRequestLabel.setText(QCoreApplication.translate("MainWindow", u"\u7b49\u5f85\u6e38\u620f\u6d41\u7a0b", None))
        self.decisionPromptLabel.setText(QCoreApplication.translate("MainWindow", u"\u5f53\u524d\u6ca1\u6709\u9700\u8981\u5904\u7406\u7684\u51b3\u5b9a", None))
        self.numberDecisionLabel.setText(QCoreApplication.translate("MainWindow", u"\u8f93\u5165\u6570\u503c", None))
        self.decisionBackButton.setText(QCoreApplication.translate("MainWindow", u"\u8fd4\u56de", None))
        self.decisionConfirmButton.setText(QCoreApplication.translate("MainWindow", u"\u786e\u8ba4", None))
        self.checkpointGroup.setTitle(QCoreApplication.translate("MainWindow", u"\u6e38\u620f\u72b6\u6001", None))
        self.checkpointStatusLabel.setText(QCoreApplication.translate("MainWindow", u"\u6e38\u620f\u5c1a\u672a\u5f00\u59cb", None))
        self.saveGameButton.setText(QCoreApplication.translate("MainWindow", u"\u4fdd\u5b58", None))
        self.commandExecutionButton.setText(QCoreApplication.translate("MainWindow", u"\u6267\u884c\u6307\u4ee4", None))
        self.placementTitleLabel.setText(QCoreApplication.translate("MainWindow", u"\u8bbe\u7f6e\u521d\u59cb\u4f4d\u7f6e", None))
        self.placementBackButton.setText(QCoreApplication.translate("MainWindow", u"\u8fd4\u56de", None))
        self.placementProgressLabel.setText(QCoreApplication.translate("MainWindow", u"\u5df2\u8bbe\u7f6e0/4", None))
        self.placementDetailGroup.setTitle(QCoreApplication.translate("MainWindow", u"\u521d\u59cb\u4f4d\u7f6e", None))
        self.groupEditButton.setText(QCoreApplication.translate("MainWindow", u"\u5206\u7ec4\u7f16\u8f91", None))
        self.saberGroupLabel.setText(QCoreApplication.translate("MainWindow", u"Saber\u7ec4", None))
        self.archerGroupLabel.setText(QCoreApplication.translate("MainWindow", u"Archer\u7ec4", None))
        self.lancerGroupLabel.setText(QCoreApplication.translate("MainWindow", u"Lancer\u7ec4", None))
        self.riderGroupLabel.setText(QCoreApplication.translate("MainWindow", u"Rider\u7ec4", None))
        self.casterGroupLabel.setText(QCoreApplication.translate("MainWindow", u"Caster\u7ec4", None))
        self.assassinGroupLabel.setText(QCoreApplication.translate("MainWindow", u"Assassin\u7ec4", None))
        self.berserkerGroupLabel.setText(QCoreApplication.translate("MainWindow", u"Berserker\u7ec4", None))
        self.extraGroupLabel.setText(QCoreApplication.translate("MainWindow", u"Extra\u7ec4", None))
        self.addPlacementGroupButton.setText(QCoreApplication.translate("MainWindow", u"\u65b0\u589e", None))
        self.removePlacementGroupButton.setText(QCoreApplication.translate("MainWindow", u"\u5220\u9664", None))
        self.resetChooseButton.setText(QCoreApplication.translate("MainWindow", u"\u91cd\u7f6e", None))
        self.characterConfirmButton.setText(QCoreApplication.translate("MainWindow", u"\u786e\u8ba4", None))
        self.groupMemberGroup.setTitle(QCoreApplication.translate("MainWindow", u"\u5206\u7ec4\u7ba1\u7406", None))
        self.removeGroupButton.setText(QCoreApplication.translate("MainWindow", u"\u5220\u9664", None))
        self.newGroupButton.setText(QCoreApplication.translate("MainWindow", u"\u65b0\u5efa", None))
        self.confirmGroupButton.setText(QCoreApplication.translate("MainWindow", u"\u786e\u8ba4", None))
        self.resetGroupButton.setText(QCoreApplication.translate("MainWindow", u"\u91cd\u7f6e", None))
    # retranslateUi

