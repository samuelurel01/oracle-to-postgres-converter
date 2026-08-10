from __future__ import annotations

from .models import OracleColumn


def oracle_to_postgres_type(column: OracleColumn) -> str:
    data_type = column.data_type.upper()

    if data_type in {"VARCHAR2", "NVARCHAR2", "VARCHAR"}:
        length = column.char_length or column.data_length
        return f"varchar({length})" if length else "text"

    if data_type in {"CHAR", "NCHAR"}:
        length = column.char_length or column.data_length or 1
        return f"char({length})"

    if data_type == "NUMBER":
        return map_number(column.data_precision, column.data_scale)

    if data_type in {"FLOAT", "BINARY_DOUBLE"}:
        return "double precision"

    if data_type == "BINARY_FLOAT":
        return "real"

    if data_type == "DATE":
        return "timestamp(0)"

    if data_type.startswith("TIMESTAMP") and "WITH TIME ZONE" in data_type:
        return "timestamp with time zone"

    if data_type.startswith("TIMESTAMP"):
        return "timestamp"

    if data_type in {"CLOB", "NCLOB", "LONG", "XMLTYPE"}:
        return "text"

    if data_type in {"BLOB", "RAW", "LONG RAW"}:
        return "bytea"

    if data_type == "ROWID" or data_type == "UROWID":
        return "text"

    return "text"


def map_number(precision: int | None, scale: int | None) -> str:
    if precision is None:
        return "numeric"

    normalized_scale = scale or 0
    if normalized_scale == 0:
        if precision <= 4:
            return "smallint"
        if precision <= 9:
            return "integer"
        if precision <= 18:
            return "bigint"

    return f"numeric({precision},{normalized_scale})"
