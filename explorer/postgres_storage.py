"""Data Explorer PostgreSQL adapter pending the shared platform repository/migrations."""
import re
from contextlib import contextmanager

import psycopg

from explorer.storage import ExplorerStore


class _PostgresConnection:
    """Support the parameterised SQL shared with the SQLite adapter."""
    def __init__(self, conn):
        self.conn = conn

    def execute(self, sql, args=()):
        return self.conn.execute(sql.replace('?', '%s'), args)


class PostgresExplorerStore(ExplorerStore):
    def __init__(self, dsn, *, schema='public'):
        # A restricted identifier prevents options/SQL injection in search_path.
        if not re.fullmatch(r'[a-z_][a-z0-9_]{0,62}', schema):
            raise ValueError('Invalid PostgreSQL schema name')
        self.dsn = dsn
        self.schema = schema
        with self.connect() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS explorer_sessions (
                id TEXT PRIMARY KEY, filename TEXT NOT NULL, original BYTEA NOT NULL,
                dataset TEXT NOT NULL, current_version INTEGER NOT NULL,
                app_version TEXT NOT NULL, state_schema_version TEXT NOT NULL,
                algorithm_version TEXT NOT NULL
            )''')
            db.execute('''CREATE TABLE IF NOT EXISTS explorer_states (
                session_id TEXT NOT NULL REFERENCES explorer_sessions(id),
                state_version INTEGER NOT NULL, configuration TEXT NOT NULL,
                aggregates TEXT NOT NULL, updated_at TEXT NOT NULL,
                PRIMARY KEY (session_id, state_version)
            )''')

    @contextmanager
    def connect(self):
        with psycopg.connect(self.dsn, options=f'-csearch_path={self.schema}') as conn:
            yield _PostgresConnection(conn)

    def lock_session(self, db, session_id):
        return db.execute('SELECT dataset, current_version, algorithm_version, state_schema_version FROM explorer_sessions WHERE id=? FOR UPDATE', (session_id,)).fetchone()
