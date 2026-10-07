"""Nexus Shelf: Direct root module entrypoint."""

from .nexus_shelf.core import (
    GovernanceEngine,
    SkillIndexer,
    SkillShelfEngine,
    TTLCache,
)

__all__ = [
    "SkillShelfEngine",
    "SkillIndexer",
    "GovernanceEngine",
    "TTLCache",
]

if __name__ == "__main__":
    print("Nexus Shelf root module loaded.")
