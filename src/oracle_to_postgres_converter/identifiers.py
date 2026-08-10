from __future__ import annotations


def normalize_identifier(identifier: str, preserve: bool = False) -> str:
    return identifier if preserve else identifier.lower()


def quote_pg_identifier(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def quote_oracle_identifier(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'

