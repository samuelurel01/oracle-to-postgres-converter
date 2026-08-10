from __future__ import annotations

import json
import os
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

from .models import OracleColumn
from .models import OracleTable


class ProblemLogger:
    def __init__(self, log_dir: str | None = None) -> None:
        self.log_dir = Path(log_dir or os.getenv("MIGRATION_LOG_DIR", "/app/logs"))
        self.log_file = self.log_dir / "migration-problems.log"
        self._lock = threading.Lock()
        self._initialized = False

    def log_temporal_sanitization(
        self,
        *,
        table: OracleTable,
        column: OracleColumn,
        raw_value: str,
        replacement: Any,
        reason: str,
        raw_row: tuple[Any, ...],
    ) -> None:
        self._write(
            {
                "event": "temporal_value_sanitized",
                "timestamp": datetime.now().isoformat(timespec="seconds"),
                "table": f"{table.owner}.{table.name}",
                "column": column.name,
                "oracle_type": column.data_type,
                "reason": reason,
                "raw_value": raw_value,
                "replacement": serialize_value(replacement),
                "row": {
                    table_column.name: serialize_value(value)
                    for table_column, value in zip(table.columns, raw_row, strict=True)
                },
            }
        )

    def log_nul_byte_sanitization(
        self,
        *,
        table: OracleTable,
        column: OracleColumn,
        raw_value: str,
        replacement: str,
        raw_row: tuple[Any, ...],
    ) -> None:
        self._write(
            {
                "event": "nul_byte_sanitized",
                "timestamp": datetime.now().isoformat(timespec="seconds"),
                "table": f"{table.owner}.{table.name}",
                "column": column.name,
                "oracle_type": column.data_type,
                "reason": "postgres_text_cannot_contain_nul_byte",
                "raw_value": serialize_value(raw_value),
                "replacement": serialize_value(replacement),
                "row": {
                    table_column.name: serialize_value(value)
                    for table_column, value in zip(table.columns, raw_row, strict=True)
                },
            }
        )

    def _write(self, event: dict[str, Any]) -> None:
        with self._lock:
            if not self._initialized:
                self.log_dir.mkdir(parents=True, exist_ok=True)
                self._initialized = True

            with self.log_file.open("a", encoding="utf-8") as log:
                log.write(json.dumps(event, ensure_ascii=False, default=str) + "\n")


def serialize_value(value: Any) -> Any:
    if hasattr(value, "read"):
        return value.read()
    if isinstance(value, bytes):
        return value.hex()
    if isinstance(value, datetime):
        return value.isoformat(sep=" ")
    return value
