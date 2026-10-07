"""Nexus Vault: Temporal Knowledge Graph & Persistent Episodic Memory.

Standalone, zero-dependency architecture component providing SQLite WAL persistence,
FTS5 Trigram full-text search, and embedded temporal knowledge graphs.
All runtime persistence files (vault.db, wal, shm) default to the component's data/ subfolder.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

DEFAULT_DATA_DIR = Path(__file__).resolve().parent / "data"


def _extract_snippet(text: str, query: str = "", max_chars: int = 150) -> str:
    """Extract a concise context window centered on query, or prefix text."""
    if not text:
        return ""
    clean = " ".join(text.split())
    if not query.strip():
        return clean[:max_chars] + ("..." if len(clean) > max_chars else "")

    lower_text = clean.lower()
    lower_q = query.lower().strip()
    idx = lower_text.find(lower_q)
    if idx == -1:
        tokens = [t for t in re.findall(r"\w+", lower_q) if len(t) > 1]
        for t in tokens:
            pos = lower_text.find(t)
            if pos != -1:
                idx = pos
                break

    if idx == -1:
        return clean[:max_chars] + ("..." if len(clean) > max_chars else "")

    start = max(0, idx - 40)
    end = min(len(clean), idx + len(query) + 90)
    prefix = "..." if start > 0 else ""
    suffix = "..." if end < len(clean) else ""
    return prefix + clean[start:end].strip() + suffix



# ============================================================================
# 1. Database Manager with Schema & FTS5 Synchronization
# ============================================================================

class DatabaseManager:
    """SQLite Database Manager with WAL mode and FTS5 Trigram virtual indexing."""

    def __init__(self, db_path: Optional[str | Path] = None):
        if db_path:
            self.db_path = Path(db_path).resolve()
        else:
            DEFAULT_DATA_DIR.mkdir(parents=True, exist_ok=True)
            self.db_path = (DEFAULT_DATA_DIR / "vault.db").resolve()

        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self.initialize_schema()

    def get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), check_same_thread=False, timeout=15.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA foreign_keys = ON;")
        return conn

    def initialize_schema(self) -> None:
        with self._lock:
            conn = self.get_connection()
            try:
                conn.executescript("""
                    CREATE TABLE IF NOT EXISTS memories (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        node_id TEXT UNIQUE NOT NULL,
                        track TEXT NOT NULL,
                        title TEXT NOT NULL,
                        content TEXT NOT NULL,
                        tags TEXT NOT NULL DEFAULT '[]',
                        metadata TEXT NOT NULL DEFAULT '{}',
                        version INTEGER NOT NULL DEFAULT 1,
                        is_active INTEGER NOT NULL DEFAULT 1,
                        created_at REAL NOT NULL,
                        updated_at REAL NOT NULL
                    );
                    CREATE INDEX IF NOT EXISTS idx_memories_track ON memories(track);
                    CREATE INDEX IF NOT EXISTS idx_memories_node_id ON memories(node_id);
                    CREATE INDEX IF NOT EXISTS idx_memories_active ON memories(is_active);

                    CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(
                        title, content, tags, track UNINDEXED,
                        content='memories', content_rowid='id', tokenize='trigram'
                    );

                    CREATE TRIGGER IF NOT EXISTS trg_memories_ai AFTER INSERT ON memories BEGIN
                        INSERT INTO memories_fts(rowid, title, content, tags, track)
                        VALUES (new.id, new.title, new.content, new.tags, new.track);
                    END;
                    CREATE TRIGGER IF NOT EXISTS trg_memories_ad AFTER DELETE ON memories BEGIN
                        INSERT INTO memories_fts(memories_fts, rowid, title, content, tags, track)
                        VALUES ('delete', old.id, old.title, old.content, old.tags, old.track);
                    END;
                    CREATE TRIGGER IF NOT EXISTS trg_memories_au AFTER UPDATE ON memories BEGIN
                        INSERT INTO memories_fts(memories_fts, rowid, title, content, tags, track)
                        VALUES ('delete', old.id, old.title, old.content, old.tags, old.track);
                        INSERT INTO memories_fts(rowid, title, content, tags, track)
                        VALUES (new.id, new.title, new.content, new.tags, new.track);
                    END;

                    CREATE TABLE IF NOT EXISTS memory_relations (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        source_node TEXT NOT NULL,
                        target_node TEXT NOT NULL,
                        relation_type TEXT NOT NULL,
                        weight REAL NOT NULL DEFAULT 1.0,
                        valid_at REAL NOT NULL,
                        invalid_at REAL,
                        metadata TEXT NOT NULL DEFAULT '{}'
                    );
                    CREATE INDEX IF NOT EXISTS idx_rel_source ON memory_relations(source_node);
                    CREATE INDEX IF NOT EXISTS idx_rel_target ON memory_relations(target_node);
                    CREATE INDEX IF NOT EXISTS idx_rel_type ON memory_relations(relation_type);
                """)
                conn.commit()
            finally:
                conn.close()


# ============================================================================
# 2. Temporal Knowledge Graph Engine
# ============================================================================

class TemporalGraphEngine:
    """Manages relationship edges with temporal validity windows and recursive traversal."""

    def __init__(self, db: DatabaseManager, max_depth: int = 2):
        self.db = db
        self.max_depth = max_depth

    def add_relation(
        self,
        source_node: str,
        target_node: str,
        relation_type: str,
        weight: float = 1.0,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Insert or update a relation edge. SUPERSEDES edges invalidate prior targets."""
        now = time.time()
        meta_json = json.dumps(metadata or {}, ensure_ascii=False)

        conn = self.db.get_connection()
        try:
            cursor = conn.cursor()
            if relation_type.upper() == "SUPERSEDES":
                cursor.execute("""
                    UPDATE memory_relations
                    SET invalid_at = ?
                    WHERE target_node = ? AND invalid_at IS NULL;
                """, (now, target_node))

            cursor.execute("""
                INSERT INTO memory_relations (source_node, target_node, relation_type, weight, valid_at, invalid_at, metadata)
                VALUES (?, ?, ?, ?, ?, NULL, ?);
            """, (source_node, target_node, relation_type.upper(), weight, now, meta_json))
            edge_id = cursor.lastrowid
            conn.commit()

            return {
                "success": True,
                "edge_id": edge_id,
                "source": source_node,
                "target": target_node,
                "relation": relation_type.upper(),
                "valid_at": now,
            }
        finally:
            conn.close()

    def invalidate_edge(self, source_node: str, target_node: str, relation_type: Optional[str] = None) -> bool:
        """Invalidate an active relation edge by setting invalid_at timestamp."""
        now = time.time()
        conn = self.db.get_connection()
        try:
            cursor = conn.cursor()
            query = "UPDATE memory_relations SET invalid_at = ? WHERE source_node = ? AND target_node = ? AND invalid_at IS NULL"
            params: list[Any] = [now, source_node, target_node]
            if relation_type:
                query += " AND relation_type = ?"
                params.append(relation_type.upper())
            cursor.execute(query, params)
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()

    def get_node_relations(self, node_id: str, active_only: bool = True) -> List[Dict[str, Any]]:
        """Fetch all relations connected to a node (inward and outward)."""
        conn = self.db.get_connection()
        try:
            cursor = conn.cursor()
            query = """
                SELECT id, source_node, target_node, relation_type, weight, valid_at, invalid_at, metadata
                FROM memory_relations
                WHERE (source_node = ? OR target_node = ?)
            """
            params: list[Any] = [node_id, node_id]
            if active_only:
                query += " AND invalid_at IS NULL"
            query += " ORDER BY valid_at DESC;"

            cursor.execute(query, params)
            return [dict(row) for row in cursor.fetchall()]
        finally:
            conn.close()

    def traverse_subgraph(self, start_node: str, max_depth: Optional[int] = None) -> Dict[str, Any]:
        """Breadth-first search traversal returning connected subgraphs up to max_depth."""
        ctx = self.get_multihop_context(start_node, hops=max_depth or self.max_depth)
        return {
            "root": ctx["root"],
            "nodes": [n["node_id"] for n in ctx["nodes"]],
            "edges": ctx["edges"],
            "node_count": ctx["node_count"],
            "edge_count": ctx["edge_count"],
        }

    def get_multihop_context(
        self,
        start_node: str,
        hops: int = 2,
        max_nodes: int = 15,
    ) -> Dict[str, Any]:
        """Traverse connected graph up to N hops, resolves node memory details, and compiles text injection block."""
        depth_limit = hops if hops is not None else self.max_depth
        visited_nodes: set[str] = {start_node}
        edges_collected: list[dict[str, Any]] = []
        seen_edge_keys: set[str] = set()
        frontier = [start_node]

        conn = self.db.get_connection()
        try:
            cursor = conn.cursor()
            for _ in range(depth_limit):
                if not frontier or len(visited_nodes) >= max_nodes:
                    break
                placeholders = ",".join("?" for _ in frontier)
                cursor.execute(f"""
                    SELECT id, source_node, target_node, relation_type, weight, valid_at, metadata
                    FROM memory_relations
                    WHERE (source_node IN ({placeholders}) OR target_node IN ({placeholders}))
                      AND invalid_at IS NULL;
                """, frontier + frontier)

                new_frontier: set[str] = set()
                for row in cursor.fetchall():
                    edge = dict(row)
                    s, t = edge["source_node"], edge["target_node"]
                    rel = edge["relation_type"]
                    edge_key = f"{edge['id']}:{s}->{rel}->{t}"
                    if edge_key not in seen_edge_keys:
                        seen_edge_keys.add(edge_key)
                        edges_collected.append(edge)

                    if s not in visited_nodes and len(visited_nodes) < max_nodes:
                        visited_nodes.add(s)
                        new_frontier.add(s)
                    if t not in visited_nodes and len(visited_nodes) < max_nodes:
                        visited_nodes.add(t)
                        new_frontier.add(t)
                frontier = list(new_frontier)

            # Resolve node attributes from memories table
            nodes_map: dict[str, dict[str, Any]] = {}
            if visited_nodes:
                p_nodes = ",".join("?" for _ in visited_nodes)
                cursor.execute(f"""
                    SELECT id, node_id, track, title, content, tags, metadata, version, updated_at
                    FROM memories
                    WHERE node_id IN ({p_nodes}) AND is_active = 1;
                """, list(visited_nodes))
                for row in cursor.fetchall():
                    item = dict(row)
                    try:
                        item["tags"] = json.loads(item["tags"])
                    except Exception:
                        item["tags"] = []
                    try:
                        item["metadata"] = json.loads(item["metadata"])
                    except Exception:
                        item["metadata"] = {}
                    item["summary"] = _extract_snippet(item.get("content", ""), max_chars=120)
                    nodes_map[item["node_id"]] = item

            # Provide fallback descriptors for visited nodes without memory row
            for nid in visited_nodes:
                if nid not in nodes_map:
                    nodes_map[nid] = {
                        "node_id": nid,
                        "track": "external",
                        "title": nid,
                        "content": "",
                        "summary": "",
                        "tags": [],
                        "metadata": {},
                        "version": 1,
                    }

            # Generate semantic path strings
            paths: list[str] = []
            for edge in edges_collected:
                s_id = edge["source_node"]
                t_id = edge["target_node"]
                s_title = nodes_map.get(s_id, {}).get("title", s_id)
                t_title = nodes_map.get(t_id, {}).get("title", t_id)
                rel = edge["relation_type"]
                weight = edge.get("weight", 1.0)
                paths.append(f"({s_id}: '{s_title}') --[{rel} (w={weight})]--> ({t_id}: '{t_title}')")

            # Compile text injection block
            lines = [
                f"=== Knowledge Graph Context (Root: {start_node}, Hops: {hops}, Nodes: {len(nodes_map)}, Edges: {len(edges_collected)}) ===",
                "[Semantic Paths]",
            ]
            if paths:
                for p in paths:
                    lines.append(f"  - {p}")
            else:
                lines.append("  (No active relationship edges found)")

            lines.append("[Connected Entities]")
            sorted_nodes = sorted(
                nodes_map.values(),
                key=lambda n: (0 if n["node_id"] == start_node else 1, n["node_id"]),
            )
            for n in sorted_nodes:
                tag_str = " ".join(f"#{t}" for t in n.get("tags", [])) if n.get("tags") else ""
                tag_part = f" [{tag_str}]" if tag_str else ""
                summary_part = f"\n    Summary: {n['summary']}" if n.get("summary") else ""
                lines.append(
                    f"  * [{n['node_id']}] (track: {n.get('track', 'general')}, v{n.get('version', 1)}): {n['title']}{tag_part}{summary_part}"
                )

            text_injection = "\n".join(lines)

            return {
                "root": start_node,
                "hops": hops,
                "nodes": list(nodes_map.values()),
                "edges": edges_collected,
                "paths": paths,
                "text_injection": text_injection,
                "node_count": len(nodes_map),
                "edge_count": len(edges_collected),
            }
        finally:
            conn.close()


# ============================================================================
# 3. Dual-Engine Memory Searcher
# ============================================================================

class MemorySearcher:
    """Combines SQLite FTS5 Trigram full-text search with 1-Hop Graph enrichment."""

    def __init__(self, db: DatabaseManager, graph: TemporalGraphEngine):
        self.db = db
        self.graph = graph

    def search(
        self,
        query: str,
        track: str = "all",
        limit: int = 5,
        detail: bool = False,
        include_graph: bool = False,
        graph_hops: int = 2,
    ) -> List[Dict[str, Any]]:
        clean_q = query.strip().replace("'", "").replace('"', "").replace("*", "")
        if not clean_q:
            return []

        conn = self.db.get_connection()
        try:
            cursor = conn.cursor()
            rows: list[Any] = []

            # 1. Attempt FTS5 Trigram Match
            fts_sql = """
                SELECT m.id, m.node_id, m.track, m.title, m.content, m.tags, m.metadata, m.version, m.updated_at,
                       bm25(memories_fts) as rank
                FROM memories_fts f
                JOIN memories m ON f.rowid = m.id
                WHERE memories_fts MATCH ? AND m.is_active = 1
            """
            params: list[Any] = [clean_q]
            if track != "all":
                fts_sql += " AND m.track = ?"
                params.append(track)
            fts_sql += " ORDER BY rank LIMIT ?;"
            params.append(limit)

            try:
                cursor.execute(fts_sql, params)
                rows = cursor.fetchall()
            except sqlite3.OperationalError:
                rows = []

            # 2. Fallback to LIKE substring search if FTS5 matches are sparse
            if len(rows) < limit:
                existing_ids = set(r["id"] for r in rows)
                like_sql = """
                    SELECT id, node_id, track, title, content, tags, metadata, version, updated_at, 999.0 as rank
                    FROM memories
                    WHERE (title LIKE ? OR content LIKE ? OR tags LIKE ?) AND is_active = 1
                """
                like_pat = f"%{clean_q}%"
                like_params: list[Any] = [like_pat, like_pat, like_pat]
                if track != "all":
                    like_sql += " AND track = ?"
                    like_params.append(track)
                like_sql += " LIMIT ?;"
                like_params.append(limit - len(rows))

                cursor.execute(like_sql, like_params)
                for r in cursor.fetchall():
                    if r["id"] not in existing_ids:
                        rows.append(r)

            results = []
            for row in rows:
                item = dict(row)
                raw_content = item.get("content", "")
                try:
                    item["tags"] = json.loads(item["tags"])
                except Exception:
                    item["tags"] = []
                try:
                    item["metadata"] = json.loads(item["metadata"])
                except Exception:
                    item["metadata"] = {}

                # Attach dynamic snippet around matched query tokens
                item["snippet"] = _extract_snippet(raw_content, query=clean_q)

                # L1 vs L2: omit full content unless detail=True
                if not detail:
                    item.pop("content", None)

                # Standalone vs Graph-paired retrieval
                if include_graph:
                    item["relations"] = self.graph.get_node_relations(item["node_id"], active_only=True)
                    item["graph_context"] = self.graph.get_multihop_context(
                        item["node_id"], hops=graph_hops
                    )

                results.append(item)

            return results
        finally:
            conn.close()


# ============================================================================
# 4. Memory Consolidator
# ============================================================================

class MemoryConsolidator:
    """Manages memory lifecycle, deduplication, versioning, and soft-deletion."""

    def __init__(self, db: DatabaseManager, graph: TemporalGraphEngine):
        self.db = db
        self.graph = graph

    def consolidate_and_store(
        self,
        track: str,
        node_id: str,
        title: str,
        content: str,
        tags: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        relations: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """Insert a new memory or update an existing node with an incremented version."""
        now = time.time()
        tags_list = tags or []
        meta_dict = metadata or {}
        tags_json = json.dumps(tags_list, ensure_ascii=False)
        meta_json = json.dumps(meta_dict, ensure_ascii=False)

        conn = self.db.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT id, version FROM memories WHERE node_id = ?;", (node_id,))
            existing = cursor.fetchone()

            if existing:
                row_id = existing["id"]
                new_version = existing["version"] + 1
                cursor.execute("""
                    UPDATE memories
                    SET title = ?, content = ?, tags = ?, metadata = ?, version = ?, updated_at = ?, is_active = 1
                    WHERE id = ?;
                """, (title, content, tags_json, meta_json, new_version, now, row_id))
                action = "UPDATED"
            else:
                cursor.execute("""
                    INSERT INTO memories (node_id, track, title, content, tags, metadata, version, is_active, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, 1, 1, ?, ?);
                """, (node_id, track, title, content, tags_json, meta_json, now, now))
                row_id = cursor.lastrowid
                new_version = 1
                action = "INSERTED"

            conn.commit()

            # Bind associated relations if provided
            if relations:
                for rel in relations:
                    target = rel.get("target") or rel.get("target_node")
                    rel_type = rel.get("type") or rel.get("relation_type") or "RELATES_TO"
                    weight = float(rel.get("weight", 1.0))
                    if target:
                        self.graph.add_relation(node_id, target, rel_type, weight)

            return {
                "success": True,
                "action": action,
                "node_id": node_id,
                "version": new_version,
                "track": track,
                "row_id": row_id,
            }
        finally:
            conn.close()

    def delete_node(self, node_id: str, hard: bool = False) -> bool:
        """Deactivate or physically delete a node."""
        conn = self.db.get_connection()
        try:
            cursor = conn.cursor()
            if hard:
                cursor.execute("DELETE FROM memories WHERE node_id = ?;", (node_id,))
            else:
                cursor.execute("UPDATE memories SET is_active = 0, updated_at = ? WHERE node_id = ?;", (time.time(), node_id))
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()


# ============================================================================
# 5. Universal Memory Vault Engine (Facade)
# ============================================================================

class MemoryVaultEngine:
    """Universal high-level facade coordinating storage, search, and knowledge graph."""

    def __init__(self, db_path: Optional[str | Path] = None, data_dir: Optional[str | Path] = None):
        target_dir = Path(data_dir or DEFAULT_DATA_DIR).resolve()
        target_dir.mkdir(parents=True, exist_ok=True)
        resolved_db = Path(db_path).resolve() if db_path else target_dir / "vault.db"
        self.db = DatabaseManager(resolved_db)
        self.graph = TemporalGraphEngine(self.db)
        self.searcher = MemorySearcher(self.db, self.graph)
        self.consolidator = MemoryConsolidator(self.db, self.graph)

    def store(
        self,
        title: str,
        content: str,
        track: str = "general",
        tags: Optional[List[str]] = None,
        node_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        relations: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """Persist a memory record into the vault."""
        resolved_node_id = node_id or f"mem_{int(time.time() * 1000)}"
        return self.consolidator.consolidate_and_store(
            track=track,
            node_id=resolved_node_id,
            title=title,
            content=content,
            tags=tags,
            metadata=metadata,
            relations=relations,
        )

    def list_nodes(self, track: str = "all", limit: int = 50, offset: int = 0) -> Dict[str, Any]:
        """L0 Catalog: Retrieve lightweight node index without full content body."""
        conn = self.db.get_connection()
        try:
            cursor = conn.cursor()
            query = "SELECT node_id, track, title, tags, version, updated_at FROM memories WHERE is_active = 1"
            params: list[Any] = []
            if track != "all":
                query += " AND track = ?"
                params.append(track)
            query += " ORDER BY updated_at DESC LIMIT ? OFFSET ?;"
            params.extend([limit, offset])
            cursor.execute(query, params)
            nodes = []
            for r in cursor.fetchall():
                node = dict(r)
                try:
                    node["tags"] = json.loads(node["tags"])
                except Exception:
                    node["tags"] = []
                nodes.append(node)
            return {"total": len(nodes), "track": track, "nodes": nodes}
        finally:
            conn.close()

    def search(
        self,
        query: str,
        track: str = "all",
        limit: int = 5,
        detail: bool = False,
        include_graph: bool = False,
        graph_hops: int = 2,
    ) -> List[Dict[str, Any]]:
        """Search memories across full text, with optional multi-hop graph pairing."""
        return self.searcher.search(
            query=query,
            track=track,
            limit=limit,
            detail=detail,
            include_graph=include_graph,
            graph_hops=graph_hops,
        )

    def read(
        self,
        node_id: str,
        include_graph: bool = False,
        graph_hops: int = 2,
    ) -> Dict[str, Any]:
        """L2 Deep Read: Retrieve full memory record and optional multi-hop graph context."""
        conn = self.db.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, node_id, track, title, content, tags, metadata, version, is_active, created_at, updated_at
                FROM memories
                WHERE node_id = ? AND is_active = 1;
            """, (node_id,))
            row = cursor.fetchone()
            if not row:
                return {"found": False, "error": f"Memory node '{node_id}' not found"}

            item = dict(row)
            try:
                item["tags"] = json.loads(item["tags"])
            except Exception:
                item["tags"] = []
            try:
                item["metadata"] = json.loads(item["metadata"])
            except Exception:
                item["metadata"] = {}

            result = {"found": True, "memory": item}
            if include_graph:
                result["graph_context"] = self.graph.get_multihop_context(node_id, hops=graph_hops)
            return result
        finally:
            conn.close()

    def get_graph(self, node_id: str, hops: int = 2, max_nodes: int = 15) -> Dict[str, Any]:
        """Query multi-hop knowledge graph neighborhood and text injection around a node."""
        return self.graph.get_multihop_context(node_id, hops=hops, max_nodes=max_nodes)

    def link(
        self,
        source_node: str,
        target_node: str,
        relation_type: str = "RELATES_TO",
        weight: float = 1.0,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Establish a semantic edge between two memories."""
        return self.graph.add_relation(source_node, target_node, relation_type, weight, metadata)

    def stats(self) -> Dict[str, Any]:
        """Inspect storage and topology volume metrics."""
        conn = self.db.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM memories WHERE is_active = 1;")
            active_mems = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(*) FROM memory_relations WHERE invalid_at IS NULL;")
            active_edges = cursor.fetchone()[0]
            cursor.execute("SELECT track, COUNT(*) FROM memories WHERE is_active = 1 GROUP BY track;")
            track_counts = {row[0]: row[1] for row in cursor.fetchall()}
            return {
                "active_memories": active_mems,
                "active_relations": active_edges,
                "tracks": track_counts,
                "db_path": str(self.db.db_path),
            }
        finally:
            conn.close()


if __name__ == "__main__":
    import tempfile
    print("Testing Nexus Vault...")
    with tempfile.TemporaryDirectory() as tmp_dir:
        test_db = Path(tmp_dir) / "data" / "test_vault.db"
        vault = MemoryVaultEngine(db_path=test_db)

        # Store test memories
        r1 = vault.store("Subprocess Buffer Deadlock", "On Windows, pipe buffers block.", "errors", ["pipe", "deadlock"], "err_001")
        assert r1["success"] and r1["action"] == "INSERTED"
        r2 = vault.store("Async Process Protocol", "Use communicate() or asyncio streams.", "architecture", ["async"], "arch_001")
        assert r2["success"]
        r3 = vault.store("Stream Buffer Monitor", "Monitor buffer watermarks.", "monitoring", ["buffer"], "mon_001")
        assert r3["success"]

        # Link 2 hops: arch_001 -> err_001 -> mon_001
        assert vault.link("arch_001", "err_001", "SOLVES")["success"]
        assert vault.link("err_001", "mon_001", "MONITORED_BY")["success"]

        # Standalone search (L1 snippet, zero graph overhead)
        hits_standalone = vault.search("deadlock", track="errors", include_graph=False)
        assert len(hits_standalone) >= 1 and hits_standalone[0]["node_id"] == "err_001"
        assert "snippet" in hits_standalone[0] and "graph_context" not in hits_standalone[0]

        # Graph-paired search (multi-hop graph context and text injection)
        hits_paired = vault.search("deadlock", track="errors", include_graph=True, graph_hops=2)
        assert len(hits_paired) >= 1 and "graph_context" in hits_paired[0]
        ctx = hits_paired[0]["graph_context"]
        assert ctx["node_count"] >= 3 and len(ctx["paths"]) >= 2 and "Knowledge Graph Context" in ctx["text_injection"]

        # L0 Catalog
        cat = vault.list_nodes(track="all")
        assert cat["total"] == 3 and any(n["node_id"] == "arch_001" for n in cat["nodes"])

        # L2 Deep Read
        read_std = vault.read("arch_001", include_graph=False)
        assert read_std["found"] and "communicate()" in read_std["memory"]["content"] and "graph_context" not in read_std
        read_g = vault.read("arch_001", include_graph=True, graph_hops=2)
        assert read_g["found"] and read_g["graph_context"]["node_count"] >= 3

        # Direct get_graph & stats
        graph_data = vault.get_graph("arch_001", hops=2)
        assert graph_data["node_count"] >= 3 and len(graph_data["paths"]) >= 2
        st = vault.stats()
        assert st["active_memories"] == 3 and st["active_relations"] == 2

        print("Nexus Vault tests passed successfully.")
