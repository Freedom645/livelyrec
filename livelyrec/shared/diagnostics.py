"""診断系（メモリ使用量の取得・定期ロギング）。

BSOD（特に MEMORY_MANAGEMENT）の手がかりを取得するため、自プロセスと
システム全体のメモリ使用量を定期的にログへ出力する。Windows API
（GetProcessMemoryInfo / GlobalMemoryStatusEx）を ctypes で直接呼び、
psutil 等の追加依存を持ち込まない。
"""

from __future__ import annotations

import ctypes
import logging
import sys
import threading
from ctypes import wintypes
from typing import TypedDict

logger = logging.getLogger("livelyrec.diag")


class MemorySnapshot(TypedDict, total=False):
    rss_mb: float
    private_mb: float
    peak_rss_mb: float
    sys_memory_load_pct: int
    sys_avail_mb: float
    sys_total_mb: float


def get_memory_snapshot() -> MemorySnapshot | None:
    """Windows のプロセスメモリ使用量とシステムメモリ状態を取得する。

    取得失敗時、または非 Windows 環境では None を返す（呼び出し側でフォールバック）。
    """
    if not sys.platform.startswith("win"):
        return None
    try:
        class _PMC_EX(ctypes.Structure):
            _fields_ = [
                ("cb", wintypes.DWORD),
                ("PageFaultCount", wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
                ("PrivateUsage", ctypes.c_size_t),
            ]

        class _MEMSTATX(ctypes.Structure):
            _fields_ = [
                ("dwLength", wintypes.DWORD),
                ("dwMemoryLoad", wintypes.DWORD),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("sullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]

        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        psapi = ctypes.WinDLL("Psapi.dll")  # type: ignore[attr-defined]

        # ハンドル型は 64bit 環境で 8 バイト。restype を指定しないと c_int に
        # 切り詰められ INVALID_HANDLE 扱いになるので、戻り値型と引数型を明示。
        kernel32.GetCurrentProcess.restype = wintypes.HANDLE
        psapi.GetProcessMemoryInfo.argtypes = [
            wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD
        ]
        psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
        kernel32.GlobalMemoryStatusEx.argtypes = [ctypes.c_void_p]
        kernel32.GlobalMemoryStatusEx.restype = wintypes.BOOL

        pmc = _PMC_EX()
        pmc.cb = ctypes.sizeof(pmc)
        if not psapi.GetProcessMemoryInfo(
            kernel32.GetCurrentProcess(), ctypes.byref(pmc), pmc.cb
        ):
            return None

        msx = _MEMSTATX()
        msx.dwLength = ctypes.sizeof(msx)
        if not kernel32.GlobalMemoryStatusEx(ctypes.byref(msx)):
            return None

        mb = 1024 * 1024
        return MemorySnapshot(
            rss_mb=round(pmc.WorkingSetSize / mb, 1),
            private_mb=round(pmc.PrivateUsage / mb, 1),
            peak_rss_mb=round(pmc.PeakWorkingSetSize / mb, 1),
            sys_memory_load_pct=int(msx.dwMemoryLoad),
            sys_avail_mb=round(msx.ullAvailPhys / mb, 1),
            sys_total_mb=round(msx.ullTotalPhys / mb, 1),
        )
    except OSError:
        return None


class MemoryMonitor:
    """別スレッドで定期的にメモリ使用量を INFO ログへ出力するモニタ。

    BSOD（MEMORY_MANAGEMENT 等）の直前のメモリ逼迫を後追いで確認するため、
    記録中常時稼働させる前提。CPU 負荷は無視できる程度（数秒に 1 回の syscall）。
    """

    def __init__(self, interval_sec: float = 60.0) -> None:
        self._interval = interval_sec
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None:
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._loop, name="memory-monitor", daemon=True
        )
        self._thread.start()

    def stop(self, timeout: float = 2.0) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)
            self._thread = None

    def _loop(self) -> None:
        # 起動直後の 1 件を残してから定期ループへ。
        self._log_once()
        while not self._stop.wait(self._interval):
            self._log_once()

    @staticmethod
    def _log_once() -> None:
        snap = get_memory_snapshot()
        if snap is None:
            return
        logger.info(
            "memory rss=%sMB private=%sMB peak=%sMB sys_load=%s%% sys_avail=%sMB/%sMB",
            snap.get("rss_mb"),
            snap.get("private_mb"),
            snap.get("peak_rss_mb"),
            snap.get("sys_memory_load_pct"),
            snap.get("sys_avail_mb"),
            snap.get("sys_total_mb"),
        )


def _idle_wait(seconds: float, stop: threading.Event) -> bool:
    """テスト用のヘルパ。本体では使用しないが、外部からも待機を組み立てやすくする。"""
    return stop.wait(seconds)


# テストから明示的に内部ループを 1 回だけ走らせるための公開ヘルパ
def log_memory_once() -> None:
    """1 回だけメモリスナップショットを INFO ログへ出力する（テスト用フック）。"""
    MemoryMonitor._log_once()
