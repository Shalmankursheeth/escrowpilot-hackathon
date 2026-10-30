"""Tiny schema upgrade for the demo: add any column the models have but the database lacks.
Lets you keep your local data when the app gains a field. Production should use real migrations (Alembic)."""
import logging

from sqlalchemy import Boolean, Integer, inspect, text

from .db import Base

log = logging.getLogger("escrowpilot.migrate")


def ensure_columns(engine) -> list[str]:
    added = []
    insp = inspect(engine)
    for table in Base.metadata.sorted_tables:
        if not insp.has_table(table.name):
            continue
        have = {c["name"] for c in insp.get_columns(table.name)}
        for col in table.columns:
            if col.name in have:
                continue
            ddl = f'ALTER TABLE {table.name} ADD COLUMN {col.name} {col.type.compile(engine.dialect)}'
            default = col.default.arg if col.default is not None and not callable(col.default.arg) else None
            if default is not None:
                if isinstance(col.type, Boolean):
                    default = "1" if default else "0"
                elif isinstance(col.type, Integer):
                    default = str(int(default))
                else:
                    default = "'" + str(default).replace("'", "''") + "'"
                ddl += f" DEFAULT {default}"
            with engine.begin() as conn:
                conn.execute(text(ddl))
            added.append(f"{table.name}.{col.name}")
            log.info("added column %s.%s", table.name, col.name)
    return added
