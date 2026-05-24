"""ExportService（CSV エクスポート）のテスト。"""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

from livelyrec.application.export_service import CsvOptions, ExportService
from livelyrec.domain.score import ClearType, Judgements, Medal, Rank, Result


class FakeResultRepo:
    """list_recent が固定の行を返すフェイク。"""

    def __init__(self, rows: list[tuple]) -> None:
        self._rows = rows

    def list_recent(self, limit: int = 10000) -> list[tuple]:  # noqa: ARG002
        return self._rows


def _result(score: int = 87268) -> Result:
    return Result(
        score=score,
        judgements=Judgements(312, 18, 5, 2),
        combo=329,
        clear_type=ClearType.CLEAR,
        medal=Medal.CIRCLE,
        rank=Rank.AAA,
        best_score_diff=120,
    )


def _row(session_id: str, dt: datetime, chart_id: str = "popn-1:HYPER:0", score: int = 87268):
    return (session_id, dt, chart_id, _result(score))


def test_export_writes_header_and_rows(tmp_path: Path) -> None:
    repo = FakeResultRepo([
        _row("s1", datetime(2026, 5, 18, 14, 0), score=90000),
        _row("s2", datetime(2026, 5, 18, 15, 0), "popn-2:EX:0", score=85000),
    ])
    out = tmp_path / "out.csv"
    n = ExportService(repo).export_all(out)
    assert n == 2
    lines = out.read_text(encoding="utf-8-sig").strip().splitlines()
    assert lines[0].startswith("business_date,recorded_at")
    assert len(lines) == 3
    # difficulty 列は chart_id から抽出される
    assert ",HYPER," in lines[1]
    assert ",EX," in lines[2]


def test_export_default_encoding_has_bom(tmp_path: Path) -> None:
    out = tmp_path / "bom.csv"
    ExportService(FakeResultRepo([_row("s1", datetime(2026, 5, 1, 12, 0))])).export_all(out)
    assert out.read_bytes().startswith(b"\xef\xbb\xbf")


def test_export_without_bom_option(tmp_path: Path) -> None:
    out = tmp_path / "nobom.csv"
    ExportService(FakeResultRepo([_row("s1", datetime(2026, 5, 1, 12, 0))])).export_all(
        out, options=CsvOptions(encoding="utf-8")
    )
    assert not out.read_bytes().startswith(b"\xef\xbb\xbf")


def test_export_empty_writes_header_only(tmp_path: Path) -> None:
    out = tmp_path / "empty.csv"
    n = ExportService(FakeResultRepo([])).export_all(out)
    assert n == 0
    lines = out.read_text(encoding="utf-8-sig").strip().splitlines()
    assert len(lines) == 1


def test_export_date_range_filter(tmp_path: Path) -> None:
    repo = FakeResultRepo([
        _row("s1", datetime(2026, 5, 1, 12, 0)),
        _row("s2", datetime(2026, 5, 15, 12, 0)),
        _row("s3", datetime(2026, 5, 30, 12, 0)),
    ])
    out = tmp_path / "range.csv"
    n = ExportService(repo).export_all(
        out, date_from=date(2026, 5, 10), date_to=date(2026, 5, 20)
    )
    assert n == 1


def test_export_creates_parent_directory(tmp_path: Path) -> None:
    out = tmp_path / "nested" / "deep" / "o.csv"
    ExportService(FakeResultRepo([])).export_all(out)
    assert out.exists()


def test_export_row_values(tmp_path: Path) -> None:
    out = tmp_path / "values.csv"
    ExportService(FakeResultRepo([_row("s1", datetime(2026, 5, 18, 14, 0))])).export_all(out)
    rows = out.read_text(encoding="utf-8-sig").strip().splitlines()
    data = rows[1].split(",")
    header = rows[0].split(",")
    record = dict(zip(header, data, strict=True))
    assert record["score"] == "87268"
    assert record["cool"] == "312"
    assert record["clear_type"] == "CLEAR"
    assert record["rank"] == "AAA"
