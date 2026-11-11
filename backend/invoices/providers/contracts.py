from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ProviderExtractionResponse:
    """
    Preserve both the parsed provider data and its original response.
    """

    data: dict[str, Any]
    raw_response: str
    