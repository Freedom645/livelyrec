"""画面認識パイプライン。

詳細: docs/design/10_詳細設計_画像認識.md
"""

from .normalize import NormalizedFrame, normalize_frame
from .pipeline import PlayMetrics, RecognitionPipeline, ResultMetrics
from .roi_defs import PLAY_ROI, RESULT_ROI, SCREEN_DETECT_REGIONS

__all__ = [
    "normalize_frame",
    "NormalizedFrame",
    "PLAY_ROI",
    "RESULT_ROI",
    "SCREEN_DETECT_REGIONS",
    "RecognitionPipeline",
    "PlayMetrics",
    "ResultMetrics",
]
