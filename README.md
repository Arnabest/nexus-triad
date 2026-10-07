# Nexus Triad: Unified Execution, Memory, and Skill Framework

> Zero-dependency, out-of-the-box physical execution gate, temporal episodic memory, and dynamic skill indexing framework for AI agents.

---

## 1. Standardized Component Architecture & Directory Layout

All components follow the standardized `nexus_***` naming convention. Runtime persistence files (databases, states, caches, logs) are strictly isolated and stored inside each component's internal `data/` subfolder:

```text
nexus_triad_standalone/
  ├── __init__.py                # Top-level unified exports
  ├── pyproject.toml             # Standard pip package distribution metadata
  ├── README.md                  # Comprehensive onboarding and specification guide
  ├── .gitignore                 # Runtime and cache exclusion rules
  │
  ├── nexus_gate/                # Component 1: Physical Execution Gate & Reversibility
  │   ├── __init__.py
  │   ├── core.py                # AST check, Git shadow snapshot, Attention ladder
  │   └── data/                  # Runtime files: anchor_state.json, snapshots
  │
  ├── nexus_vault/               # Component 2: Temporal Knowledge Graph & Memory Vault
  │   ├── __init__.py
  │   ├── core.py                # SQLite WAL, FTS5 Trigram, Temporal graph edges
  │   └── data/                  # Runtime files: vault.db, WAL, SHM
  │
  ├── nexus_shelf/               # Component 3: Dynamic Skill Indexer & Governance
  │   ├── __init__.py
  │   ├── core.py                # Bilingual BM25 scoring, Cliff truncation defense
  │   └── data/                  # Runtime files: index_cache.json, reports
  │
  ├── nexus_gate.py              # Root module entrypoint shim
  ├── nexus_vault.py             # Root module entrypoint shim
  ├── nexus_shelf.py             # Root module entrypoint shim
  │
  └── tests/
      └── test_standalone.py     # End-to-end integration test suite
```

---

## 2. Quick Start (Plug-and-Play / 即拆即用)

The framework has **zero external dependencies** and runs on any standard Python 3.10+ environment.

### 2.1 Direct Module Import
Import from either the root package or the component modules:

```python
# Mode A: Package import
from nexus_triad_standalone import NexusGate, MemoryVaultEngine, SkillShelfEngine

# Mode B: Direct component imports
from nexus_gate import NexusGate
from nexus_vault import MemoryVaultEngine
from nexus_shelf import SkillShelfEngine

# 1. Initialize Nexus Execution Gate (persists to nexus_gate/data/)
gate = NexusGate(workspace_root=".")

# 2. Initialize Memory Vault (persists database to nexus_vault/data/vault.db)
vault = MemoryVaultEngine()

# 3. Initialize Skill Shelf (persists index cache to nexus_shelf/data/)
shelf = SkillShelfEngine(skill_roots=["skills"], allowed_workspaces=["."])
```

### 2.2 Progressive Disclosure Retrieval Protocol (渐进披露机制)

Both `nexus_shelf` and `nexus_vault` enforce a 3-tier progressive disclosure protocol to minimize token consumption and avoid context window pollution:

```python
# =========================================================================
# L0: Lightweight Catalog Listing (< 50 tokens)
# =========================================================================
skill_catalog = shelf.list_catalog()                     # Summary of skills: name, category, description
vault_catalog = vault.list_nodes(track="errors")         # Node titles, IDs, tags, version (zero body text)

# =========================================================================
# L1: Focused Search Snippets (100 - 300 tokens)
# =========================================================================
# Shelf: BM25 score with keyword-centered match_snippet window
shelf_hits = shelf.search(query="800 lines modularizer")
# Returns: [{"name": "...", "score": 1.45, "match_snippet": "...exceeding 800 lines. Modularize..."}]

# Vault Standalone: Pure knowledge base items, zero graph overhead
vault_hits_std = vault.search(query="deadlock", track="errors", include_graph=False)
# Returns: [{"node_id": "err_1", "title": "...", "snippet": "...pipe buffer blocks..."}]

# Vault Graph-Paired: Paired with multi-hop graph context and text injection
vault_hits_paired = vault.search(query="deadlock", track="errors", include_graph=True, graph_hops=2)
# Returns: [{"node_id": "err_1", "graph_context": {"text_injection": "=== Knowledge Graph Context...", "paths": [...]}}]

# =========================================================================
# L2: On-Demand Deep Read & Section Slicing (< 500 tokens)
# =========================================================================
# Shelf: Slices specific markdown headings without loading the full 800-line skill!
sec = shelf.read("py-modular", section="usage")
# Returns: {"found": True, "section": "Usage", "content": "Split scripts into subpackages..."}

# Vault: Reads full node content, optionally traversing multi-hop neighborhood
node = vault.read("fix_1", include_graph=True, graph_hops=2)
# Returns: {"found": True, "memory": {...}, "graph_context": {...}}
```

### 2.3 Five-Minute Agent Loop Integration

```python
# Phase 1: Prior-Art Ingestion (Search memory and skills before authoring)
history = vault.search(query="subprocess deadlock", track="errors", include_graph=True)
tools = shelf.search(query="python modularizer")

# Phase 2: Pre-Tool Execution Check (AST Verification + 1ms Shadow Snapshot)
decision = gate.evaluate_pre_tool(
    tool_name="write_to_file",
    args={"TargetFile": "app.py", "CodeContent": "def run(): return 42\n"}
)
if decision.get("decision") == "deny":
    print("Action blocked by Nexus:", decision.get("reason"))
else:
    # Perform mutation safely
    pass

# Phase 3: Post-Tool Verification (Ladder Progression)
gate.evaluate_post_tool(
    tool_name="run_command",
    args={"CommandLine": "pytest tests/ -v"},
    exit_code=0
)

# Phase 4: Post-Mortem Feedback (Store discovered solutions and link edges)
vault.store(
    title="Windows Pipe Deadlock Fix",
    content="Always drain child stdout/stderr concurrently.",
    track="errors",
    tags=["windows", "pipes"],
    node_id="err_win_001"
)
vault.link("arch_fix_001", "err_win_001", relation_type="SOLVES")
```

---

## 3. Host Integration Guide (接入指引)

### 3.1 IDE PreToolUse & PostToolUse Hook Setup
Configure host runner (e.g. Antigravity IDE, custom harness) to route actions through `nexus_gate`:

```json
{
  "hooks": {
    "PreInvocation": [
      {
        "command": "python",
        "args": ["-m", "nexus_triad_standalone.nexus_gate.core", "--pre-invocation"]
      }
    ],
    "PreToolUse": [
      {
        "command": "python",
        "args": ["-m", "nexus_triad_standalone.nexus_gate.core", "--pre-tool"]
      }
    ],
    "PostToolUse": [
      {
        "command": "python",
        "args": ["-m", "nexus_triad_standalone.nexus_gate.core", "--post-tool"]
      }
    ]
  }
}
```

### 3.2 Model Context Protocol (MCP) Integration
Wrap `nexus_vault` and `nexus_shelf` in standard stdio MCP servers:

```python
# mcp_server.py
import json, sys
from nexus_vault import MemoryVaultEngine
from nexus_shelf import SkillShelfEngine

vault = MemoryVaultEngine()
shelf = SkillShelfEngine()

# Handle standard MCP json-rpc dispatch for tools:
# - vault_search, vault_store, vault_link, vault_stats
# - shelf_search, shelf_read, shelf_guard, shelf_catalog
```

---

## 4. Authoring & Editing Specifications (编辑与开发规范)

When developing extensions, adding skills, or recording memories, adhere strictly to the following standards:

### 4.1 Skill Shelf Authoring Specification (`SKILL.md`)
Every skill must reside in its own subdirectory and contain a single `SKILL.md` file following this exact YAML frontmatter format:

```markdown
---
name: your-skill-name
description: "Precise 1-2 sentence description explaining exact capabilities and trigger situations."
---
# Skill Title

## Core Philosophy
1. Concise operational principles.

## CLI / Tool Usage
Instructions on how the agent or host invokes this skill.

## Verification Gate
How to verify the skill functioned properly (Exit Code 0, automated tests).
```

* **Line Budget Rule**: Individual `SKILL.md` files must not exceed **800 lines**.
* **Language & Tokenization**: Indexer processes English words and Chinese 2-grams. Include accurate keywords in both the `description` and section headers for optimal BM25 ranking.

### 4.2 Memory Vault Tracking Specification
When persisting memories via `vault.store(...)`, categorize entries under one of the five canonical domain tracks:

| Track Name | Scope & Purpose | Example Content |
| :--- | :--- | :--- |
| `errors` | Anti-patterns, bugs, root causes, and traps | `Subprocess pipe buffer exhaustion on Windows` |
| `architecture` | Structural invariants, ADRs, interface contracts | `Zero-dependency standard library constraint` |
| `worklog` | Session progress milestones and causality summaries | `Refactored parser from regex to state machine` |
| `domain` | Specialized technical domain facts (CDP, audio, OCR) | `Lit Element shadow DOM querySelector rules` |
| `general` | Universal project configuration and environment data | `Python virtual environment layout` |

#### Graph Relationship Semantics
When linking memories via `vault.link(source, target, relation_type)`:
* `SOLVES`: Solution node resolves a bug/anti-pattern node.
* `SUPERSEDES`: New node invalidates and replaces an older version (automatically sets `invalid_at`).
* `RELATES_TO`: General bidirectional semantic association.
* `DERIVED_FROM`: Architectural refinement or parent-child lineage.
* `MONITORED_BY`: Diagnostic or telemetry observer relationship.

#### Multi-Hop Knowledge Graph Expansion & Model Injection
The graph engine supports recursive BFS expansion (`get_multihop_context(node_id, hops=2, max_nodes=15)`) that automatically resolves entity attributes from the SQLite persistence table and generates human- and LLM-readable text injection blocks:

```text
=== Knowledge Graph Context (Root: arch_001, Hops: 2, Nodes: 3, Edges: 2) ===
[Semantic Paths]
  - (arch_001: 'Async Process Protocol') --[SOLVES (w=1.0)]--> (err_001: 'Subprocess Buffer Deadlock')
  - (err_001: 'Subprocess Buffer Deadlock') --[MONITORED_BY (w=1.0)]--> (mon_001: 'Stream Buffer Monitor')
[Connected Entities]
  * [arch_001] (track: architecture, v1): Async Process Protocol [#async #pipes]
    Summary: Use communicate() or asyncio streams to concurrently drain pipes...
  * [err_001] (track: errors, v1): Subprocess Buffer Deadlock [#windows #subprocess #deadlock]
    Summary: On Windows, draining stdout without draining stderr can deadlock child processes...
  * [mon_001] (track: monitoring, v1): Stream Buffer Monitor [#buffer #metrics]
    Summary: Monitor high-water mark for inter-process buffers...
```

#### Dual Retrieval Modes
1. **Standalone Item Retrieval** (`include_graph=False`):
   Ideal for rapid semantic lookups, low-latency search, or strict token budgets. Returns only memory metadata and dynamic keyword snippets without graph traversal overhead.
2. **Graph-Paired Retrieval** (`include_graph=True`):
   Ideal for architectural decision making, causal debugging, and solution synthesis. Injects connected node topologies, semantic paths, and entity summaries into each search hit.
3. **Direct Graph Traversal** (`vault.get_graph(node_id, hops=2)`):
   Inspects the topological neighborhood of any memory entity independently of full-text search.

### 4.3 Code Modification Physical Redlines
Under Nexus governance, code authored or modified by agents must strictly observe:

1. **Deterministic Syntax Validity (AST Gate)**:
   Any Python file written via `write_to_file` or `replace_file_content` is parsed through `ast.parse`. Syntax errors immediately abort the write and return a micro-capsule diagnostic.
2. **Cliff Truncation Defense**:
   If an edit reduces file length by more than **65%** (content ratio < 35%), the write is blocked to protect against accidental stubbing or truncation.
   * *Shim Exception*: Legitimate re-export shims (containing `__all__`, `import `, or `from .` under 2000 chars) are recognized and allowed.
3. **800-Line Substrate Budget**:
   Monolithic files exceeding 800 lines must be split into modular packages with re-export shims.
4. **Data Isolation Rule**:
   All runtime outputs, databases, caches, and state machine files must be saved in the corresponding component's `data/` subfolder.
5. **Zero-Emoji Discipline**:
   Source code, comments, log strings, and documentation must contain zero emoji characters. Use standard ASCII and markdown notation.

---

## 5. Verification & Testing

Verify that all components are functioning properly on your system:

```powershell
# 1. Bytecode verification
python -m py_compile nexus_gate/core.py nexus_vault/core.py nexus_shelf/core.py

# 2. Integration test suite
python -m unittest tests/test_standalone.py
```
