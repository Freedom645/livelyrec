"""画面状態と状態マシン。

詳細: docs/design/06_詳細設計_アーキテクチャ.md §3.1、docs/design/10_詳細設計_画像認識.md §3.3
"""

from __future__ import annotations

from enum import Enum


class ScreenType(Enum):
    UNKNOWN = "unknown"
    TITLE = "title"
    SELECT = "select"
    READY = "ready"
    OPTION = "option"
    QUEST = "quest"
    PLAY = "play"
    PLAY_READY = "play_ready"
    RESULT = "result"
    LOAD_TO_PLAY = "load_to_play"
    LOAD_TO_READY = "load_to_ready"


class RecordingState(Enum):
    INITIAL = "initial"
    CONNECTING = "connecting"
    RECORDING_UNKNOWN = "recording_unknown"
    RECORDING = "recording"
    STOPPED = "stopped"


# (from, to) で許可される遷移の集合。
# UNKNOWN からはどの画面へも遷移可能（記録開始直後・接続復帰直後を想定）。
_ALLOWED_TRANSITIONS: set[tuple[ScreenType, ScreenType]] = {
    # SELECT
    (ScreenType.SELECT, ScreenType.READY),
    (ScreenType.SELECT, ScreenType.LOAD_TO_READY),
    # READY
    (ScreenType.READY, ScreenType.SELECT),
    (ScreenType.READY, ScreenType.OPTION),
    (ScreenType.READY, ScreenType.PLAY),
    (ScreenType.READY, ScreenType.LOAD_TO_PLAY),
    # OPTION
    (ScreenType.OPTION, ScreenType.READY),
    (ScreenType.OPTION, ScreenType.PLAY),
    (ScreenType.OPTION, ScreenType.LOAD_TO_PLAY),
    # PLAY
    (ScreenType.PLAY, ScreenType.PLAY),  # リトライの自己遷移
    (ScreenType.PLAY, ScreenType.PLAY_READY),
    (ScreenType.PLAY, ScreenType.RESULT),
    (ScreenType.PLAY, ScreenType.LOAD_TO_PLAY),
    # PLAY_READY
    (ScreenType.PLAY_READY, ScreenType.PLAY),
    # RESULT
    (ScreenType.RESULT, ScreenType.SELECT),
    (ScreenType.RESULT, ScreenType.READY),
    (ScreenType.RESULT, ScreenType.PLAY),
    (ScreenType.RESULT, ScreenType.LOAD_TO_PLAY),
    (ScreenType.RESULT, ScreenType.LOAD_TO_READY),
    # LOAD 系
    (ScreenType.LOAD_TO_PLAY, ScreenType.PLAY),
    (ScreenType.LOAD_TO_PLAY, ScreenType.PLAY_READY),
    (ScreenType.LOAD_TO_READY, ScreenType.READY),
    (ScreenType.LOAD_TO_READY, ScreenType.SELECT),
    # TITLE（タイトル画面）— 記録フロー外。選曲へ進む
    (ScreenType.TITLE, ScreenType.SELECT),
    (ScreenType.TITLE, ScreenType.LOAD_TO_READY),
    # QUEST（クエスト画面）— 記録フロー外。選曲との行き来
    (ScreenType.SELECT, ScreenType.QUEST),
    (ScreenType.QUEST, ScreenType.SELECT),
    (ScreenType.QUEST, ScreenType.LOAD_TO_READY),
}


class StateMachine:
    """画面遷移の妥当性を検証する状態マシン。

    UNKNOWN 状態からは初回確定までは任意遷移を許容する。
    確定後の不正遷移は ``CONSECUTIVE_REQUIRED_INVALID`` 連続で観測されたときのみ受容する。
    """

    CONSECUTIVE_REQUIRED_INVALID = 3

    def __init__(self) -> None:
        self._current: ScreenType = ScreenType.UNKNOWN
        self._pending_invalid: ScreenType | None = None
        self._invalid_count: int = 0

    @property
    def current(self) -> ScreenType:
        return self._current

    def reset(self) -> None:
        self._current = ScreenType.UNKNOWN
        self._pending_invalid = None
        self._invalid_count = 0

    def transition(self, to: ScreenType) -> bool:
        """to への遷移を試みる。受け入れたら True、棄却なら False。"""
        if self._is_allowed(self._current, to):
            self._current = to
            self._pending_invalid = None
            self._invalid_count = 0
            return True

        # 同じ不正遷移が連続して観測されたら強制的に受け入れる
        if to == self._pending_invalid:
            self._invalid_count += 1
            if self._invalid_count >= self.CONSECUTIVE_REQUIRED_INVALID:
                self._current = to
                self._pending_invalid = None
                self._invalid_count = 0
                return True
        else:
            self._pending_invalid = to
            self._invalid_count = 1
        return False

    def _is_allowed(self, frm: ScreenType, to: ScreenType) -> bool:
        if frm == ScreenType.UNKNOWN:
            return True
        if frm == to:
            return frm == ScreenType.PLAY  # PLAY のみ自己遷移を許容（リトライ）
        return (frm, to) in _ALLOWED_TRANSITIONS
