"""Proposed renderer contract; version and props require team agreement."""
from typing import Annotated, Literal

from pydantic import Field

from explorer.models import Configuration, Filter, Scalar, StrictModel, WhatIf


class Column(StrictModel):
    name: str
    type: Literal['number', 'string', 'boolean', 'mixed', 'empty']
    nullable: bool


class TextProps(StrictModel):
    text: str


class FilterProps(StrictModel):
    columns: list[Column]
    filters: list[Filter]
    group_by: str | None


class FormProps(StrictModel):
    what_if: WhatIf | None


class CardProps(StrictModel):
    count: int
    sums: dict[str, float]


class Group(StrictModel):
    value: Scalar
    count: int
    sums: dict[str, float]


class ChartProps(StrictModel):
    groups: list[Group]


class TableProps(StrictModel):
    columns: list[Column]
    rows: list[dict[str, Scalar]]


class TextNode(StrictModel):
    component_type: Literal['text']
    props: TextProps


class FilterNode(StrictModel):
    component_type: Literal['filter']
    props: FilterProps


class FormNode(StrictModel):
    component_type: Literal['form']
    props: FormProps


class CardNode(StrictModel):
    component_type: Literal['card']
    props: CardProps


class ChartNode(StrictModel):
    component_type: Literal['chart']
    props: ChartProps


class TableNode(StrictModel):
    component_type: Literal['table']
    props: TableProps


Node = Annotated[TextNode | FilterNode | FormNode | CardNode | ChartNode | TableNode, Field(discriminator='component_type')]


class UISchema(StrictModel):
    schema_version: Literal['1.0'] = '1.0'
    app_id: Literal['data-explorer'] = 'data-explorer'
    nodes: list[Node]


def make_ui_schema(dataset: dict, config: Configuration, aggregates: dict) -> dict:
    nodes = [
        {'component_type': 'text', 'props': {'text': 'Исходные данные не изменяются'}},
        {'component_type': 'filter', 'props': {'columns': dataset['columns'], 'filters': config.filters, 'group_by': config.group_by}},
        {'component_type': 'form', 'props': {'what_if': config.what_if}},
        {'component_type': 'card', 'props': {'count': aggregates['count'], 'sums': aggregates['sums']}},
        {'component_type': 'chart', 'props': {'groups': aggregates['groups']}},
        {'component_type': 'table', 'props': {'columns': dataset['columns'], 'rows': dataset['rows']}},
    ]
    return UISchema(nodes=nodes).model_dump()
