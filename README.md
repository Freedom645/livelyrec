# LivelyRec

pop'n music lively のゲーム画面を OBS WebSocket 経由で取得し、画像認識によりスコアを自動記録、OBS ブラウザソース向けの配信支援表示を提供するスタンドアロン Windows アプリ。

## ドキュメント / 使い方ガイド

導入から配信支援オーバーレイの設定まで、画像付きの解説を **[公式ガイド（GitHub Pages）](https://freedom645.github.io/livelyrec/)** にまとめています。

## ダウンロード

最新版は **[GitHub Releases](https://github.com/Freedom645/livelyrec/releases/latest)** から入手できます。

## 動作環境

- Windows 10 (21H2 以降) 64bit、または Windows 11
- OBS Studio 28 以降（WebSocket v5 同梱版）
- pop'n music lively（コナステ）の正規プレイ環境

## ポータブル構成

LivelyRec は **常時ポータブル** で動作します。

- 配布フォルダを **書き込み可能な場所**（ドキュメント、デスクトップなど）に展開してください。
- Program Files 配下や OneDrive 同期フォルダなど、書込み制限のある場所には展開しないでください。
- ユーザデータはすべて `livelyrec_data/` 配下に保存されます。
- **アプリを移動する際はフォルダごと丸ごと** 移動してください。`LivelyRec.exe` 単体をコピーするとデータが失われます。

## 開発者向け

### 環境構築

[uv](https://docs.astral.sh/uv/) を使用します。

```bash
# 開発用一式（dev グループは既定で入る。OCR 抜きの軽量セット）
uv sync

# OCR エンジン（PaddleOCR）も含めたフルセット
uv sync --extra ocr
```

`uv` は `pyproject.toml` の `requires-python` に従って Python 3.11 を自動取得します。

### 開発実行

```bash
uv run python -m livelyrec.app
```

### テスト

```bash
uv run pytest
```

### ビルド

```bash
pyinstaller LivelyRec.spec --noconfirm
```

## ライセンス

MIT License（予定）

pop'n music は KONAMI Amusement の登録商標です。本ソフトウェアは KONAMI Amusement とは関係ありません（非公式ツール）。
