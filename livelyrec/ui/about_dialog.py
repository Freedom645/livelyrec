"""About ダイアログ（FR-BAN-008、v2.0）。

詳細: docs/design/11_詳細設計_バナー認識.md §7.2

アプリのバージョン情報・出典属性表示・免責表示を行うモーダル。
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
    "<p><b>バナー画像参照:</b><br>"
    "remywiki.com / popnmusic.fandom.com<br>"
    "（各サイトの著作権・利用規約はそれぞれのサイトをご参照ください）</p>"
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
