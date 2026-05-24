"""配信支援URL表示パネル。

OBS ブラウザソースに貼り付けるための HTTP URL を表示する。
外部連携ツール（プラグイン等）向けの WebSocket URI（ws://...）は
通常運用ではノイズになるため、設定ダイアログの WebSocket タブからのみ参照する。
"""

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
    def __init__(self, browser_url: str, parent=None) -> None:
        super().__init__("配信支援URL", parent)
        layout = QVBoxLayout(self)
        row = QHBoxLayout()
        row.addWidget(QLabel("ブラウザソース:"))
        edit = QLineEdit(browser_url)
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
