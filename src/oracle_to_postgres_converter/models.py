from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class OracleColumn:
    name: str
    data_type: str
    data_length: int | None
    data_precision: int | None
    data_scale: int | None
    char_length: int | None
    nullable: bool
    column_id: int


@dataclass(frozen=True)
class OracleTable:
    owner: str
    name: str
    columns: list[OracleColumn]
    primary_key_columns: list[str]

