"""FilenameSanitizer のテスト（FR-REC-047 / §9.9）。"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from livelyrec.infrastructure.filename_sanitizer import FilenameSanitizer


def test_sanitize_strips_forbidden_characters() -> None:
    s = FilenameSanitizer()
    assert s.sanitize_title("song:title?with*bad/chars") == "songtitlewithbadchars"


def test_sanitize_strips_control_characters() -> None:
    s = FilenameSanitizer()
    assert s.sanitize_title("a\x00b\x1fc") == "abc"


def test_sanitize_strips_trailing_dot_and_space() -> None:
    s = FilenameSanitizer()
    assert s.sanitize_title("  hello.. ") == "hello"


def test_sanitize_empty_returns_unknown() -> None:
    s = FilenameSanitizer()
    assert s.sanitize_title(None) == "unknown"
    assert s.sanitize_title("") == "unknown"
    assert s.sanitize_title("???") == "unknown"
    # サニタイズ後に空白とドットだけが残るケース
    assert s.sanitize_title("  .  ") == "unknown"


def test_sanitize_keeps_multibyte() -> None:
    s = FilenameSanitizer()
    assert s.sanitize_title("ぽぽぽかレトロード") == "ぽぽぽかレトロード"


def test_sanitize_truncates_at_utf8_boundary() -> None:
    s = FilenameSanitizer()
    # 3byte 文字「あ」を多数並べる
    raw = "あ" * 50  # 150 byte
    sanitized = s.sanitize_title(raw)
    assert len(sanitized.encode("utf-8")) <= FilenameSanitizer.MAX_BYTES
    # マルチバイト境界を壊さないこと（デコードできる）
    sanitized.encode("utf-8").decode("utf-8")


def test_compose_result_filename() -> None:
    s = FilenameSanitizer()
    ts = datetime(2026, 5, 28, 19, 30, 45)
    name = s.compose_result_filename(ts, "ぽぽぽかレトロード", 87268)
    assert name == "2026-05-28_19-30-45_ぽぽぽかレトロード_87268.png"


def test_compose_result_filename_unknown_when_no_title_and_no_score() -> None:
    s = FilenameSanitizer()
    ts = datetime(2026, 5, 28, 19, 30, 45)
    name = s.compose_result_filename(ts, None, None)
    assert name == "2026-05-28_19-30-45_unknown_unknown.png"


def test_compose_banner_filename() -> None:
    s = FilenameSanitizer()
    ts = datetime(2026, 5, 28, 19, 30, 45)
    name = s.compose_banner_filename(ts, "ぽぽぽかレトロード")
    assert name == "2026-05-28_19-30-45_ぽぽぽかレトロード_banner.png"


def test_resolve_unique_no_collision(tmp_path: Path) -> None:
    s = FilenameSanitizer()
    p = tmp_path / "a.png"
    assert s.resolve_unique(p) == p


def test_resolve_unique_with_collisions(tmp_path: Path) -> None:
    s = FilenameSanitizer()
    p = tmp_path / "a.png"
    p.write_bytes(b"")
    (tmp_path / "a_2.png").write_bytes(b"")
    resolved = s.resolve_unique(p)
    assert resolved == tmp_path / "a_3.png"
