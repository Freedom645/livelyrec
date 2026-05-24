"""LivelyRec 全例外の階層定義。

詳細: docs/design/06_詳細設計_アーキテクチャ.md §5.1
"""

from __future__ import annotations


class LivelyRecError(Exception):
    """LivelyRec 全例外の基底。"""


# --- 接続系（回復可能） ---

class ObsConnectionError(LivelyRecError):
    """OBS WebSocket 接続関連の問題。"""


class ObsAuthError(ObsConnectionError):
    """OBS WebSocket 認証失敗。"""


class ObsTimeoutError(ObsConnectionError):
    """OBS WebSocket タイムアウト。"""


# --- OBS 設定・リクエスト系（接続エラーではない＝再接続では解決しない） ---

class ObsConfigurationError(LivelyRecError):
    """OBS 関連の設定不備（ソース名未設定など）。再接続では解決しない。"""


class ObsRequestError(LivelyRecError):
    """OBS へのリクエストが失敗（存在しないソース指定など）。再接続では解決しない。"""


# --- 認識系（フレーム単位で回復可能） ---

class RecognitionError(LivelyRecError):
    """画像認識中の一般的エラー。"""


class OcrEngineError(RecognitionError):
    """OCR エンジン側の問題。"""


# --- 永続化系（重大） ---

class RepositoryError(LivelyRecError):
    """永続化層のエラー。"""


class DatabaseCorruptionError(RepositoryError):
    """DB ファイル破損。"""


# --- マスタ系 ---

class MasterFetchError(LivelyRecError):
    """マスタ取得失敗。"""


class MasterParseError(LivelyRecError):
    """マスタ JSON のパース失敗。"""


# --- 設定系 ---

class ConfigError(LivelyRecError):
    """設定ファイル関連エラー。"""


class DataFolderNotWritableError(ConfigError):
    """データフォルダに書き込めない（ポータブル運用前提のため致命）。"""


# --- アップデート系 ---

class UpdateCheckError(LivelyRecError):
    """アップデートチェック失敗（通常は無視）。"""
