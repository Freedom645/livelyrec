# LivelyRec

pop'n music lively のゲーム画面を OBS WebSocket 経由で取得し、画像認識によりスコアを自動記録、OBS ブラウザソース向けの配信支援表示を提供するスタンドアロン Windows アプリ。

## 配布ページ

最新版および利用方法はこちら → **[https://Freedom645.github.io/livelyrec/](https://Freedom645.github.io/livelyrec/)**

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

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev]"
```

または:

```bash
pip install -r requirements-dev.txt
```

### 開発実行

```bash
python -m livelyrec.app
```

### テスト

```bash
pytest
```

### ビルド

```bash
pyinstaller LivelyRec.spec --noconfirm
```

## ライセンス

MIT License（予定）

pop'n music は KONAMI Amusement の登録商標です。本ソフトウェアは KONAMI Amusement とは関係ありません（非公式ツール）。
