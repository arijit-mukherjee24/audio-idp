"""Storage contracts shared by services, workflow and UI."""
from typing import Any, Literal, TypedDict

EntityKind = Literal['batch','recording','transcript','class','field','classification','extraction']

class Entity(TypedDict):
    id: str
    kind: EntityKind
    parent: str | None
    batch: str | None
    data: dict[str, Any]
    revision: int
    updated: float


class Job(TypedDict):
    id: str
    kind: str
    target: str
    batch: str
    status: Literal['queued','running','completed','failed','cancelled','interrupted','superseded']
    error: str
    cache_hit: int
    request_hash: str | None
    created: float
    updated: float
