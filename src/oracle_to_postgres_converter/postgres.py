from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import psycopg
from psycopg import sql

from .config import PostgresConfig
from .identifiers import normalize_identifier, quote_pg_identifier
from .models import OracleTable
from .type_mapping import oracle_to_postgres_type


class PostgresWriter:
    def __init__(self, config: PostgresConfig, preserve_identifiers: bool = False) -> None:
        self.config = config
        self.preserve_identifiers = preserve_identifiers
        self.connection: psycopg.Connection[Any] | None = None

    def __enter__(self) -> "PostgresWriter":
        self.connection = psycopg.connect(self.config.dsn)
        self.connection.autocommit = False
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        if self.connection is not None:
            if exc_type is None:
                self.connection.commit()
            else:
                self.connection.rollback()
            self.connection.close()

    def create_schema(self) -> None:
        assert self.connection is not None
        with self.connection.cursor() as cursor:
            cursor.execute(
                sql.SQL("create schema if not exists {}").format(
                    sql.Identifier(self.config.schema),
                )
            )

    def drop_table(self, table: OracleTable) -> None:
        assert self.connection is not None
        table_name = self.pg_table_name(table.name)
        with self.connection.cursor() as cursor:
            cursor.execute(
                sql.SQL("drop table if exists {}.{} cascade").format(
                    sql.Identifier(self.config.schema),
                    sql.Identifier(table_name),
                )
            )

    def truncate_table(self, table: OracleTable) -> None:
        assert self.connection is not None
        table_name = self.pg_table_name(table.name)
        with self.connection.cursor() as cursor:
            cursor.execute(
                sql.SQL("truncate table {}.{}").format(
                    sql.Identifier(self.config.schema),
                    sql.Identifier(table_name),
                )
            )

    def create_table_if_not_exists(self, table: OracleTable) -> str:
        assert self.connection is not None
        ddl = self.build_create_table_sql(table)
        with self.connection.cursor() as cursor:
            cursor.execute(ddl)
        return ddl

    def build_create_table_sql(self, table: OracleTable) -> str:
        table_name = self.pg_table_name(table.name)
        column_definitions = []

        for column in table.columns:
            column_name = self.pg_column_name(column.name)
            nullable = "" if column.nullable else " not null"
            column_definitions.append(
                f"{quote_pg_identifier(column_name)} {oracle_to_postgres_type(column)}{nullable}"
            )

        primary_key_columns = [
            self.pg_column_name(column)
            for column in table.primary_key_columns
            if column in {oracle_column.name for oracle_column in table.columns}
        ]
        if primary_key_columns:
            pk_columns = ", ".join(quote_pg_identifier(column) for column in primary_key_columns)
            column_definitions.append(f"primary key ({pk_columns})")

        columns_sql = ",\n    ".join(column_definitions)
        return (
            f"create table if not exists {quote_pg_identifier(self.config.schema)}."
            f"{quote_pg_identifier(table_name)} (\n    {columns_sql}\n)"
        )

    def insert_rows(self, table: OracleTable, rows: Sequence[tuple[Any, ...]]) -> None:
        if not rows:
            return

        assert self.connection is not None
        table_name = self.pg_table_name(table.name)
        column_names = [self.pg_column_name(column.name) for column in table.columns]
        placeholders = sql.SQL(", ").join(sql.Placeholder() for _ in column_names)

        statement = sql.SQL("insert into {}.{} ({}) values ({})").format(
            sql.Identifier(self.config.schema),
            sql.Identifier(table_name),
            sql.SQL(", ").join(sql.Identifier(column) for column in column_names),
            placeholders,
        )

        with self.connection.cursor() as cursor:
            cursor.executemany(statement, rows)

    def commit(self) -> None:
        assert self.connection is not None
        self.connection.commit()

    def pg_table_name(self, oracle_table_name: str) -> str:
        return normalize_identifier(oracle_table_name, self.preserve_identifiers)

    def pg_column_name(self, oracle_column_name: str) -> str:
        return normalize_identifier(oracle_column_name, self.preserve_identifiers)

