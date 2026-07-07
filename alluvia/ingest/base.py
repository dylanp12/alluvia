from __future__ import annotations
from typing import Iterator, Protocol
from alluvia.models import RawSession


class Adapter(Protocol):
    def read(self) -> Iterator[RawSession]: ...
