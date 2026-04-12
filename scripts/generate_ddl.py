"""
DDL Generator — Exports SQLAlchemy models and RLS policies to raw SQL.

Usage:
    python scripts/generate_ddl.py > sql/schema.sql
"""
from __future__ import annotations

import os
import sys

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from sqlalchemy.schema import CreateTable
from sqlalchemy import create_mock_engine

from centrag.models import Base, RLS_SETUP_SQL


def generate():
    from sqlalchemy.schema import CreateTable
    from sqlalchemy import create_mock_engine
    
    def dump(sql, *multiparams, **params):
        print(sql.compile(dialect=engine.dialect))
        print(";")

    engine = create_mock_engine("postgresql://psycopg2", dump)

    print("-- CentRAG Production Schema DDL --")
    print("-- Generated automatically from centrag.models --")
    print("\n-- 1. EXTENSIONS --")
    print('CREATE EXTENSION IF NOT EXISTS "uuid-ossp";')
    
    print("\n-- 2. TABLES --")
    for table in Base.metadata.sorted_tables:
        print(f"\n-- Table: {table.name}")
        engine.connect().execute(CreateTable(table))

    print("\n-- 3. ROW LEVEL SECURITY POLICIES --")
    print(RLS_SETUP_SQL)


if __name__ == "__main__":
    generate()
