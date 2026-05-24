---
title: LivelyRec
---

# LivelyRec

**pop'n music lively** のゲーム画面を OBS 経由で取得し、スコアを自動記録 + 配信支援オーバーレイを提供するスタンドアロン **Windows アプリ**です。

[GitHub リポジトリ](https://github.com/Freedom645/livelyrec) ｜ [リリース（準備中）](https://github.com/Freedom645/livelyrec/releases)

---

## 主な機能

- OBS WebSocket からゲーム画面を取得し、画像認識で **スコア・楽曲・難易度** を自動判定
- リザルト画面で **スコアを記録**（SQLite 保存 + CSV 出力）
- **OBS ブラウザソース向けオーバーレイ** — 打鍵数・直近リザルト・楽曲情報をライブ表示
- **プレイ日**（午前 ◯ 時切替）単位の打鍵数集計
- スタンドアロン portable 構成（`livelyrec_data/` にすべてのユーザデータを集約）

## クイックスタート

> 詳細な使い方ページは準備中です。

1. [Releases](https://github.com/Freedom645/livelyrec/releases) から最新の `LivelyRec.zip` をダウンロード（公開後）
2. 任意のフォルダに展開し、`LivelyRec.exe` を起動
3. OBS 側で WebSocket を有効化（ツール → WebSocket サーバ設定）
4. アプリの「設定」から OBS 接続情報・キャプチャソースを指定して保存
5. 「記録開始」をクリックして遊ぶ

## 配信支援オーバーレイ

OBS に **ブラウザソース** を追加し、アプリ画面に表示される URL（既定 `http://127.0.0.1:14514/browser/index.html`）を指定してください。打鍵数・直近スコアがリアルタイムに表示されます。

## ドキュメント

開発用の設計文書（要件定義・基本設計・詳細設計・テスト計画書 等）は GitHub 上で公開しています:

- [設計文書一覧（docs/design/）](https://github.com/Freedom645/livelyrec/tree/main/docs/design)

## ライセンス

[MIT License](https://github.com/Freedom645/livelyrec/blob/main/LICENSE)
