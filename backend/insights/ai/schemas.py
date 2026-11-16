from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class SpendByArguments(BaseModel):
    """Validated arguments for the read-only expenditure report tool."""

    model_config = ConfigDict(extra="forbid")

    dimension: Literal["vendor", "account", "month"] = Field(
        description="How to group expenditure: vendor, expense account, or accounting month.",
    )
    start_date: date = Field(
        description="First accounting entry date to include, in YYYY-MM-DD format.",
    )
    end_date: date = Field(
        description="Last accounting entry date to include, in YYYY-MM-DD format.",
    )
    limit: int = Field(
        default=20,
        ge=1,
        le=100,
        description="Maximum number of groups returned per currency; defaults to 20.",
    )
    currency: str | None = Field(
        default=None,
        min_length=3,
        max_length=3,
        pattern=r"^[A-Z]{3}$",
        description="Optional three-letter currency code such as NGN or USD. Omit for all currencies.",
    )

    @field_validator("currency", mode="before")
    @classmethod
    def normalize_currency(cls, value):
        if value is None:
            return None
        if isinstance(value, str):
            return value.strip().upper()
        return value

    @model_validator(mode="after")
    def validate_date_range(self):
        if self.start_date > self.end_date:
            raise ValueError("start_date cannot be later than end_date.")
        return self
