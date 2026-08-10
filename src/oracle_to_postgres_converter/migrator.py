from __future__ import annotations

from collections.abc import Callable
from collections.abc import Iterable
from dataclasses import dataclass

from .config import MigrationConfig
from .identifiers import quote_pg_identifier
from .oracle import OracleReader
from .postgres import PostgresWriter


@dataclass(frozen=True)
class MigrationProgress:
    phase: str
    message: str
    current_table: str | None = None
    current_table_index: int = 0
    total_tables: int = 0
    inserted_rows: int = 0
    total_rows: int | None = None
    percent: float = 0.0


ProgressCallback = Callable[[MigrationProgress], None]


class Migrator:
    def __init__(
        self,
        config: MigrationConfig,
        progress_callback: ProgressCallback | None = None,
    ) -> None:
        self.config = config
        self.progress_callback = progress_callback

    def migrate(self, requested_tables: Iterable[str] | None = None) -> None:
        if self.config.dry_run:
            self.print_plan(requested_tables)
            return

        with OracleReader(self.config.oracle) as oracle, PostgresWriter(
            self.config.postgres,
            preserve_identifiers=self.config.preserve_identifiers,
        ) as postgres:
            table_names = list(requested_tables or oracle.list_table_names())
            if not table_names:
                self.emit(
                    phase="completed",
                    message="No tables found to migrate.",
                    percent=100.0,
                )
                print("No tables found to migrate.")
                return

            tables = [oracle.read_table(table_name) for table_name in table_names]
            table_row_counts = [oracle.count_rows(table) for table in tables]
            total_rows = sum(table_row_counts)
            inserted_rows = 0

            self.emit(
                phase="preparing",
                message=f"Preparing {len(tables)} table(s).",
                total_tables=len(tables),
                total_rows=total_rows,
            )

            postgres.create_schema()

            for table_index, table in enumerate(tables, start=1):
                table_total_rows = table_row_counts[table_index - 1]
                print(f"Preparing {table.owner}.{table.name}")
                self.emit(
                    phase="creating_table",
                    message=f"Preparing {table.owner}.{table.name}",
                    current_table=table.name,
                    current_table_index=table_index,
                    total_tables=len(tables),
                    inserted_rows=inserted_rows,
                    total_rows=total_rows,
                    percent=self.percent(inserted_rows, total_rows),
                )

                if self.config.drop_existing:
                    postgres.drop_table(table)

                postgres.create_table_if_not_exists(table)

                if self.config.truncate:
                    postgres.truncate_table(table)

                table_inserted_rows = 0
                for rows in oracle.iter_rows(table, self.config.batch_size):
                    postgres.insert_rows(table, rows)
                    table_inserted_rows += len(rows)
                    inserted_rows += len(rows)
                    self.emit(
                        phase="copying",
                        message=(
                            f"Copying {table.name}: {table_inserted_rows}/"
                            f"{table_total_rows} rows"
                        ),
                        current_table=table.name,
                        current_table_index=table_index,
                        total_tables=len(tables),
                        inserted_rows=inserted_rows,
                        total_rows=total_rows,
                        percent=self.percent(inserted_rows, total_rows),
                    )
                    print(f"  inserted {table_inserted_rows} rows", end="\r", flush=True)

                postgres.commit()
                print(f"  inserted {table_inserted_rows} rows")

            self.emit(
                phase="completed",
                message="Migration completed.",
                total_tables=len(tables),
                inserted_rows=inserted_rows,
                total_rows=total_rows,
                percent=100.0,
            )

    def print_plan(self, requested_tables: Iterable[str] | None = None) -> None:
        with OracleReader(self.config.oracle) as oracle:
            postgres = PostgresWriter(
                self.config.postgres,
                preserve_identifiers=self.config.preserve_identifiers,
            )
            table_names = list(requested_tables or oracle.list_table_names())
            print(
                f"create schema if not exists {quote_pg_identifier(self.config.postgres.schema)};"
            )
            for table_name in table_names:
                table = oracle.read_table(table_name)
                print(postgres.build_create_table_sql(table) + ";")

    def emit(
        self,
        *,
        phase: str,
        message: str,
        current_table: str | None = None,
        current_table_index: int = 0,
        total_tables: int = 0,
        inserted_rows: int = 0,
        total_rows: int | None = None,
        percent: float | None = None,
    ) -> None:
        if self.progress_callback is None:
            return

        self.progress_callback(
            MigrationProgress(
                phase=phase,
                message=message,
                current_table=current_table,
                current_table_index=current_table_index,
                total_tables=total_tables,
                inserted_rows=inserted_rows,
                total_rows=total_rows,
                percent=self.percent(inserted_rows, total_rows) if percent is None else percent,
            )
        )

    @staticmethod
    def percent(inserted_rows: int, total_rows: int | None) -> float:
        if not total_rows:
            return 0.0
        return min(100.0, round((inserted_rows / total_rows) * 100, 2))
