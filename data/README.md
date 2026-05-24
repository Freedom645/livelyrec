# data/

LivelyRec で利用するマスタデータ等を格納するディレクトリ。

## master.json

公式サイト「pop'n music lively 収録楽曲一覧」からスクレイピングした楽曲マスタ。

- 生成スクリプト: `scripts/build_master.py`
- スキーマ: `docs/05_基本設計書.md §6.1` / `docs/08_詳細設計_API設計.md §5.3` 参照
- 楽曲数: 1347（2026-05-18 時点）

### 配信方法

将来 GitHub Pages 等にホストし、`settings.json` の `master.endpoint_url` に
そのURLを設定する。配信開始までは本ファイルをローカルファイル参照する運用も可能。

### 再生成

```bash
python scripts/build_master.py --out data/master.json
```

### 未整備の情報

- **難易度別レベル**（EASY / NORMAL / HYPER / EX の各 level）: 公式サイトに掲載されていないため初期値は `null`
- ジャンル名（pop'n の表示で大きく出る ジャンル名 / 楽曲名 の関係）
- UPPER 譜面の有無

#### 難易度レベルの自動取得が困難な理由
- 上級攻略Wiki（[https://popn.wiki/](https://popn.wiki/)）は Nuxt.js ベースの SPA で、初期 HTML にデータが含まれず、サーバサイドスクレイピング不可
- asagaolabo Wiki（[https://w.atwiki.jp/asagaolabo/](https://w.atwiki.jp/asagaolabo/)）は構造化された難易度一覧が無い

#### 当面の対応: 手動収集 CSV のマージ機能

ユーザが手動収集（コミュニティ協力等）したレベルデータを CSV で取り込み、生成時にマージできます。

```bash
python scripts/build_master.py --out data/master.json --levels-from data/levels.csv
```

CSV 形式（ヘッダあり、UTF-8 もしくは UTF-8 BOM）:

```csv
title,difficulty,level
ぽかぽかレトロード,EASY,8
ぽかぽかレトロード,NORMAL,24
ぽかぽかレトロード,HYPER,36
ぽかぽかレトロード,EX,42
```

JSON 形式も受付:

```json
[
  {"title": "ぽかぽかレトロード", "difficulty": "HYPER", "level": 36}
]
```

`data/levels.sample.csv` にサンプルあり。本番運用ではコミュニティ協力等で
全1347曲ぶんの CSV を整備し、リポジトリに `data/levels.csv` として置く想定。
