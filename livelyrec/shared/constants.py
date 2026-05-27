"""アプリ全体で参照する定数。"""

from __future__ import annotations

APP_NAME = "LivelyRec"
DATA_DIR_NAME = "livelyrec_data"

DEFAULT_BUSINESS_DAY_ROLLOVER_HOUR = 6
DEFAULT_OBS_HOST = "127.0.0.1"
DEFAULT_OBS_PORT = 4455
DEFAULT_WS_HOST = "127.0.0.1"
DEFAULT_WS_PORT = 14514
# 既定 fps と上限 fps。0.5 秒間隔（2 fps）でも認識・配信支援の追従に
# 十分なため、CPU/GPU 負荷と OBS スクリーンショット I/O を抑える目的で
# 上限を 2 に設定（I-025 対応・PO 判断 2026-05-24）。
DEFAULT_FPS = 2
MAX_FPS = 2

SCREEN_BASE_WIDTH = 1366
SCREEN_BASE_HEIGHT = 768

SCHEMA_VERSION = 2
WS_SCHEMA_VERSION = "v1"

# 配信支援ブラウザソースの 4 パス（FR-STR-007）
BROWSER_SOURCE_PATHS = (
    "keycount",
    "now-playing",
    "now-playing-history",
    "recent",
)
