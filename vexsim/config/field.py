"""Field definition schema."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

PositiveFloat = Annotated[float, Field(gt=0, allow_inf_nan=False)]


class FieldConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    version: Literal[1] = 1
    name: str = "V5RC field (empty)"
    # Inside-wall dimensions. 144 in is the nominal 6x6 tile grid; real fields
    # measure slightly less between the walls, so measure yours for wall resets.
    size_in: tuple[PositiveFloat, PositiveFloat] = (144.0, 144.0)
