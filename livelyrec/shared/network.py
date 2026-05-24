"""ネットワーク補助関数。

LAN 公開時にユーザへ表示するホスト（ブラウザソース URL の host 部分）を
決定するための小さなユーティリティを提供する。
"""

from __future__ import annotations

import socket


def get_lan_ip(fallback: str = "127.0.0.1") -> str:
    """ローカル PC の LAN IP を最善努力で取得する。

    UDP ソケットで外部宛に connect すると、OS は実送信せず経路決定だけ行い、
    使われるインタフェースの IP が `getsockname` で取れる。これで取れない／
    loopback の場合は `gethostbyname(gethostname())` を試し、それでもダメな
    場合は `fallback` を返す。
    """
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            if ip and not ip.startswith("127."):
                return ip
        finally:
            s.close()
    except OSError:
        pass
    try:
        ip = socket.gethostbyname(socket.gethostname())
        if ip and not ip.startswith("127."):
            return ip
    except OSError:
        pass
    return fallback


def resolve_advertised_host(settings_host: str, lan_publish: bool) -> str:
    """設定 host と lan_publish フラグから「ユーザへ表示する」 host を返す。

    - `lan_publish=False` の場合は設定値をそのまま返す（既定 127.0.0.1）。
    - `lan_publish=True` かつ設定 host が loopback / 全インタフェース指定（空、
      0.0.0.0、127.0.0.1、localhost）の場合は LAN IP を採用する。
    - それ以外（ユーザが明示的に IP/ホスト名を指定）は設定値をそのまま返す。
    """
    if not lan_publish:
        return settings_host
    if settings_host in ("", "0.0.0.0", "127.0.0.1", "localhost"):
        return get_lan_ip(fallback=settings_host or "127.0.0.1")
    return settings_host
