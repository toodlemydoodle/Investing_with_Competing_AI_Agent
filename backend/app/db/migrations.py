from __future__ import annotations

from sqlalchemy import inspect
from sqlalchemy.engine import Engine


TABLE_RENAMES = {
    'strategy_sleeves': 'strategy_agents',
    'sleeve_positions': 'agent_positions',
    'sleeve_trades': 'agent_trades',
}

COLUMN_RENAMES = {
    'broker_orders': {'sleeve_slug': 'agent_slug'},
    'agent_positions': {'sleeve_slug': 'agent_slug'},
    'agent_trades': {'sleeve_slug': 'agent_slug'},
}

COLUMN_ADDITIONS = {
    'strategy_agents': {
        'competition_window_days': 'INTEGER NOT NULL DEFAULT 90',
        'rolling_gains': 'FLOAT NOT NULL DEFAULT 0',
        'rolling_losses': 'FLOAT NOT NULL DEFAULT 0',
        'rolling_unrealized': 'FLOAT NOT NULL DEFAULT 0',
        'rolling_net_pnl': 'FLOAT NOT NULL DEFAULT 0',
        'is_eligible_for_elimination': 'BOOLEAN NOT NULL DEFAULT 0',
        'elimination_ready_at': 'DATETIME',
        'last_scored_at': 'DATETIME',
    },
    'companies': {
        'approval_source': "TEXT NOT NULL DEFAULT 'baseline'",
        'approval_positive_streak': 'INTEGER NOT NULL DEFAULT 0',
        'approval_negative_streak': 'INTEGER NOT NULL DEFAULT 0',
        'last_conviction_score': 'FLOAT NOT NULL DEFAULT 0',
        'last_researched_at': 'DATETIME',
    },
}


def migrate_legacy_schema(engine: Engine) -> None:
    if engine.dialect.name != 'sqlite':
        return

    with engine.begin() as connection:
        inspector = inspect(connection)
        tables = set(inspector.get_table_names())

        for old_name, new_name in TABLE_RENAMES.items():
            if old_name in tables and new_name not in tables:
                connection.exec_driver_sql(f'ALTER TABLE "{old_name}" RENAME TO "{new_name}"')
                tables.remove(old_name)
                tables.add(new_name)

        inspector = inspect(connection)
        current_tables = set(inspector.get_table_names())
        for table_name, renames in COLUMN_RENAMES.items():
            if table_name not in current_tables:
                continue
            columns = {column['name'] for column in inspector.get_columns(table_name)}
            for old_name, new_name in renames.items():
                if old_name in columns and new_name not in columns:
                    connection.exec_driver_sql(
                        f'ALTER TABLE "{table_name}" RENAME COLUMN "{old_name}" TO "{new_name}"'
                    )
                    columns.remove(old_name)
                    columns.add(new_name)

        inspector = inspect(connection)
        current_tables = set(inspector.get_table_names())
        for table_name, additions in COLUMN_ADDITIONS.items():
            if table_name not in current_tables:
                continue
            columns = {column['name'] for column in inspector.get_columns(table_name)}
            for column_name, column_sql in additions.items():
                if column_name in columns:
                    continue
                connection.exec_driver_sql(
                    f'ALTER TABLE "{table_name}" ADD COLUMN "{column_name}" {column_sql}'
                )
                columns.add(column_name)
