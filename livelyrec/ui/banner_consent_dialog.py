"""バナー画像取得時の同意ダイアログ（FR-BAN-006、v2.0）。

詳細: docs/design/11_詳細設計_バナー認識.md §7.1

「Wiki からバナー画像を取得」ボタン押下時に表示するモーダルダイアログ。
私的複製の範囲内であること、本アプリが KONAMI 公式とは無関係である旨を
明示し、ユーザの明示的同意を取得する。
"""

from __future__ import annotations

from datetime import UTC, datetime

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QVBoxLayout,
)

# app_kv テーブルに保存する同意キー（FR-BAN-006）
CONSENT_KEY = "banner_fetch_consent"


CONSENT_BODY = (
    "以下のサイトからバナー画像をダウンロードし、お使いの PC の\n"
    "ローカルフォルダに保存します。\n\n"
    "  ・remywiki.com\n"
    "  ・popnmusic.fandom.com\n\n"
    "取得した画像は楽曲認識の精度向上のみに用い、本アプリで再配布する\n"
    "ことはありません。\n\n"
    "本機能のご利用は私的複製の範囲内で、お客様の責任で行ってください。\n"
    "本アプリは KONAMI 公式とは無関係です。"
)


class BannerConsentDialog(QDialog):
    """バナー画像取得の同意取得用モーダル。

    返り値（accept 時）:
    - `consented_at` プロパティに ISO8601 文字列が入る（app_kv へ保存用）
    - `do_not_show_again` プロパティに「次回から表示しない」のチェック状態
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("バナー画像の取得について")
        self.setModal(True)

        layout = QVBoxLayout(self)

        body = QLabel(CONSENT_BODY)
        body.setWordWrap(True)
        body.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(body)

        self._do_not_show_again = QCheckBox("次回から表示しない")
        layout.addWidget(self._do_not_show_again)

        buttons = QDialogButtonBox(self)
        self._accept_btn = buttons.addButton(
            "同意して取得開始", QDialogButtonBox.AcceptRole
        )
        buttons.addButton("キャンセル", QDialogButtonBox.RejectRole)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._consented_at: str | None = None

    @property
    def consented_at(self) -> str | None:
        return self._consented_at

    @property
    def do_not_show_again(self) -> bool:
        return self._do_not_show_again.isChecked()

    def accept(self) -> None:  # type: ignore[override]
        self._consented_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        super().accept()


def has_existing_consent(app_kv_repo) -> bool:
    """app_kv に同意が保存済みかを確認する（"次回から表示しない" 後の判定用）。"""
    return app_kv_repo.get(CONSENT_KEY) is not None


def record_consent(app_kv_repo, consented_at: str) -> None:
    """app_kv に同意のタイムスタンプを記録する。"""
    app_kv_repo.set(CONSENT_KEY, consented_at)
