# 詳細設計書: API設計編

| 項目 | 内容 |
|------|------|
| プロダクト名 | LivelyRec |
| 版数 | 0.1（ドラフト） |
| 作成日 | 2026-05-18 |
| 関連資料 | `05_基本設計書.md` §7、`06_詳細設計_アーキテクチャ.md`、`07_詳細設計_DB設計.md` |

> LivelyRec が公開する外部 I/F（WebSocket Server、ファイル出力）と、内部で利用する OBS WebSocket クライアント、GitHub クライアントの仕様を確定する。

---

## 1. WebSocket Server（外部公開）

### 1.1. エンドポイント

| 項目 | 値 |
|------|-----|
| URL | `ws://<host>:<port>/v1` |
| デフォルトバインド | `127.0.0.1:14514` |
| プロトコル | RFC 6455 WebSocket |
| サブプロトコル | なし |
| メッセージ形式 | JSON、UTF-8 |
| バージョニング | パスに `/v1`。破壊的変更時は `/v2` を立てる |

### 1.2. 認証

| 設定 | 認証 | 用途 |
|------|------|------|
| `lan_publish: false`（既定、127.0.0.1） | なし | 同一PC内（OBSブラウザソース等） |
| `lan_publish: true`（任意のIPバインド） | **トークン必須** | LAN内の別PCからの接続 |

トークン認証方式:

- 32バイト乱数を Base64 (URLセーフ) でエンコード（`livelyrec_token_xxxxxxxxxxxxx`）。
- 接続時の HTTP Header `Authorization: Bearer <token>` で送信。
- ヘッダなし or 不一致時は HTTP 401 で接続拒否。

### 1.3. メッセージ形式

すべてのメッセージは以下のエンベロープを持つ:

```json
{
  "type": "<message_type>",
  "ts": "2026-05-18T15:30:00.123+09:00",
  "schema": "v1",
  "payload": { ... }
}
```

- `type`: 後述の通知/要求/応答の種別文字列
- `ts`: 送信側のローカル時刻（ISO 8601 + offset）
- `schema`: `v1` 固定
- `payload`: 種別ごとのスキーマ

### 1.4. サーバ → クライアント（通知）

#### 1.4.1. `state.changed`

接続状態・記録状態の変化を通知。

```json
{
  "type": "state.changed",
  "ts": "2026-05-18T15:30:00.123+09:00",
  "schema": "v1",
  "payload": {
    "recording_state": "RECORDING",
    "screen": "PLAY",
    "previous_screen": "READY",
    "obs_connected": true
  }
}
```

| キー | 型 | 内容 |
|------|----|------|
| `recording_state` | `"INITIAL"|"CONNECTING"|"RECORDING_UNKNOWN"|"RECORDING"|"STOPPED"` | 全体状態 |
| `screen` | `"UNKNOWN"|"SELECT"|"READY"|"OPTION"|"PLAY"|"PLAY_READY"|"RESULT"|"LOAD_TO_PLAY"|"LOAD_TO_READY"` | 現在画面 |
| `previous_screen` | 同上 | 直前画面 |
| `obs_connected` | bool | OBS接続状態 |

#### 1.4.2. `chart.selected`

選曲画面でカーソル上の譜面が変化したとき。

```json
{
  "type": "chart.selected",
  "ts": "...",
  "schema": "v1",
  "payload": {
    "chart": {
      "chart_id": "popn-12345:HYPER:false",
      "song_id": "popn-12345",
      "title": "ぽぽぽかレトロード",
      "genre": "ぽかぽかレトロード",
      "difficulty": "HYPER",
      "is_upper": false,
      "level": 36
    },
    "identified": true,
    "confidence": 0.92
  }
}
```

特定不能時は `identified: false, chart: null`。

#### 1.4.3. `play.started`

プレイ画面突入を検知。

```json
{
  "type": "play.started",
  "ts": "...",
  "schema": "v1",
  "payload": {
    "session_id": "abc...",
    "chart": { ... },
    "business_date": "2026-05-18"
  }
}
```

#### 1.4.4. `judgements.tick`

プレイ中の判定数差分・累計を通知。

```json
{
  "type": "judgements.tick",
  "ts": "...",
  "schema": "v1",
  "payload": {
    "session_id": "abc...",
    "delta": {"cool": 1, "great": 0, "good": 0, "bad": 0},
    "session_total": {"cool": 312, "great": 18, "good": 5, "bad": 2},
    "daily_total": {"cool": 12345, "great": 2345, "good": 123, "bad": 45, "total": 14858}
  }
}
```

#### 1.4.5. `play.retry`

リトライ検出。

```json
{
  "type": "play.retry",
  "ts": "...",
  "schema": "v1",
  "payload": {
    "session_id": "abc...",
    "attempt_count": 2
  }
}
```

#### 1.4.6. `result.recorded`

リザルト画面の記録完了。**楽曲名検出失敗（FR-REC-039）時は `chart: null, display_title: "検出失敗"` で配信する**（payload 構造は同一）。

```json
{
  "type": "result.recorded",
  "ts": "...",
  "schema": "v1",
  "payload": {
    "session_id": "abc...",
    "chart": { ... },                  // 検出失敗時は null
    "display_title": "ぽぽぽかレトロード",
    "result": {
      "score": 87268,
      "judgements": {"cool": 312, "great": 18, "good": 5, "bad": 2},
      "combo": 329,
      "clear_type": "CLEAR",
      "medal": "DIAMOND_SILVER",
      "rank": "AAA",
      "best_score_diff": 1234
    }
  }
}
```

#### 1.4.7. `business_day.rolled`

業務日切替の通知。

```json
{
  "type": "business_day.rolled",
  "ts": "...",
  "schema": "v1",
  "payload": {
    "previous_date": "2026-05-18",
    "current_date": "2026-05-19",
    "rolled_at": "2026-05-19T06:00:00+09:00"
  }
}
```

#### 1.4.8. `now_playing.changed`（新規 / FR-STR-007 ②、FR-STR-008）

「現在のプレイ楽曲」ブラウザソースが購読する通知。プレイ画面突入時／楽曲特定の確定時／検出失敗の確定時にブロードキャストする。

```json
{
  "type": "now_playing.changed",
  "ts": "...",
  "schema": "v1",
  "payload": {
    "session_id": "abc...",
    "identified": true,
    "chart": { ... },                  // identified=false の場合 null
    "display_title": "ぽぽぽかレトロード",
    "business_date": "2026-05-18"
  }
}
```

楽曲名検出失敗（FR-REC-039）時:

```json
{
  "type": "now_playing.changed",
  "ts": "...",
  "schema": "v1",
  "payload": {
    "session_id": "abc...",
    "identified": false,
    "chart": null,
    "display_title": "検出失敗",
    "business_date": "2026-05-18"
  }
}
```

| キー | 型 | 内容 |
|------|----|------|
| `session_id` | string | 当該プレイセッション |
| `identified` | bool | 楽曲特定の成否 |
| `chart` | Chart \| null | 特定成功時のみ詳細を含む |
| `display_title` | string | 表示用文字列。特定失敗時は **固定文言「検出失敗」** |
| `business_date` | string | "YYYY-MM-DD" |

### 1.5. クライアント → サーバ（要求）

#### 1.5.1. `chart.history.request`

譜面の過去リザルトを要求。

```json
{
  "type": "chart.history.request",
  "ts": "...",
  "schema": "v1",
  "payload": {
    "request_id": "req-001",
    "chart_id": "popn-12345:HYPER:false",
    "limit": 5
  }
}
```

応答: `chart.history.response`

```json
{
  "type": "chart.history.response",
  "ts": "...",
  "schema": "v1",
  "payload": {
    "request_id": "req-001",
    "chart_id": "popn-12345:HYPER:false",
    "best_score": 92407,
    "best_recorded_at": "2026-05-10T12:34:56+09:00",
    "history": [
      {
        "session_id": "...",
        "recorded_at": "...",
        "score": 92407,
        "judgements": {...},
        "combo": 350,
        "clear_type": "FULL_COMBO",
        "medal": "STAR_GOLD",
        "rank": "S+",
        "best_score_diff": 1200
      },
      ...
    ]
  }
}
```

#### 1.5.2. `recent.history.request`（新規 / FR-STR-009、`/browser/recent` 用）

DB 全履歴から最新 N 件のプレイ履歴を要求。

```json
{
  "type": "recent.history.request",
  "ts": "...",
  "schema": "v1",
  "payload": {
    "request_id": "req-003",
    "limit": 10
  }
}
```

応答: `recent.history.response`

```json
{
  "type": "recent.history.response",
  "ts": "...",
  "schema": "v1",
  "payload": {
    "request_id": "req-003",
    "entries": [
      {
        "session_id": "abc...",
        "started_at": "2026-05-27T19:30:45+09:00",
        "chart": { ... },                 // 検出失敗時は null
        "display_title": "ぽぽぽかレトロード",  // 検出失敗時は "検出失敗"
        "difficulty": "HYPER",            // 検出失敗時は null
        "score": 87268,
        "clear_type": "CLEAR",
        "rank": "AAA"
      },
      ...
    ]
  }
}
```

- `entries` は時刻降順、最大 `limit` 件。
- `limit` は省略時 10、許容範囲 1〜50。範囲外は `INVALID_REQUEST` エラー応答。
- リザルト記録時の `result.recorded` ブロードキャストでクライアント側がリスト先頭に追加する push 更新も行うため、本要求は初回接続時の同期に用いる。

#### 1.5.3. `daily_keycount.request`

業務日累計を要求。

```json
{
  "type": "daily_keycount.request",
  "ts": "...",
  "schema": "v1",
  "payload": {
    "request_id": "req-002",
    "business_date": "2026-05-18"
  }
}
```

応答: `daily_keycount.response`

```json
{
  "type": "daily_keycount.response",
  "ts": "...",
  "schema": "v1",
  "payload": {
    "request_id": "req-002",
    "business_date": "2026-05-18",
    "counts": {"cool": 12345, "great": 2345, "good": 123, "bad": 45, "total": 14858}
  }
}
```

### 1.6. エラー

```json
{
  "type": "error",
  "ts": "...",
  "schema": "v1",
  "payload": {
    "request_id": "req-001",
    "code": "INVALID_REQUEST",
    "message": "chart_id is required"
  }
}
```

エラーコード一覧:

| code | 意味 |
|------|------|
| `INVALID_REQUEST` | スキーマ違反、必須欠落 |
| `NOT_FOUND` | 指定した chart_id が DB に存在しない |
| `INTERNAL` | サーバ内部エラー |
| `AUTH_REQUIRED` | 認証必須なのに未認証 |
| `AUTH_INVALID` | トークン不一致 |

### 1.7. 接続ライフサイクル

```
1. Client → ws://host:port/v1 接続
   (LAN公開時、settings.json に token 明示設定がある場合のみ Authorization ヘッダ必須)
2. Server: 接続確立直後に最新の state.changed と now_playing.changed をスナップショット送信
3. 双方向メッセージ送受
4. クライアント切断時は何もせず破棄
```

### 1.8. ブラウザソース別の購読・要求パターン

| ブラウザソース | 購読メッセージ | 起動時要求 |
|----------------|----------------|------------|
| `/browser/keycount/` | `judgements.tick`, `business_day.rolled`, `state.changed` | `daily_keycount.request` |
| `/browser/now-playing/` | `now_playing.changed`, `state.changed` | なし（接続時に Server がスナップショット送信） |
| `/browser/now-playing-history/` | `now_playing.changed`, `result.recorded` | 受信した `chart_id` を起点に `chart.history.request` |
| `/browser/recent/` | `result.recorded` | `recent.history.request`（limit=10） |

### 1.9. バックプレッシャ

- 送信キュー上限: クライアントごとに **100 件**。
- 上限超過時は **古いものから破棄** し、WARN ログ出力。
- これにより配信支援ブラウザソース側のスローダウン時にも本体が詰まらない。

### 1.10. 静的ファイル配信パス（FR-STR-007 / FR-STR-010）

WebSocket Server に併設した HTTP 静的ファイル配信は以下のパス構成とする（v1.x 移行で **既存の `/browser/index.html` 配信は廃止**、404 を返す）。

| URL パス | マウント元 | 用途 |
|----------|------------|------|
| `/browser/keycount/` | `browser_source/keycount/index.html` | 打鍵数カウンタ |
| `/browser/now-playing/` | `browser_source/now_playing/index.html` | 現在のプレイ楽曲 |
| `/browser/now-playing-history/` | `browser_source/now_playing_history/index.html` | 直近プレイ楽曲のスコア履歴 |
| `/browser/recent/` | `browser_source/recent/index.html` | 直近 10 件履歴 |

末尾 `/` を含まないアクセス（`/browser/keycount`）は `/browser/keycount/` へ 301 リダイレクト。`/browser/` 直下にはランディングページとして 4 ソースへのリンク集 `index.html` を配置する。

---

## 2. OBS WebSocket クライアント

### 2.1. ライブラリ

`obs-websocket-py`（同期クライアント）を採用。OBS WebSocket v5 対応。2026-05-20 工程7で `simpleobsws`（非同期）から移行（I-010〜I-013）。

### 2.2. 使用オペレーション

| Request | 用途 |
|---------|------|
| `GetVersion` | バージョン確認（互換性チェック） |
| `GetSceneList` | シーン一覧取得（設定 UI 用） |
| `GetSourceScreenshot` | ゲーム画面のキャプチャ取得 |

`GetSourceScreenshot` パラメタ:

```json
{
  "sourceName": "popn-game",
  "imageFormat": "png",
  "imageWidth": 1366,
  "imageHeight": 768
}
```

返り値はBase64エンコードされたPNGデータ。

### 2.3. 再接続戦略

```
attempt 0: 即座
attempt 1: 1秒後
attempt 2: 2秒後
attempt 3: 4秒後
attempt 4: 8秒後
attempt 5: 16秒後
それ以降: 30秒間隔で無制限（手動停止まで）
```

エラー区別:
- 認証失敗 → 再接続せず UI に通知
- ネットワークエラー → 上記バックオフで再試行

---

## 3. ファイル出力（外部連携）

### 3.1. 出力先

設定で指定するディレクトリ。既定: `<配布フォルダ>/livelyrec_data/export/`（ポータブル構成）

### 3.2. ファイル仕様

| ファイル名 | 内容 | 更新タイミング |
|-----------|------|----------------|
| `current_state.json` | 現在状態（recording/screen等）と現在カーソル譜面 | state.changed / chart.selected 発火時 |
| `latest_result.json` | 直近のリザルト1件。検出失敗時は `chart: null, display_title: "検出失敗"` | result.recorded 発火時 |
| `daily_keycount.json` | 当日業務日の累計判定数 | judgements.tick / business_day.rolled 発火時 |
| `session_in_progress.json` | プレイ中セッション情報。検出失敗時も同様に出力 | play.started/judgements.tick/now_playing.changed |
| `now_playing.json` | 現在のプレイ楽曲（display_title を含む）。検出失敗時は `"検出失敗"` | now_playing.changed 発火時 |
| `recent_history.json` | DB 最新 10 件のプレイ履歴 | result.recorded 発火時に再生成 |

### 3.3. アトミック書込み

```python
def atomic_write_json(path: Path, data: dict) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)
```

ファイル監視ベースの読込側がファイルを途中状態で読まないよう保証する。

### 3.4. スキーマ

WebSocket メッセージの `payload` をほぼそのままシリアライズ。`schema` フィールドで版管理（`"v1"`）。

---

## 4. CSV エクスポート

### 4.1. 既定仕様

| 項目 | 既定値 | オプション |
|------|--------|-----------|
| 文字コード | UTF-8 (BOM あり) | BOMなし指定可 |
| 区切り | カンマ | TAB 指定可 |
| 改行 | CRLF（Windows既定） | LF 指定可 |
| 引用 | minimal（必要時のみダブルクォート） | always 指定可 |

### 4.2. デフォルト出力列

| 列名 | 内容 |
|------|------|
| `business_date` | プレイ業務日 |
| `recorded_at` | 記録時刻（ISO 8601） |
| `genre` | ジャンル名 |
| `title` | 楽曲タイトル |
| `difficulty` | 難易度（EASY/NORMAL/HYPER/EX/UPPER） |
| `level` | 難易度値 |
| `score` | スコア |
| `cool` / `great` / `good` / `bad` | 判定数 |
| `combo` | コンボ数 |
| `clear_type` | クリア種類 |
| `medal` | クリアメダル |
| `rank` | クリアランク |

### 4.3. 文字置換ルール

環境依存文字の置換テーブルを `livelyrec/application/csv_charset.py` に定義:

| 元文字 | 置換 |
|-------|------|
| `♥` `❤` | `♥` 維持（UTF-8では問題なし。Shift-JIS 出力時のみ `(H)` に置換） |
| `〜` | `〜` 維持（UTF-8）／`～` 置換（Shift-JIS） |
| その他 機種依存 | 同様 |

`UnicodeEncodeError` 発生時は置換 → ログに WARN を出して継続。

---

## 5. GitHub クライアント

### 5.1. Releases API

エンドポイント: `https://api.github.com/repos/<owner>/<repo>/releases/latest`

ヘッダ: `Accept: application/vnd.github+json`, `User-Agent: LivelyRec/<version>`

レート制限: 認証なしで 60 req/hour。アプリ起動時 1 回のみ呼ぶため十分。

### 5.2. アセットダウンロード

リリースの `assets[].browser_download_url` を取得 → HTTP GET → ローカルファイル書き込み → SHA-256 チェックサム検証。

### 5.3. マスタ JSON 取得

エンドポイント例: `https://<owner>.github.io/livelyrec/master.json`

```
GET master.json
ETag-based caching
   1. ローカルキャッシュに ETag がある → If-None-Match で送信
   2. 304 Not Modified → キャッシュ使用
   3. 200 OK → 新規取得 + ETag 更新
```

---

## 6. JSON Schema（最低限）

正式な JSON Schema は本書末尾の `appendix_schemas/` 配下に `livelyrec-v1.schema.json` として配置（実装時に追加）。本書では型定義のみ列挙。

### 6.1. 共通型

```ts
type RecordingState = "INITIAL" | "CONNECTING" | "RECORDING_UNKNOWN" | "RECORDING" | "STOPPED";
type ScreenType = "UNKNOWN" | "SELECT" | "READY" | "OPTION" | "PLAY" | "PLAY_READY" | "RESULT" | "LOAD_TO_PLAY" | "LOAD_TO_READY";
type Difficulty = "EASY" | "NORMAL" | "HYPER" | "EX" | "UPPER";
type ClearType = "PERFECT" | "FULL_COMBO" | "CLEAR" | "FAILED";
type Medal = "STAR_GOLD" | "STAR_SILVER" | "STAR_BRONZE" | "DIAMOND_GOLD" | "DIAMOND_SILVER" | "DIAMOND_BRONZE" | "CIRCLE" | "NONE";
type Rank = "S+" | "S" | "AAA" | "AA+" | "AA" | "A+" | "A" | "B+" | "B" | "C+" | "C" | "D" | "E";

interface Chart {
  chart_id: string;
  song_id: string;
  title: string;
  genre: string | null;
  difficulty: Difficulty;
  is_upper: boolean;
  level: number | null;
}

interface Judgements {
  cool: number;
  great: number;
  good: number;
  bad: number;
}

interface ResultPayload {
  score: number;
  judgements: Judgements;
  combo: number;
  clear_type: ClearType;
  medal: Medal;
  rank: Rank;
  best_score_diff: number | null;
}
```

---

## 7. 詳細設計の他編との関係

- WebSocket Server の実装は `infrastructure/ws_server.py`（`06_詳細設計_アーキテクチャ.md` §1, §4）
- メッセージ生成元: `RecordingService` / `AnalysisService`
- `chart.history.request` の応答は `ResultRepository.list_by_chart()`（`07_詳細設計_DB設計.md` §4）を呼ぶ
- 配信支援ブラウザソース（`browser_source/index.html`）が本仕様を消費（`09_詳細設計_UI設計.md`）

---

## 8. 承認

| 役割 | 氏名 | 日付 | 結果 |
|------|------|------|------|
| プロダクトオーナー | （ユーザ） | YYYY-MM-DD | 承認／差戻し |

---

## 改訂履歴

| 版 | 日付 | 内容 | 改訂者 |
|----|------|------|--------|
| 0.1 | 2026-05-18 | 初版作成 | Claude Code |
| 0.2 | 2026-05-18 | ファイル出力先をポータブル構成（livelyrec_data/export/）に変更 | Claude Code |
| 0.3 | 2026-05-27 | v1.x 機能追加: now_playing.changed / recent.history.request/response を新設、result.recorded に display_title を追加（検出失敗時 "検出失敗"）、ブラウザソース URL 構成を 4 ソース独立配信に再定義（§1.10）、§1.8 にソース別購読パターン、ファイル出力に now_playing.json / recent_history.json を追加 | Claude Code |
