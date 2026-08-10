from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class OracleConfig:
    user: str
    password: str
    dsn: str
    schema: str
    config_dir: str | None = None
    thick_mode: bool = True


@dataclass(frozen=True)
class PostgresConfig:
    dsn: str
    schema: str = "public"


@dataclass(frozen=True)
class MigrationConfig:
    oracle: OracleConfig
    postgres: PostgresConfig
    batch_size: int = 1000
    drop_existing: bool = False
    truncate: bool = False
    dry_run: bool = False
    preserve_identifiers: bool = False


def value_or_env(value: str | None, env_name: str) -> str:
    resolved = value or os.getenv(env_name)
    if not resolved:
        raise ValueError(f"Missing required value: provide --{env_name.lower().replace('_', '-')} or {env_name}")
    return resolved
