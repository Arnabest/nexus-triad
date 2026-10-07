"""Nexus Gate: Direct root module entrypoint."""

from .nexus_gate.core import (
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

__all__ = [
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
]

if __name__ == "__main__":
    from .nexus_gate.core import main
    # Direct CLI invocation support if needed
    print("Nexus Gate root module loaded.")
