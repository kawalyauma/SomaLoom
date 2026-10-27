"""Minimal schema type; Agent 4 owns vector queries and value serialization."""

from sqlalchemy.dialects.postgresql.base import ischema_names
from sqlalchemy.types import UserDefinedType


class Vector(UserDefinedType):
    cache_ok = True

    def __init__(self, dimensions=1536):
        self.dimensions = int(dimensions)

    def get_col_spec(self, **kwargs):
        return f"vector({self.dimensions})"


ischema_names["vector"] = Vector
