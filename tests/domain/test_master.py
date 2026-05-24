"""マスタ正規化・難易度パースのテスト。"""

from __future__ import annotations

import pytest

from livelyrec.domain.master import normalize_song_title, parse_difficulty
from livelyrec.domain.score import Difficulty


@pytest.mark.parametrize(
    "raw, expected",
    [
        # カタカナはひらがなに統一される（jaconv 利用）
        ("ぽぽぽかレトロード", "ぽぽぽかれとろーど"),
        ("漆黒のスペシャルプリンセスサンデー", "漆黒のすぺしゃるぷりんせすさんでー"),
        ("ぽぽぽか★レトロード", "ぽぽぽかれとろーど"),
        ("ぽぽぽか レトロード", "ぽぽぽかれとろーど"),
        ("  ぽぽぽか  ", "ぽぽぽか"),
        ("HELLO!?", "hello"),
        ("", ""),
    ],
)
def test_normalize_song_title(raw: str, expected: str) -> None:
    assert normalize_song_title(raw) == expected


@pytest.mark.parametrize(
    "label, expected",
    [
        ("EX", Difficulty.EX),
        ("EXTRA", Difficulty.EX),
        ("HYP", Difficulty.HYPER),
        ("HYPER", Difficulty.HYPER),
        ("Hyper", Difficulty.HYPER),
        ("NORMAL", Difficulty.NORMAL),
        ("EASY", Difficulty.EASY),
        ("5BUTTONS", Difficulty.EASY),
        ("UPPER", Difficulty.UPPER),
        ("EX UPPER", Difficulty.UPPER),
        ("", None),
        ("???", None),
    ],
)
def test_parse_difficulty(label: str, expected: Difficulty | None) -> None:
    assert parse_difficulty(label) == expected
