"""Local SQLite adapter; the shared platform repository is not available yet."""
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from uuid import uuid4

from explorer.analysis import ALGORITHM_VERSION, calculate
from explorer.models import Configuration

APP_ID = 'data-explorer'
APP_VERSION = '1.0.0'
STATE_SCHEMA_VERSION = '1.0'


class NotFound(Exception):
    pass


class Conflict(Exception):
    pass


def _json(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(',', ':'))


class ExplorerStore:
    def __init__(self, path):
        self.path = str(path)
        with self.connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS explorer_sessions (
                    id TEXT PRIMARY KEY, filename TEXT NOT NULL, original BLOB NOT NULL,
                    dataset TEXT NOT NULL, current_version INTEGER NOT NULL,
                    app_version TEXT NOT NULL, state_schema_version TEXT NOT NULL,
                    algorithm_version TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS explorer_states (
                    session_id TEXT NOT NULL REFERENCES explorer_sessions(id),
                    state_version INTEGER NOT NULL, configuration TEXT NOT NULL,
                    aggregates TEXT NOT NULL, updated_at TEXT NOT NULL,
                    PRIMARY KEY (session_id, state_version)
                );
            ''')

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        try:
            db.execute('PRAGMA foreign_keys=ON')
            with db:
                yield db
        finally:
            db.close()

    @staticmethod
    def now():
        return datetime.now(timezone.utc).isoformat()

    def create(self, filename, raw, dataset):
        session_id = str(uuid4())
        config = Configuration()
        aggregates = calculate(dataset, config)
        with self.connect() as db:
            db.execute('INSERT INTO explorer_sessions VALUES (?, ?, ?, ?, 1, ?, ?, ?)',
                       (session_id, filename, raw, _json(dataset), APP_VERSION, STATE_SCHEMA_VERSION, ALGORITHM_VERSION))
            db.execute('INSERT INTO explorer_states VALUES (?, 1, ?, ?, ?)', (session_id, _json(config.model_dump()), _json(aggregates), self.now()))
        return self.get(session_id)

    def get(self, session_id, version=None):
        with self.connect() as db:
            session = db.execute('SELECT filename, dataset, current_version, app_version, state_schema_version, algorithm_version FROM explorer_sessions WHERE id=?', (session_id,)).fetchone()
            if not session:
                raise NotFound()
            filename, dataset_json, current, app_version, schema_version, algorithm_version = session
            selected = current if version is None else version
            state = db.execute('SELECT configuration, aggregates, updated_at FROM explorer_states WHERE session_id=? AND state_version=?', (session_id, selected)).fetchone()
            if not state:
                raise NotFound()
        dataset = json.loads(dataset_json)
        config_json, aggregates_json, updated_at = state
        return {'session_id': session_id, 'app_id': APP_ID, 'app_version': app_version,
                'state_schema_version': schema_version, 'state_version': selected, 'updated_at': updated_at,
                'payload': {'dataset': {'filename': filename, 'sha256': dataset['sha256'], 'algorithm_version': algorithm_version},
                            'configuration': json.loads(config_json), 'aggregates': json.loads(aggregates_json)},
                'dataset': dataset}

    def save(self, session_id, expected_version, config):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            session = db.execute('SELECT dataset, current_version, algorithm_version, state_schema_version FROM explorer_sessions WHERE id=?', (session_id,)).fetchone()
            if not session:
                raise NotFound()
            if session[1] != expected_version:
                raise Conflict()
            if session[2:] != (ALGORITHM_VERSION, STATE_SCHEMA_VERSION):
                raise Conflict()
            aggregates = calculate(json.loads(session[0]), config)
            version = expected_version + 1
            db.execute('INSERT INTO explorer_states VALUES (?, ?, ?, ?, ?)', (session_id, version, _json(config.model_dump()), _json(aggregates), self.now()))
            db.execute('UPDATE explorer_sessions SET current_version=? WHERE id=?', (version, session_id))
        return self.get(session_id, version)
