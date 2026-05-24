"""CSV エクスポート。

詳細: docs/design/08_詳細設計_API設計.md §4
"""

from __future__ import annotations

import csv
import logging
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from livelyrec.infrastructure.repository.result_repo import ResultRepository

logger = logging.getLogger("livelyrec.export")


@dataclass(frozen=True)
class CsvOptions:
    encoding: str = "utf-8-sig"   # BOM 付き UTF-8（既定）
    delimiter: str = ","
    newline: str = "\r\n"


_HEADER = [
    "business_date",
    "recorded_at",
    "genre",
    "title",
    "difficulty",
    "level",
    "score",
    "cool",
    "great",
    "good",
    "bad",
    "combo",
    "clear_type",
    "medal",
    "rank",
]


class ExportService:
    def __init__(self, result_repo: ResultRepository) -> None:
        self._results = result_repo

    def export_all(
        self,
        out_path: Path,
        options: CsvOptions | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
    ) -> int:
        """全期間（または期間指定）のリザルトを CSV 出力する。書込件数を返す。"""
        if options is None:
            options = CsvOptions()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        # 大量データに備えて全件取得は避け、list_recent を大きめに取り出す
        # 実プロダクションでは date 範囲 SQL を追加実装したいが、本実装はシンプルに
        recent = self._results.list_recent(limit=10000)
        rows = []
        for _session_id, started_at, chart_id, result in recent:
            if date_from and started_at.date() < date_from:
                continue
            if date_to and started_at.date() > date_to:
                continue
            rows.append({
                "business_date": started_at.date().isoformat(),
                "recorded_at": started_at.isoformat(),
                "genre": "",
                "title": "",
                "difficulty": chart_id.split(":")[1] if ":" in chart_id else "",
                "level": "",
                "score": result.score,
                "cool": result.judgements.cool,
                "great": result.judgements.great,
                "good": result.judgements.good,
                "bad": result.judgements.bad,
                "combo": result.combo,
                "clear_type": result.clear_type.value,
                "medal": result.medal.value,
                "rank": result.rank.value,
            })

        with out_path.open("w", encoding=options.encoding, newline="") as f:
            writer = csv.DictWriter(
                f,
                fieldnames=_HEADER,
                delimiter=options.delimiter,
                lineterminator=options.newline,
            )
            writer.writeheader()
            for row in rows:
                writer.writerow(row)
        return len(rows)
