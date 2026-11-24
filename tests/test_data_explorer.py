import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from explorer.app import create_app
from explorer.dataset import InvalidDataset, MAX_BYTES, parse_dataset
from explorer.models import Configuration
from explorer.storage import Conflict, ExplorerStore
from explorer.ui import UISchema

FIXTURES = Path(__file__).resolve().parents[1] / 'fixtures' / 'data-explorer'


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(tmp_path / 'explorer.db')) as test_client:
        yield test_client


@pytest.mark.parametrize('filename', ['sales.csv', 'sales.json'])
def test_upload_save_reopen_and_handoff(client, filename):
    raw = (FIXTURES / filename).read_bytes()
    created = client.post('/api/data-explorer/sessions', params={'filename': filename}, content=raw)
    assert created.status_code == 201
    initial = created.json()
    session_id = initial['state']['session_id']
    assert initial['state']['state_version'] == 1
    assert initial['state']['payload']['aggregates']['sums'] == {'amount': 600.0}
    UISchema.model_validate(initial['ui_schema'])
    configuration = {
        'filters': [{'column': 'category', 'operator': 'eq', 'value': 'книги'}],
        'group_by': 'category', 'what_if': {'column': 'amount', 'operation': 'multiply', 'value': 1.1},
    }
    updated = client.put(f'/api/data-explorer/sessions/{session_id}', json={
        'expected_version': 1, 'configuration': configuration,
        'client_aggregates': {'count': 999, 'sums': {'amount': 999}},
    })
    assert updated.status_code == 200
    current = updated.json()
    assert current['state']['state_version'] == 2
    assert current['state']['payload']['aggregates']['count'] == 2
    assert current['state']['payload']['aggregates']['sums'] == {'amount': 440.0}
    assert current['data']['rows'] == initial['data']['rows']
    assert client.get(f'/api/data-explorer/sessions/{session_id}').json() == current
    assert client.get(f'/api/data-explorer/sessions/{session_id}?version=1').json() == initial
    handoff = client.get(f'/api/data-explorer/sessions/{session_id}/handoff?version=2').json()
    assert handoff['payload'] == current['state']['payload']
    assert handoff['state_version'] == 2
    assert client.put(f'/api/data-explorer/sessions/{session_id}', json={'expected_version': 1, 'configuration': configuration}).status_code == 409
    assert client.get(f'/api/data-explorer/sessions/{session_id}?version=99').status_code == 404


@pytest.mark.parametrize(('filename', 'raw'), [
    ('a.csv', b''), ('a.csv', b'a,a\n1,2\n'), ('a.csv', b'a,\n1,2\n'),
    ('a.csv', b'a,b\n1\n'), ('a.csv', b'a,b\n1,2,3\n'),
    ('a.csv', b'a\n"unterminated'), ('a.csv', b'a\n\xff'),
    ('a.json', b'{}'), ('a.json', b'[{"a":1},{"b":2}]'),
    ('a.json', b'[{"a":1,"a":2}]'), ('a.json', b'[{"a":{"b":2}}]'),
    ('a.json', b'[{"a":NaN}]'), ('a.json', b'[{"a":"\\ud800"}]'),
    ('a.json', b'[{"a":9007199254740992}]'), ('a.txt', b'hello'),
])
def test_rejects_bad_file_without_crashing(client, filename, raw):
    response = client.post('/api/data-explorer/sessions', params={'filename': filename}, content=raw)
    assert response.status_code == 422
    assert isinstance(response.json()['detail'], str)


def test_limit_and_no_code_execution(client):
    response = client.post('/api/data-explorer/sessions?filename=x.csv', content=b'a\n' + b'a' * MAX_BYTES)
    assert response.status_code == 413
    raw = b'a\n=1+1\n'
    response = client.post('/api/data-explorer/sessions?filename=x.csv', content=raw)
    assert response.json()['data']['rows'] == [{'a': '=1+1'}]


def test_invalid_configuration_does_not_advance_state(client):
    created = client.post('/api/data-explorer/sessions?filename=sales.csv', content=(FIXTURES / 'sales.csv').read_bytes()).json()
    session_id = created['state']['session_id']
    response = client.put(f'/api/data-explorer/sessions/{session_id}', json={'expected_version': 1, 'configuration': {'what_if': {'column': 'category', 'value': 2}}})
    assert response.status_code == 422
    assert client.get(f'/api/data-explorer/sessions/{session_id}').json()['state']['state_version'] == 1


def test_original_bytes_survive_restart(tmp_path):
    path = tmp_path / 'explorer.db'
    raw = (FIXTURES / 'sales.csv').read_bytes()
    with TestClient(create_app(path)) as client:
        session_id = client.post('/api/data-explorer/sessions?filename=sales.csv', content=raw).json()['state']['session_id']
        assert client.put(f'/api/data-explorer/sessions/{session_id}', json={'expected_version': 1, 'configuration': {}}).status_code == 200
    with TestClient(create_app(path)) as client:
        assert client.get(f'/api/data-explorer/sessions/{session_id}').json()['state']['state_version'] == 2
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT original FROM explorer_sessions WHERE id=?', (session_id,)).fetchone()[0] == raw


def test_concurrent_writes_do_not_overwrite_each_other(tmp_path):
    store = ExplorerStore(tmp_path / 'explorer.db')
    raw = (FIXTURES / 'sales.csv').read_bytes()
    session_id = store.create('sales.csv', raw, parse_dataset('sales.csv', raw))['session_id']
    barrier = Barrier(2)
    def write():
        barrier.wait()
        try:
            return store.save(session_id, 1, Configuration())['state_version']
        except Conflict:
            return 'conflict'
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: write(), range(2)))
    assert sorted(map(str, results)) == ['2', 'conflict']


def test_ui_schema_rejects_unknown_components_and_props(client):
    schema = client.post('/api/data-explorer/sessions?filename=sales.json', content=(FIXTURES / 'sales.json').read_bytes()).json()['ui_schema']
    schema['nodes'][0]['props']['html'] = '<script>alert(1)</script>'
    with pytest.raises(ValidationError):
        UISchema.model_validate(schema)
    schema['nodes'][0] = {'component_type': 'script', 'props': {}}
    with pytest.raises(ValidationError):
        UISchema.model_validate(schema)
