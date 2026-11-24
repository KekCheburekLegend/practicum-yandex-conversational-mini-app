"""Exercise the real PostgreSQL adapter and API, isolated in a unique schema."""
import hashlib
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from uuid import uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg import sql

from explorer.app import create_app
from explorer.models import Configuration
from explorer.postgres_storage import PostgresExplorerStore
from explorer.storage import Conflict

FIXTURES = Path(__file__).resolve().parents[1] / 'fixtures' / 'data-explorer'


@pytest.fixture
def postgres_store():
    dsn = os.getenv('EXPLORER_TEST_POSTGRES_DSN')
    if not dsn:
        pytest.skip('Set EXPLORER_TEST_POSTGRES_DSN to run PostgreSQL integration tests')
    schema = 'test_explorer_' + uuid4().hex
    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(schema)))
    try:
        yield PostgresExplorerStore(dsn, schema=schema)
    finally:
        with psycopg.connect(dsn, autocommit=True) as conn:
            conn.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(schema)))


@pytest.mark.parametrize('filename', ['sales.csv', 'sales.json'])
def test_postgres_api_handoff_preserves_input_and_version(postgres_store, filename):
    raw = (FIXTURES / filename).read_bytes()
    with TestClient(create_app(store_factory=lambda: postgres_store)) as client:
        created = client.post('/api/data-explorer/sessions', params={'filename': filename}, content=raw)
        assert created.status_code == 201
        initial = created.json()
        state = initial['state']
        assert state['payload']['dataset']['sha256'] == hashlib.sha256(raw).hexdigest()
        url = '/api/data-explorer/sessions/' + state['session_id']
        config = {'filters': [{'column': 'category', 'operator': 'eq', 'value': 'книги'}],
                  'group_by': 'category', 'what_if': {'column': 'amount', 'value': 1.1}}
        response = client.put(url, json={'expected_version': 1, 'configuration': config})
        assert response.status_code == 200
        saved = response.json()
        assert saved['state']['state_version'] == 2
        assert saved['state']['payload']['configuration']['what_if']['value'] == 1.1
        assert saved['state']['payload']['aggregates']['sums']['amount'] == 440
        assert saved['data']['rows'] == initial['data']['rows']
        assert client.get(url + '?version=1').json() == initial
        assert client.get(url + '/handoff?version=2').json() == saved['state']
        assert client.put(url, json={'expected_version': 1, 'configuration': config}).status_code == 409
        assert client.get(url).json() == saved
    # Bypass the API only to verify that the original bytes persisted in Postgres.
    with postgres_store.connect() as conn:
        stored = conn.execute('SELECT original FROM explorer_sessions WHERE id=?', (state['session_id'],)).fetchone()[0]
    assert bytes(stored) == raw
    # A new adapter and application instance must recover the same version.
    new_store = PostgresExplorerStore(postgres_store.dsn, schema=postgres_store.schema)
    with TestClient(create_app(store_factory=lambda: new_store)) as client:
        assert client.get(url).json() == saved


def test_postgres_optimistic_lock_is_atomic(postgres_store):
    raw = (FIXTURES / 'sales.csv').read_bytes()
    with TestClient(create_app(store_factory=lambda: postgres_store)) as client:
        session_id = client.post('/api/data-explorer/sessions?filename=sales.csv', content=raw).json()['state']['session_id']
    barrier = Barrier(2)
    def write():
        barrier.wait(timeout=10)
        try:
            return postgres_store.save(session_id, 1, Configuration())['state_version']
        except Conflict:
            return 'conflict'
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: write(), range(2)))
    assert sorted(map(str, results)) == ['2', 'conflict']
    with postgres_store.connect() as conn:
        versions = conn.execute('SELECT state_version FROM explorer_states WHERE session_id=? ORDER BY state_version', (session_id,)).fetchall()
    assert versions == [(1,), (2,)]


def test_invalid_upload_and_configuration_leave_postgres_unchanged(postgres_store):
    with TestClient(create_app(store_factory=lambda: postgres_store)) as client:
        assert client.post('/api/data-explorer/sessions?filename=x.json', content=b'[{"x":{}}]').status_code == 422
        with postgres_store.connect() as conn:
            assert conn.execute('SELECT count(*) FROM explorer_sessions').fetchone()[0] == 0
        raw = (FIXTURES / 'sales.csv').read_bytes()
        session_id = client.post('/api/data-explorer/sessions?filename=sales.csv', content=raw).json()['state']['session_id']
        response = client.put('/api/data-explorer/sessions/' + session_id, json={
            'expected_version': 1, 'configuration': {'what_if': {'column': 'category', 'value': 2}},
        })
        assert response.status_code == 422
        assert client.get('/api/data-explorer/sessions/' + session_id).json()['state']['state_version'] == 1


def test_app_selects_postgres_from_environment(postgres_store, monkeypatch):
    monkeypatch.setenv('EXPLORER_DATABASE_URL', postgres_store.dsn)
    monkeypatch.setenv('EXPLORER_DATABASE_SCHEMA', postgres_store.schema)
    with TestClient(create_app()) as client:
        result = client.post('/api/data-explorer/sessions?filename=sales.csv', content=(FIXTURES / 'sales.csv').read_bytes())
        assert result.status_code == 201
        assert isinstance(client.app.state.store, PostgresExplorerStore)
    with postgres_store.connect() as conn:
        assert conn.execute('SELECT count(*) FROM explorer_sessions').fetchone()[0] == 1
