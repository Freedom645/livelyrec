"""配信支援URL表示パネル。"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
)


class BroadcastUrlPanel(QGroupBox):
    def __init__(self, ws_url: str, browser_url: str, parent=None) -> None:
        super().__init__("配信支援URL", parent)
        layout = QVBoxLayout(self)
        for label, url in (("WebSocket:", ws_url), ("ブラウザソース:", browser_url)):
            row = QHBoxLayout()
            row.addWidget(QLabel(label))
            edit = QLineEdit(url)
            edit.setReadOnly(True)
            row.addWidget(edit)
            copy = QPushButton("コピー")
            copy.clicked.connect(lambda _checked=False, e=edit: self._copy(e))
            row.addWidget(copy)
            layout.addLayout(row)

    @staticmethod
    def _copy(edit: QLineEdit) -> None:
        edit.selectAll()
        edit.copy()
