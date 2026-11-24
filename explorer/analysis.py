"""Reference calculation for a reproducible handoff; browser stays interactive."""
import math
from collections import OrderedDict

from explorer.models import Configuration

ALGORITHM_VERSION = '1.0.0'


class InvalidConfiguration(ValueError):
    pass


def _is_number(value):
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def calculate(dataset: dict, config: Configuration) -> dict:
    columns = {c['name']: c['type'] for c in dataset['columns']}
    if config.group_by is not None and config.group_by not in columns:
        raise InvalidConfiguration('Неизвестная колонка группировки')
    if config.what_if and columns.get(config.what_if.column) != 'number':
        raise InvalidConfiguration('What-if требует числовую колонку')
    for f in config.filters:
        if f.column not in columns:
            raise InvalidConfiguration('Неизвестная колонка фильтра')
        if f.operator in ('gte', 'lte') and (columns[f.column] != 'number' or not _is_number(f.value)):
            raise InvalidConfiguration('Числовой фильтр требует числовую колонку и значение')
        if f.operator == 'contains' and (columns[f.column] != 'string' or not isinstance(f.value, str)):
            raise InvalidConfiguration('Фильтр contains требует строковую колонку и значение')

    def matches(row, f):
        value = row[f.column]
        if f.operator == 'eq':
            return type(value) is type(f.value) and value == f.value or (_is_number(value) and _is_number(f.value) and value == f.value)
        if f.operator == 'contains':
            return isinstance(value, str) and f.value.casefold() in value.casefold()
        if not _is_number(value):
            return False
        return value >= f.value if f.operator == 'gte' else value <= f.value

    rows = [dict(row) for row in dataset['rows'] if all(matches(row, f) for f in config.filters)]
    if config.what_if:
        for row in rows:
            value = row[config.what_if.column]
            if value is not None:
                row[config.what_if.column] = value * config.what_if.value
                if not math.isfinite(row[config.what_if.column]):
                    raise InvalidConfiguration('Результат what-if слишком велик')
    numeric = [name for name, kind in columns.items() if kind == 'number']

    def stats(items):
        sums = {}
        for name in numeric:
            try:
                total = math.fsum(r[name] for r in items if _is_number(r[name]))
            except OverflowError as exc:
                raise InvalidConfiguration('Сумма слишком велика') from exc
            if not math.isfinite(total):
                raise InvalidConfiguration('Сумма слишком велика')
            sums[name] = round(total, 6)
        return {'count': len(items), 'sums': sums}

    groups = []
    if config.group_by:
        buckets = OrderedDict()
        for row in rows:
            value = row[config.group_by]
            # Different JSON scalar types stay distinct (e.g. true and 1).
            key = (type(value).__name__, value)
            buckets.setdefault(key, []).append(row)
        groups = [{'value': items[0][config.group_by], **stats(items)} for items in buckets.values()]
    return {**stats(rows), 'groups': groups}
