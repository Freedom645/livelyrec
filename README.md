# LivelyRec

pop'n music lively のゲーム画面を OBS WebSocket 経由で取得し、画像認識によりスコアを自動記録、OBS ブラウザソース向けの配信支援表示を提供するスタンドアロン Windows アプリ。

> 詳細は `docs/` 配下のドキュメント参照。
> プロジェクト計画書: [docs/design/01_プロジェクト計画書.md](docs/design/01_プロジェクト計画書.md)

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

### サポート依頼時

不具合報告時は `livelyrec_data/` フォルダごと ZIP にして送付してください。ただし `settings.json` 内に **OBS パスワードや WebSocket トークンが平文** で含まれているため、共有前に必ず削除してください。設定UIの「パスワードを保存しない」オプションでも回避できます。

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
pyinstaller --noconfirm --windowed --name LivelyRec --add-data "browser_source;browser_source" --add-data "templates;templates" livelyrec/app.py
```

## ドキュメント

| ドキュメント | 内容 |
|--------------|------|
| [00_要件.md](docs/design/00_要件.md) | オリジナル要件メモ |
| [01_プロジェクト計画書.md](docs/design/01_プロジェクト計画書.md) | プロジェクト計画 |
| [02_要件定義書.md](docs/design/02_要件定義書.md) | 機能/非機能要件 |
| [03_用語集.md](docs/design/03_用語集.md) | ドメイン用語 |
| [04_リスク・課題管理表.md](docs/design/04_リスク・課題管理表.md) | リスク・課題 |
| [05_基本設計書.md](docs/design/05_基本設計書.md) | 基本設計 |
| [06_詳細設計_アーキテクチャ.md](docs/design/06_詳細設計_アーキテクチャ.md) | アーキテクチャ詳細 |
| [07_詳細設計_DB設計.md](docs/design/07_詳細設計_DB設計.md) | DB設計詳細 |
| [08_詳細設計_API設計.md](docs/design/08_詳細設計_API設計.md) | API設計詳細 |
| [09_詳細設計_UI設計.md](docs/design/09_詳細設計_UI設計.md) | UI設計詳細 |
| [10_詳細設計_画像認識.md](docs/design/10_詳細設計_画像認識.md) | 画像認識詳細 |
| [docs/design/poc/](docs/design/poc/) | PoC #01-#03 結果 |

## ライセンス

MIT License（予定）

pop'n music は KONAMI Amusement の登録商標です。本ソフトウェアは KONAMI Amusement とは関係ありません（非公式ツール）。
