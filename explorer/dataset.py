"""Bounded CSV/JSON ingestion. Uploaded bytes are data, never executable code."""
import csv
import io
import json
import math
import re
from hashlib import sha256
from pathlib import PurePath

MAX_BYTES = 1_000_000
MAX_ROWS = 5_000
MAX_COLUMNS = 50
MAX_CELL_CHARS = 10_000
MAX_SAFE_INTEGER = 2**53 - 1
NUMBER = re.compile(r'-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?\Z')


class InvalidDataset(ValueError):
    pass


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise InvalidDataset(f'Повторяющаяся колонка: {key}')
        result[key] = value
    return result


def _constant(value):
    raise InvalidDataset(f'Недопустимое число: {value}')


def _invalid_text(value):
    return '\x00' in value or any(0xD800 <= ord(char) <= 0xDFFF for char in value)


def _validate_scalar(value):
    if value is None or isinstance(value, bool):
        return
    if isinstance(value, str):
        if len(value) > MAX_CELL_CHARS or _invalid_text(value):
            raise InvalidDataset('Слишком длинное значение или недопустимый символ')
        return
    if isinstance(value, int):
        if abs(value) > MAX_SAFE_INTEGER:
            raise InvalidDataset('Целое число выходит за пределы точности JavaScript')
        return
    if isinstance(value, float) and math.isfinite(value):
        return
    raise InvalidDataset('Допускаются только конечные числа и скалярные значения')


def _csv_value(value):
    if value == '':
        return None
    # Preserve text such as identifiers with leading zeroes.
    if NUMBER.fullmatch(value):
        if '.' not in value and 'e' not in value.lower():
            number = int(value)
        else:
            number = float(value)
        _validate_scalar(number)
        return number
    return value


def parse_dataset(filename: str, content: bytes) -> dict:
    if not content:
        raise InvalidDataset('Файл пуст')
    if len(content) > MAX_BYTES:
        raise InvalidDataset('Размер файла превышает 1 000 000 байт')
    try:
        text = content.decode('utf-8-sig', errors='strict')
    except UnicodeDecodeError as exc:
        raise InvalidDataset('Ожидается кодировка UTF-8') from exc
    extension = PurePath(filename).suffix.lower()
    try:
        if extension == '.csv':
            reader = csv.reader(io.StringIO(text, newline=''), strict=True)
            columns = next(reader, [])
            rows = []
            for line in reader:
                if len(line) != len(columns):
                    raise InvalidDataset(f'Число полей в строке {reader.line_num} не совпадает с заголовком')
                rows.append(dict(zip(columns, map(_csv_value, line))))
                if len(rows) > MAX_ROWS:
                    raise InvalidDataset('Допускается не более 5000 строк')
        elif extension == '.json':
            rows = json.loads(text, object_pairs_hook=_pairs, parse_constant=_constant)
            if not isinstance(rows, list) or not rows or not all(isinstance(row, dict) for row in rows):
                raise InvalidDataset('JSON должен содержать непустой массив объектов')
            columns = list(rows[0])
        else:
            raise InvalidDataset('Поддерживаются только файлы CSV и JSON')
    except InvalidDataset:
        raise
    except (csv.Error, ValueError, RecursionError, OverflowError) as exc:
        raise InvalidDataset('Некорректный формат файла') from exc
    if not columns or len(columns) > MAX_COLUMNS or any(not isinstance(c, str) or not c.strip() or c != c.strip() or len(c) > 100 or _invalid_text(c) for c in columns):
        raise InvalidDataset('Нужно от 1 до 50 непустых имён колонок без пробелов по краям (до 100 символов)')
    if len(set(columns)) != len(columns):
        raise InvalidDataset('Имена колонок не должны повторяться')
    if not rows or len(rows) > MAX_ROWS:
        raise InvalidDataset('Нужно от 1 до 5000 строк')
    for row in rows:
        if set(row) != set(columns):
            raise InvalidDataset('Все строки должны содержать одинаковые колонки')
        for value in row.values():
            _validate_scalar(value)
    metadata = []
    for name in columns:
        values = [r[name] for r in rows if r[name] is not None]
        types = {'boolean' if isinstance(v, bool) else 'number' if isinstance(v, (int, float)) else 'string' for v in values}
        kind = next(iter(types)) if len(types) == 1 else ('empty' if not types else 'mixed')
        metadata.append({'name': name, 'type': kind, 'nullable': len(values) != len(rows)})
    return {'sha256': sha256(content).hexdigest(), 'columns': metadata, 'rows': rows}
