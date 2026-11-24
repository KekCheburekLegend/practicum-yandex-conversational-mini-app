from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictFloat, StrictInt, StrictStr


Scalar = StrictStr | StrictInt | StrictFloat | StrictBool | None


class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)


class Filter(StrictModel):
    column: str = Field(min_length=1, max_length=100)
    operator: Literal['eq', 'contains', 'gte', 'lte']
    value: Scalar


class WhatIf(StrictModel):
    column: str = Field(min_length=1, max_length=100)
    operation: Literal['multiply'] = 'multiply'
    value: float = Field(ge=-1000, le=1000, strict=True)


class Configuration(StrictModel):
    filters: list[Filter] = Field(default_factory=list, max_length=20)
    group_by: str | None = Field(default=None, max_length=100)
    what_if: WhatIf | None = None


class SaveState(StrictModel):
    expected_version: int = Field(ge=1, strict=True)
    configuration: Configuration
    # An optional client-side result may be supplied, but the saved result is
    # always recalculated from the immutable dataset and configuration.
    client_aggregates: dict[str, Any] | None = None
