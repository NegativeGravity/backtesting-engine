from typing import Annotated
from uuid import uuid4

from pydantic import StringConstraints

type Identifier = Annotated[
    str,
    StringConstraints(
        min_length=3,
        max_length=128,
        pattern=r"^[a-z0-9][a-z0-9._:-]*$",
    ),
]
type SymbolCode = Annotated[
    str,
    StringConstraints(
        min_length=1,
        max_length=32,
        pattern=r"^[A-Z0-9._-]+$",
    ),
]
type CurrencyCode = Annotated[
    str,
    StringConstraints(
        min_length=3,
        max_length=8,
        pattern=r"^[A-Z0-9]+$",
    ),
]
type SemanticVersion = Annotated[
    str,
    StringConstraints(
        min_length=5,
        max_length=32,
        pattern=(
            r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
            r"(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$"
        ),
    ),
]
type Sha256Hex = Annotated[
    str,
    StringConstraints(
        min_length=64,
        max_length=64,
        pattern=r"^[a-f0-9]{64}$",
    ),
]
type HexColor = Annotated[
    str,
    StringConstraints(pattern=r"^#[0-9A-Fa-f]{6}(?:[0-9A-Fa-f]{2})?$"),
]


def new_identifier(prefix: str) -> str:
    normalized = prefix.strip().lower().replace(" ", "_")
    return f"{normalized}_{uuid4().hex}"
