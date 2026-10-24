import sys

import pandas as pd
from PySide6.QtCore import Qt, QAbstractTableModel, QModelIndex
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QTableView,
    QHeaderView,
    QToolBar,
    QFileDialog,
    QMessageBox,
    QStatusBar,
    QComboBox,
    QLabel,
    QVBoxLayout,
    QPushButton,
    QStackedWidget,
)

FONT_FAMILY = "'맑은 고딕', 'Malgun Gothic', 'Segoe UI', sans-serif"

STYLE_SHEET = f"""
* {{
    font-family: {FONT_FAMILY};
}}
QMainWindow {{
    background-color: #f4f6fb;
}}
QToolBar {{
    background-color: #ffffff;
    border-bottom: 1px solid #e2e6f0;
    padding: 8px 12px;
    spacing: 10px;
}}
QPushButton#openButton {{
    background-color: #4f6bff;
    color: white;
    border: none;
    border-radius: 8px;
    padding: 9px 20px;
    font-weight: 600;
    font-size: 14px;
}}
QPushButton#openButton:hover {{
    background-color: #3d57e6;
}}
QPushButton#openButton:pressed {{
    background-color: #2f46c2;
}}
QLabel#filePathLabel {{
    color: #374151;
    font-size: 13px;
    padding-left: 6px;
}}
QComboBox {{
    border: 1px solid #d7dbe8;
    border-radius: 6px;
    padding: 6px 10px;
    background: white;
    color: #111827;
    font-size: 13px;
    min-width: 140px;
}}
QComboBox:focus {{
    border: 1px solid #4f6bff;
}}
QTableView {{
    background-color: #ffffff;
    alternate-background-color: #f6f8fc;
    gridline-color: #e5e8f0;
    border: 1px solid #e2e6f0;
    border-radius: 10px;
    selection-background-color: #c9d6ff;
    selection-color: #111827;
    color: #1f2937;
    font-size: 14px;
}}
QTableView::item {{
    padding: 8px;
}}
QHeaderView::section {{
    background-color: #e8ecf8;
    color: #1f2937;
    padding: 10px 8px;
    border: none;
    border-right: 1px solid #d7dbe8;
    border-bottom: 1px solid #d7dbe8;
    font-weight: 700;
    font-size: 13px;
}}
QTableCornerButton::section {{
    background-color: #e8ecf8;
    border: none;
}}
QStatusBar {{
    background-color: #ffffff;
    border-top: 1px solid #e2e6f0;
    color: #374151;
    font-size: 12px;
    padding: 5px 10px;
}}
QLabel#placeholderLabel {{
    color: #6b7280;
    font-size: 16px;
}}
"""


class PandasTableModel(QAbstractTableModel):
    def __init__(self, df: pd.DataFrame):
        super().__init__()
        self._df = df

    def rowCount(self, parent=QModelIndex()):
        return len(self._df.index)

    def columnCount(self, parent=QModelIndex()):
        return len(self._df.columns)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid() or role != Qt.DisplayRole:
            return None
        value = self._df.iat[index.row(), index.column()]
        return "" if pd.isna(value) else str(value)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role != Qt.DisplayRole:
            return None
        if orientation == Qt.Horizontal:
            return str(self._df.columns[section])
        return str(section + 1)


class ExcelViewer(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Excel Viewer")
        self.resize(1000, 650)
        self.setAcceptDrops(True)
        self._sheets: dict[str, pd.DataFrame] = {}
        self._current_path = ""

        self._build_toolbar()
        self._build_central_widget()
        self.setStatusBar(QStatusBar())

    def _build_toolbar(self):
        toolbar = QToolBar("Main")
        toolbar.setMovable(False)
        self.addToolBar(toolbar)

        open_button = QPushButton("파일 열기")
        open_button.setObjectName("openButton")
        open_button.setCursor(Qt.PointingHandCursor)
        open_button.clicked.connect(self.open_file)
        toolbar.addWidget(open_button)

        self.sheet_combo = QComboBox()
        self.sheet_combo.setVisible(False)
        self.sheet_combo.currentTextChanged.connect(self._on_sheet_changed)
        toolbar.addWidget(self.sheet_combo)

        self.file_path_label = QLabel("불러온 파일이 없습니다")
        self.file_path_label.setObjectName("filePathLabel")
        toolbar.addWidget(self.file_path_label)

    def _build_central_widget(self):
        self.table_view = QTableView()
        self.table_view.setAlternatingRowColors(True)
        self.table_view.setSelectionBehavior(QTableView.SelectRows)
        self.table_view.setSortingEnabled(True)
        self.table_view.horizontalHeader().setStretchLastSection(True)
        self.table_view.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.table_view.verticalHeader().setDefaultSectionSize(32)
        self.table_view.setFont(QFont("맑은 고딕", 10))

        self.placeholder = QLabel("엑셀 파일을 열거나 이 창으로 끌어다 놓으세요")
        self.placeholder.setObjectName("placeholderLabel")
        self.placeholder.setAlignment(Qt.AlignCenter)

        self.stack = QStackedWidget()
        self.stack.addWidget(self.placeholder)
        self.stack.addWidget(self.table_view)

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.addWidget(self.stack)
        self.setCentralWidget(container)

    def open_file(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "엑셀 파일 열기",
            "",
            "Excel Files (*.xlsx *.xls);;All Files (*)",
        )
        if not file_path:
            return
        self.load_excel(file_path)

    def load_excel(self, file_path: str):
        try:
            sheets = pd.read_excel(file_path, sheet_name=None)
        except Exception as e:
            QMessageBox.critical(self, "오류", f"파일을 읽는 중 오류가 발생했습니다:\n{e}")
            return

        self._sheets = sheets
        self._current_path = file_path

        self.sheet_combo.blockSignals(True)
        self.sheet_combo.clear()
        self.sheet_combo.addItems(list(sheets.keys()))
        self.sheet_combo.blockSignals(False)
        self.sheet_combo.setVisible(len(sheets) > 1)

        self._show_sheet(next(iter(sheets)))
        self.file_path_label.setText(file_path)

    def _on_sheet_changed(self, sheet_name: str):
        if sheet_name:
            self._show_sheet(sheet_name)

    def _show_sheet(self, sheet_name: str):
        df = self._sheets[sheet_name]
        model = PandasTableModel(df)
        self.table_view.setModel(model)
        self.table_view.resizeColumnsToContents()
        self.stack.setCurrentWidget(self.table_view)
        self.statusBar().showMessage(f"{sheet_name}  •  {len(df)}행 x {len(df.columns)}열")

    def dragEnterEvent(self, event):
        urls = event.mimeData().urls()
        if urls and urls[0].toLocalFile().lower().endswith((".xlsx", ".xls")):
            event.acceptProposedAction()

    def dropEvent(self, event):
        file_path = event.mimeData().urls()[0].toLocalFile()
        self.load_excel(file_path)


def main():
    app = QApplication(sys.argv)
    app.setFont(QFont("맑은 고딕", 10))
    app.setStyleSheet(STYLE_SHEET)
    window = ExcelViewer()
    window.show()

    if len(sys.argv) > 1:
        window.load_excel(sys.argv[1])

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
