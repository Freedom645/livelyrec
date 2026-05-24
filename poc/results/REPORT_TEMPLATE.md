# OCRエンジン選定 PoC レポート（テンプレート）

> 実行結果を反映する正式版は `docs/poc/01_ocr_engine_selection.md` に作成。

## 1. 目的

基本設計書 §4.8 に基づき、LivelyRec における OCR エンジンとして PaddleOCR が
LivelyRec のスコープ（pop'n music lively のプレイ画面・リザルト画面の認識）で
合格基準を満たすかを評価する。

## 2. 実行環境

- Python: 3.11.5
- PaddleOCR: 3.5.0
- paddlepaddle: 3.3.1
- OS: Windows 11
- 環境変数: `FLAGS_use_mkldnn=0`（PaddlePaddle 3.x の oneDNN PIR 既知不具合回避）

## 3. 評価対象

- 入力: `docs/sample/` 配下の全画像（29枚）
- Ground Truth: `poc/ground_truth.yaml`（楽曲名のみ確実、数値は OCR 出力レビュー後に追記予定）

## 4. 合格基準（基本設計 §4.8）

- 楽曲名認識正答率: ≥95%
- 数字認識正答率: ≥99%
- 平均処理時間: ≤200ms/枚

## 5. 結果サマリ

（PoC 実行結果から自動転記）

## 6. 採用判定

（合否を記載。不合格項目があればその原因と次のアクションを記載）

## 7. 既知の問題

- PaddlePaddle 3.3.1 + oneDNN PIR の組合せで OCR 実行不能だったため、
  oneDNN を無効化して動作させた（処理速度は低下する可能性）。

## 8. 次のアクション

- （採用ならば）詳細設計工程へ移行
- （不採用ならば）Tesseract の評価へ移行、または前処理方針見直し
