from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime
import os
import re
import sys
import threading
from typing import Any

import oracledb

from .config import OracleConfig
from .identifiers import quote_oracle_identifier
from .models import OracleColumn, OracleTable
from .problem_log import ProblemLogger

_oracle_client_lock = threading.Lock()
_oracle_client_initialized = False
_TEMPORAL_VALUE_PATTERN = re.compile(
    r"^(?P<year>[+-]?\d{1,6})-(?P<month>\d{2})-(?P<day>\d{2}) "
    r"(?P<hour>\d{2}):(?P<minute>\d{2}):(?P<second>\d{2})"
    r"(?:\.(?P<fraction>\d+))?"
)
_TEMPORAL_NOT_NULL_FALLBACK = datetime(1900, 1, 1)


class OracleReader:
    def __init__(self, config: OracleConfig) -> None:
        self.config = config
        self.connection: oracledb.Connection | None = None
        self.problem_logger = ProblemLogger()

    def __enter__(self) -> "OracleReader":
        initialize_oracle_client(self.config)
        connect_kwargs: dict[str, Any] = {
            "user": self.config.user,
            "password": self.config.password,
            "dsn": self.config.dsn,
        }
        if self.config.config_dir and oracledb.is_thin_mode():
            connect_kwargs["config_dir"] = self.config.config_dir

        self.connection = oracledb.connect(**connect_kwargs)
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        if self.connection is not None:
            self.connection.close()

    def list_table_names(self) -> list[str]:
        assert self.connection is not None
        with self.connection.cursor() as cursor:
            cursor.execute(
                """
                select table_name
                  from all_tables
                 where owner = :owner
                   and nested = 'NO'
                   and temporary = 'N'
                   and secondary = 'N'
                 order by table_name
                """,
                owner=self.config.schema.upper(),
            )
            return [row[0] for row in cursor.fetchall()]

    def read_table(self, table_name: str) -> OracleTable:
        columns = self.read_columns(table_name)
        primary_key_columns = self.read_primary_key_columns(table_name)
        return OracleTable(
            owner=self.config.schema.upper(),
            name=table_name.upper(),
            columns=columns,
            primary_key_columns=primary_key_columns,
        )

    def read_columns(self, table_name: str) -> list[OracleColumn]:
        assert self.connection is not None
        with self.connection.cursor() as cursor:
            cursor.execute(
                """
                select column_name,
                       data_type,
                       data_length,
                       data_precision,
                       data_scale,
                       char_length,
                       nullable,
                       column_id
                  from all_tab_columns
                 where owner = :owner
                   and table_name = :table_name
                 order by column_id
                """,
                owner=self.config.schema.upper(),
                table_name=table_name.upper(),
            )
            rows = cursor.fetchall()

        if not rows:
            raise ValueError(f"Table not found or has no columns: {self.config.schema}.{table_name}")

        return [
            OracleColumn(
                name=row[0],
                data_type=row[1],
                data_length=row[2],
                data_precision=row[3],
                data_scale=row[4],
                char_length=row[5],
                nullable=row[6] == "Y",
                column_id=row[7],
            )
            for row in rows
        ]

    def read_primary_key_columns(self, table_name: str) -> list[str]:
        assert self.connection is not None
        with self.connection.cursor() as cursor:
            cursor.execute(
                """
                select cols.column_name
                  from all_constraints cons
                  join all_cons_columns cols
                    on cols.owner = cons.owner
                   and cols.constraint_name = cons.constraint_name
                   and cols.table_name = cons.table_name
                 where cons.owner = :owner
                   and cons.table_name = :table_name
                   and cons.constraint_type = 'P'
                 order by cols.position
                """,
                owner=self.config.schema.upper(),
                table_name=table_name.upper(),
            )
            return [row[0] for row in cursor.fetchall()]

    def count_rows(self, table: OracleTable) -> int:
        assert self.connection is not None
        owner = quote_oracle_identifier(table.owner)
        table_name = quote_oracle_identifier(table.name)

        with self.connection.cursor() as cursor:
            cursor.execute(f"select count(*) from {owner}.{table_name}")
            row = cursor.fetchone()
            return int(row[0]) if row else 0

    def iter_rows(
        self,
        table: OracleTable,
        batch_size: int,
    ) -> Iterator[list[tuple[Any, ...]]]:
        assert self.connection is not None
        owner = quote_oracle_identifier(table.owner)
        table_name = quote_oracle_identifier(table.name)
        columns = ", ".join(select_expression(column) for column in table.columns)

        with self.connection.cursor() as cursor:
            cursor.arraysize = batch_size
            cursor.execute(f"select {columns} from {owner}.{table_name}")

            while True:
                rows = cursor.fetchmany(batch_size)
                if not rows:
                    break
                yield [convert_oracle_row(table, row, self.problem_logger) for row in rows]


def convert_oracle_value(value: Any) -> Any:
    if hasattr(value, "read"):
        return value.read()
    return value


def convert_oracle_row(
    table: OracleTable,
    row: tuple[Any, ...],
    problem_logger: ProblemLogger | None = None,
) -> tuple[Any, ...]:
    return tuple(
        convert_oracle_column_value(table, column, value, row, problem_logger)
        for column, value in zip(table.columns, row, strict=True)
    )


def convert_oracle_column_value(
    table: OracleTable,
    column: OracleColumn,
    value: Any,
    raw_row: tuple[Any, ...],
    problem_logger: ProblemLogger | None = None,
) -> Any:
    value = convert_oracle_value(value)
    if value is None:
        return None

    if is_temporal_column(column):
        parsed_value, reason = parse_oracle_temporal_value(str(value), nullable=column.nullable)
        if reason and problem_logger:
            problem_logger.log_temporal_sanitization(
                table=table,
                column=column,
                raw_value=str(value),
                replacement=parsed_value,
                reason=reason,
                raw_row=raw_row,
            )
        return parsed_value

    if is_textual_column(column) and isinstance(value, str) and "\x00" in value:
        sanitized_value = value.replace("\x00", "")
        if problem_logger:
            problem_logger.log_nul_byte_sanitization(
                table=table,
                column=column,
                raw_value=value,
                replacement=sanitized_value,
                raw_row=raw_row,
            )
        return sanitized_value

    return value


def parse_oracle_temporal_value(value: str, *, nullable: bool) -> tuple[datetime | None, str | None]:
    match = _TEMPORAL_VALUE_PATTERN.match(value.strip())
    if not match:
        return temporal_fallback(nullable), "invalid_temporal_format"

    year = int(match.group("year"))
    if year < 1 or year > 9999:
        return temporal_fallback(nullable), "year_out_of_range"

    fraction = match.group("fraction") or ""
    microsecond = int((fraction[:6]).ljust(6, "0")) if fraction else 0

    try:
        return (
            datetime(
                year=year,
                month=int(match.group("month")),
                day=int(match.group("day")),
                hour=int(match.group("hour")),
                minute=int(match.group("minute")),
                second=int(match.group("second")),
                microsecond=microsecond,
            ),
            None,
        )
    except ValueError:
        return temporal_fallback(nullable), "invalid_temporal_value"


def temporal_fallback(nullable: bool) -> datetime | None:
    return None if nullable else _TEMPORAL_NOT_NULL_FALLBACK


def select_expression(column: OracleColumn) -> str:
    column_name = quote_oracle_identifier(column.name)
    data_type = column.data_type.upper()

    if data_type == "DATE":
        return f"to_char({column_name}, 'SYYYY-MM-DD HH24:MI:SS')"

    if data_type.startswith("TIMESTAMP") and "WITH TIME ZONE" in data_type:
        return f"to_char({column_name}, 'SYYYY-MM-DD HH24:MI:SS.FF9 TZH:TZM')"

    if data_type.startswith("TIMESTAMP"):
        return f"to_char({column_name}, 'SYYYY-MM-DD HH24:MI:SS.FF9')"

    return column_name


def is_temporal_column(column: OracleColumn) -> bool:
    data_type = column.data_type.upper()
    return data_type == "DATE" or data_type.startswith("TIMESTAMP")


def is_textual_column(column: OracleColumn) -> bool:
    data_type = column.data_type.upper()
    return data_type in {
        "CHAR",
        "CLOB",
        "LONG",
        "NCHAR",
        "NCLOB",
        "NVARCHAR2",
        "ROWID",
        "UROWID",
        "VARCHAR",
        "VARCHAR2",
        "XMLTYPE",
    }


def initialize_oracle_client(config: OracleConfig) -> None:
    global _oracle_client_initialized

    if not config.thick_mode:
        return

    with _oracle_client_lock:
        if _oracle_client_initialized or not oracledb.is_thin_mode():
            _oracle_client_initialized = True
            return

        init_kwargs: dict[str, Any] = {}
        client_dir = os.getenv("ORACLE_CLIENT_DIR")
        if client_dir and not sys.platform.startswith("linux"):
            init_kwargs["lib_dir"] = client_dir
        if config.config_dir:
            init_kwargs["config_dir"] = config.config_dir

        oracledb.init_oracle_client(**init_kwargs)
        _oracle_client_initialized = True
