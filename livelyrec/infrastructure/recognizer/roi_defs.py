"""ROI 座標定義（基準解像度: 1366x768）。

詳細: docs/design/10_詳細設計_画像認識.md §4

座標は (x1, y1, x2, y2) 形式（包含端点）。
2026-05-19 にユーザ目視計測値で全 ROI を更新。
"""

from __future__ import annotations

Box = tuple[int, int, int, int]  # (x1, y1, x2, y2)


# プレイ画面 ROI
# - genre: pop'n music lively の現行 UI では表示されないため定義しない
PLAY_ROI: dict[str, Box] = {
    "song_name":  (452, 0, 915, 60),
    "difficulty": (923, 9, 968, 52),
    "score":      (120, 597, 388, 655),
    "combo":      (174, 696, 346, 745),
    "speed":      (1285, 623, 1334, 649),
}

# プレイ画面の判定数表示帯（GROOVE GAUGE 下）。
# 「BAD｜GOOD｜GREAT｜COOL」が左から並び、各判定は固有色（水色/赤/黄/マゼンタ）。
# 値 0 の判定は非表示。色マスクで判定ごとに分離して右端 4 桁を読む。
# y は GROOVE GAUGE の青帯を除外するため 736 から取る。
PLAY_JUDGE_ROI: Box = (425, 736, 935, 768)

# プレイ画面の難易度バッジ内のテーマ色サンプル領域（ユーザ目視計測 2026-05-22）。
# バッジ円のテーマ色: EASY=水色 / NORMAL=緑 / HYPER=橙 / EX=桃。
PLAY_DIFFICULTY_ROI: Box = (943, 47, 949, 50)


# リザルト画面 ROI
# - 判定数（cool/great/good/bad）は color mask + 連結成分で各桁を切り出すため、
#   数字の見た目領域にできるだけ近いタイトな矩形を採用する。
RESULT_ROI: dict[str, Box] = {
    "clear_label": (577, 117, 863, 148),
    "score":       (652, 423, 864, 466),
    "cool":        (762, 483, 861, 509),
    "great":       (762, 510, 861, 536),
    "good":        (762, 537, 861, 563),
    "bad":         (762, 564, 861, 590),
    "combo":       (762, 609, 861, 635),
    "best_score":  (738, 648, 863, 674),
    "best_diff":   (738, 675, 863, 701),
    # 開発者向けバナー画像クロップ領域（FR-DEV-002、PO 指定 x=489,y=233,w=390,h=94）。
    "banner":      (489, 233, 879, 327),
}


# 選曲画面 ROI
SELECT_ROI: dict[str, Box] = {
    "logo":       (117, 274, 505, 366),
    "difficulty": (566, 258, 633, 276),
    "level":      (577, 302, 630, 339),
    "artist":     (179, 378, 591, 411),
}


# オプション画面 ROI
OPTION_ROI: dict[str, Box] = {
    "logo":  (832, 26, 1103, 89),
    "level": (1119, 38, 1167, 75),
}


# 準備画面 ROI
PREPARE_ROI: dict[str, Box] = {
    "logo":       (490, 210, 878, 302),
    "difficulty": (547, 177, 641, 208),
    "level":      (497, 170, 544, 205),
    "artist":     (495, 361, 871, 394),
    "speed":      (796, 441, 872, 466),
}


# プレイ画面前ロード ROI
# - 「Let's enjoy music!」表示時に出る赤色・橙色領域。
#   面積比 + 平均色で画面判別する用途。
PRELOAD_ROI: dict[str, Box] = {
    "red_region":    (338, 334, 400, 424),
    "orange_region": (435, 455, 497, 508),
}


# 画面判別用の特徴領域
# 右下シグネチャ方式（推奨）: 右下のテンキー/ステータス領域は画面ごとに固有色なので、
# HSV 平均で高速に画面種別を判定できる。
SCREEN_SIGNATURE_ROI: Box = (1286, 672, 1347, 754)   # 61x82px
# OPTION と RESULT は右下シグネチャの色相が近い（両方 H≈6 の赤系）ため、
# テンキー上の点灯位置で分離する。
SCREEN_RESULT_DOT8_ROI: Box = (1309, 674, 1324, 689)  # リザルトで「8」が点灯
SCREEN_OPTION_DOT0_ROI: Box = (1288, 736, 1303, 751)  # オプションで「0」が点灯

# 旧 OCR ベース判別用の粗い領域（フォールバック用に保持）
SCREEN_DETECT_REGIONS: dict[str, Box] = {
    "music_select_logo":         (1150, 0, 1366, 60),
    "play_top_bar":              (0, 0, 1366, 50),
    "result_score_label_block":  (450, 410, 700, 700),
    "option_select_label":       (380, 50, 980, 120),
    "let_enjoy_music_area":      (200, 200, 1100, 600),
    "preload_red":    (338, 334, 400, 424),
    "preload_orange": (435, 455, 497, 508),
}
