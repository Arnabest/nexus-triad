"""Nexus Triad: Unified Execution, Memory, and Skill Framework.

Zero-dependency, standalone AI agent execution and governance framework.
Organized into three standardized components with dedicated internal data subfolders:
- nexus_gate: Execution safety, AST compiler-in-loop, Git shadow plumbing.
- nexus_vault: Temporal knowledge graph and episodic memory.
- nexus_shelf: Dynamic skill indexing with BM25 and code governance.
"""

from __future__ import annotations

from .nexus_gate import (
    AnchorManager,
    AnchorState,
    AttentionLadder,
    GitSnapshotEngine,
    GroundTruthVerifier,
    NexusGate,
    PlanCompiler,
    RollbackResult,
    SafetyResult,
    SnapshotResult,
    SyntaxResult,
)
from .nexus_vault import (
    DatabaseManager,
    MemoryConsolidator,
    MemorySearcher,
    MemoryVaultEngine,
    TemporalGraphEngine,
)
from .nexus_shelf import (
    GovernanceEngine,
    SkillIndexer,
    SkillShelfEngine,
    TTLCache,
)

__version__ = "1.0.0"

__all__ = [
    # Nexus Gate
    "NexusGate",
    "GroundTruthVerifier",
    "GitSnapshotEngine",
    "PlanCompiler",
    "AnchorState",
    "AnchorManager",
    "AttentionLadder",
    "SyntaxResult",
    "SafetyResult",
    "SnapshotResult",
    "RollbackResult",
    # Nexus Vault
    "MemoryVaultEngine",
    "DatabaseManager",
    "TemporalGraphEngine",
    "MemorySearcher",
    "MemoryConsolidator",
    # Nexus Shelf
    "SkillShelfEngine",
    "SkillIndexer",
    "GovernanceEngine",
    "TTLCache",
]
