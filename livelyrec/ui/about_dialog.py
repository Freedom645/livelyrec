"""About ダイアログ。

アプリのバージョン情報と KONAMI 公式非関連の免責のみを表示するモーダル。
ヘルプメニューから開く。
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QLabel, QVBoxLayout

from livelyrec import __version__

ABOUT_BODY = (
    "<h3>LivelyRec v{version}</h3>"
    "<p>pop'n music lively のスコア記録・配信支援ツール（個人開発・非営利）</p>"
    "<hr>"
    "<p><b>免責:</b><br>"
    "本アプリは個人開発の非営利ツールであり、株式会社コナミデジタル<br>"
    "エンタテインメントとは無関係です。<br>"
    "&quot;pop'n music&quot; および &quot;lively&quot; は同社の登録商標です。</p>"
)


class AboutDialog(QDialog):
    """LivelyRec の About ダイアログ。"""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("LivelyRec について")
        self.setModal(True)

        layout = QVBoxLayout(self)
        body = QLabel(ABOUT_BODY.format(version=__version__))
        body.setTextFormat(Qt.RichText)
        body.setWordWrap(True)
        body.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(body)

        buttons = QDialogButtonBox(QDialogButtonBox.Close, self)
        buttons.rejected.connect(self.reject)
        buttons.clicked.connect(self.accept)
        layout.addWidget(buttons)
