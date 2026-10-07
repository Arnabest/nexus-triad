"""Nexus Vault: Direct root module entrypoint."""

from .nexus_vault.core import (
    DatabaseManager,
    MemoryConsolidator,
    MemorySearcher,
    MemoryVaultEngine,
    TemporalGraphEngine,
)

__all__ = [
    "MemoryVaultEngine",
    "DatabaseManager",
    "TemporalGraphEngine",
    "MemorySearcher",
    "MemoryConsolidator",
]

if __name__ == "__main__":
    print("Nexus Vault root module loaded.")
