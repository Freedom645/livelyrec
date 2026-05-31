---
title: インストール
---

# インストール

[トップ](./) ｜ **インストール** ｜ [使い方](usage.html) ｜ [配信支援オーバーレイ](broadcast.html)

## 1. ダウンロード

[Releases ページ](https://github.com/Freedom645/livelyrec/releases){:target="_blank"} から最新の `LivelyRec-vX.Y.Z-windows-x64.zip` をダウンロードしてください。

> 初回リリース前は GitHub Actions の "Release" ワークフローでビルドが完成するまでアセットがありません。

## 2. 展開

任意のフォルダに ZIP を展開してください。たとえば `C:\Tools\LivelyRec\` など。

> **portable 構成**: アプリは展開先フォルダだけで動作します。設定・データはすべて `livelyrec_data/` サブフォルダに保存されます。**インストーラ不要・レジストリ非汚染**。

展開後のフォルダ構成（抜粋）:

```
LivelyRec/
├── LivelyRec.exe          ← 起動用
├── _internal/             ← Python ランタイム・依存ライブラリ
├── browser_source/        ← 配信支援HTMLオーバーレイ
└── （初回起動後に作成される）
    └── livelyrec_data/
        ├── db/            SQLite データベース
        ├── logs/          ログ
        ├── export/        CSV 出力先
        └── settings.json  設定
```

## 3. 初回起動

`LivelyRec.exe` をダブルクリックで起動します。Windows Defender SmartScreen の警告が出る場合は「詳細情報」→「実行」で先へ進めてください（実行ファイルに署名が無いため）。

初回起動時は OBS 接続情報が未設定なので、**画面右上「設定」ボタン**から接続情報を入力してください。詳細は [使い方](usage.html) を参照。

## 4. アップデート

新しいバージョンが Releases に公開された場合:

- アプリ内の「アップデート確認」（メニューまたは設定タブ）で確認・自動取得が可能
- 手動でアップデートする場合は、現フォルダの `LivelyRec.exe` と `_internal/` を新バージョンの中身で置き換えます。**`livelyrec_data/` は触らずに残してください**（設定・記録が保持されます）

## ソースから動かす場合（開発者向け）

[uv](https://docs.astral.sh/uv/) を使用します。

```bash
git clone https://github.com/Freedom645/livelyrec.git
cd livelyrec
uv sync --extra ocr
uv run python -m livelyrec.app
```

Python 3.11 必須（`uv` が `pyproject.toml` の指定に従い自動取得します）。
