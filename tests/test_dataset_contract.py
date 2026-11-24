import hashlib
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from explorer.analysis import calculate
from explorer.dataset import InvalidDataset, MAX_BYTES, MAX_ROWS, parse_dataset
from explorer.models import Configuration
from explorer.ui import UISchema, make_ui_schema

FIXTURES = Path(__file__).resolve().parents[1] / 'fixtures' / 'data-explorer'


@pytest.mark.parametrize('filename', ['sales.csv', 'sales.json'])
def test_dataset_hash_and_ui_schema_are_valid(filename):
    raw = (FIXTURES / filename).read_bytes()
    dataset = parse_dataset(filename, raw)
    assert dataset['sha256'] == hashlib.sha256(raw).hexdigest()
    config = Configuration()
    ui = make_ui_schema(dataset, config, calculate(dataset, config))
    validator = Draft202012Validator(UISchema.model_json_schema())
    assert not list(validator.iter_errors(ui))
    assert {node['component_type'] for node in ui['nodes']} == {'table', 'chart', 'filter', 'form', 'card', 'text'}
    ui['nodes'][0]['props']['html'] = '<script>alert(1)</script>'
    assert list(validator.iter_errors(ui))


def test_hash_depends_on_exact_uploaded_bytes():
    plain = b'number\n1\n'
    bom = b'\xef\xbb\xbf' + plain
    assert parse_dataset('a.csv', plain)['rows'] == parse_dataset('a.csv', bom)['rows']
    assert parse_dataset('a.csv', plain)['sha256'] != parse_dataset('a.csv', bom)['sha256']


def test_size_and_row_limits_at_boundary():
    assert len(parse_dataset('a.csv', b'x\n' + b'1\n' * MAX_ROWS)['rows']) == MAX_ROWS
    with pytest.raises(InvalidDataset):
        parse_dataset('a.csv', b'x\n' + b'1\n' * (MAX_ROWS + 1))
    with pytest.raises(InvalidDataset):
        parse_dataset('a.csv', b'x\n' + b'1' * MAX_BYTES)


def test_filters_and_what_if_do_not_mutate_source():
    raw = (FIXTURES / 'sales.json').read_bytes()
    dataset = parse_dataset('sales.json', raw)
    config = Configuration.model_validate({'filters': [{'column': 'category', 'operator': 'eq', 'value': 'книги'}],
        'group_by': 'category', 'what_if': {'column': 'amount', 'value': 1.1}})
    first = calculate(dataset, config)
    assert first['count'] == 2 and first['sums']['amount'] == 440
    assert calculate(dataset, config) == first
    assert dataset == parse_dataset('sales.json', raw)
