"""配信支援URL表示パネル。

v1.x で 4 種類の独立ブラウザソース URL を提示する（FR-STR-007 / FR-STR-010）。
外部連携ツール（プラグイン等）向けの WebSocket URI（ws://...）は
通常運用ではノイズになるため、設定ダイアログの WebSocket タブからのみ参照する。
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
)


class BroadcastUrlPanel(QGroupBox):
    """4 つのブラウザソース URL をコピーボタン付きで表示する。"""

    def __init__(self, urls: dict[str, str], parent=None) -> None:
        """`urls` は `{ラベル: URL文字列}` の辞書（順序保持）。

        想定キー例:
        - 「打鍵数カウンタ」
        - 「現在のプレイ楽曲」
        - 「選曲中の楽曲のスコア履歴」（v1.x はプレースホルダ実装）
        - 「直近 10 件のプレイ履歴」
        """
        super().__init__("配信支援ブラウザソース URL", parent)
        layout = QFormLayout(self)
        for label, url in urls.items():
            row = QHBoxLayout()
            edit = QLineEdit(url)
            edit.setReadOnly(True)
            row.addWidget(edit, stretch=1)
            copy = QPushButton("コピー")
            copy.clicked.connect(lambda _c=False, e=edit: self._copy(e))
            row.addWidget(copy)
            layout.addRow(label, row)

    @staticmethod
    def _copy(edit: QLineEdit) -> None:
        edit.selectAll()
        edit.copy()
