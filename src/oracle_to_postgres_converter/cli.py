from __future__ import annotations

import argparse
import sys

from .config import MigrationConfig, OracleConfig, PostgresConfig, value_or_env
from .migrator import Migrator


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="oracle-to-postgres",
        description="Convert Oracle tables to PostgreSQL using SELECT/INSERT batches.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    migrate = subparsers.add_parser("migrate", help="Migrate Oracle tables to PostgreSQL.")
    migrate.add_argument("--oracle-user")
    migrate.add_argument("--oracle-password")
    migrate.add_argument("--oracle-dsn")
    migrate.add_argument("--oracle-schema")
    migrate.add_argument("--oracle-config-dir")
    migrate.add_argument("--postgres-dsn")
    migrate.add_argument("--postgres-schema", default=None)
    migrate.add_argument("--tables", help="Comma-separated table names. Defaults to all tables.")
    migrate.add_argument("--batch-size", type=int, default=1000)
    migrate.add_argument("--drop-existing", action="store_true")
    migrate.add_argument("--truncate", action="store_true")
    migrate.add_argument("--dry-run", action="store_true")
    migrate.add_argument("--preserve-identifiers", action="store_true")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "migrate":
        try:
            config = MigrationConfig(
                oracle=OracleConfig(
                    user=value_or_env(args.oracle_user, "ORACLE_USER"),
                    password=value_or_env(args.oracle_password, "ORACLE_PASSWORD"),
                    dsn=value_or_env(args.oracle_dsn, "ORACLE_DSN"),
                    schema=value_or_env(args.oracle_schema, "ORACLE_SCHEMA"),
                    config_dir=args.oracle_config_dir,
                ),
                postgres=PostgresConfig(
                    dsn=value_or_env(args.postgres_dsn, "POSTGRES_DSN"),
                    schema=args.postgres_schema or "public",
                ),
                batch_size=args.batch_size,
                drop_existing=args.drop_existing,
                truncate=args.truncate,
                dry_run=args.dry_run,
                preserve_identifiers=args.preserve_identifiers,
            )
        except ValueError as error:
            parser.error(str(error))

        tables = parse_tables(args.tables)
        Migrator(config).migrate(tables)
        return 0

    parser.print_help()
    return 1


def parse_tables(raw_tables: str | None) -> list[str] | None:
    if not raw_tables:
        return None
    return [table.strip() for table in raw_tables.split(",") if table.strip()]


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
