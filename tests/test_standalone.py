"""Integration test suite for nexus_triad_standalone package."""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

_PKG_PARENT = Path(__file__).resolve().parent.parent.parent
if str(_PKG_PARENT) not in sys.path:
    sys.path.insert(0, str(_PKG_PARENT))

from nexus_triad_standalone.nexus_gate import NexusGate, GroundTruthVerifier, PlanCompiler
from nexus_triad_standalone.nexus_vault import MemoryVaultEngine
from nexus_triad_standalone.nexus_shelf import SkillShelfEngine


class TestNexusTriadStandalone(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_nexus_gate_ast_and_data_subfolder(self):
        # Verify gate saves runtime files in data_dir subfolder
        gate_data_dir = self.tmp_path / "nexus_gate_data"
        gate = NexusGate(workspace_root=self.tmp_path, data_dir=gate_data_dir)

        # 1. Valid syntax allows mutation
        res_ok = gate.evaluate_pre_tool(
            "write_to_file",
            {"TargetFile": str(self.tmp_path / "main.py"), "CodeContent": "def func(): return 1\n"}
        )
        self.assertEqual(res_ok.get("decision"), "allow")

        # 2. Syntax error denies mutation
        res_err = gate.evaluate_pre_tool(
            "write_to_file",
            {"TargetFile": str(self.tmp_path / "main.py"), "CodeContent": "def func(\n"}
        )
        self.assertEqual(res_err.get("decision"), "deny")
        self.assertIn("SYNTAX_ERROR", res_err.get("reason", ""))

        # Verify data subfolder contains anchor state
        gate.anchor_manager.save(PlanCompiler.compile("# Plan\n- [ ] Step 1\n"))
        self.assertTrue((gate_data_dir / "anchor_state.json").exists())

    def test_nexus_vault_progressive_disclosure_and_multihop_graph(self):
        vault_data_dir = self.tmp_path / "nexus_vault_data"
        vault = MemoryVaultEngine(data_dir=vault_data_dir)

        # Store 3 nodes across tracks
        r1 = vault.store(
            title="Deadlock Issue",
            content="Pipe buffering can block Windows child processes when stderr is not drained.",
            track="errors",
            tags=["pipe", "deadlock"],
            node_id="err_1",
        )
        self.assertTrue(r1["success"])

        r2 = vault.store(
            title="Async Drainage",
            content="Drain async streams concurrently via communicate() or stream readers.",
            track="architecture",
            tags=["async"],
            node_id="fix_1",
        )
        self.assertTrue(r2["success"])

        r3 = vault.store(
            title="Buffer Watermark Monitor",
            content="Track high-water mark buffer telemetry to prevent overflow.",
            track="monitoring",
            tags=["buffer", "telemetry"],
            node_id="mon_1",
        )
        self.assertTrue(r3["success"])

        # Link 2 hops: fix_1 -> err_1 -> mon_1
        l1 = vault.link("fix_1", "err_1", relation_type="SOLVES")
        self.assertTrue(l1["success"])
        l2 = vault.link("err_1", "mon_1", relation_type="MONITORED_BY")
        self.assertTrue(l2["success"])

        # L0: Catalog listing
        cat = vault.list_nodes(track="all")
        self.assertEqual(cat["total"], 3)
        self.assertTrue(any(n["node_id"] == "fix_1" for n in cat["nodes"]))

        # L1: Standalone search (include_graph=False, default)
        hits_std = vault.search(query="deadlock", track="errors", include_graph=False)
        self.assertGreaterEqual(len(hits_std), 1)
        self.assertEqual(hits_std[0]["node_id"], "err_1")
        self.assertIn("snippet", hits_std[0])
        self.assertNotIn("graph_context", hits_std[0])
        self.assertNotIn("content", hits_std[0])

        # L1: Graph-paired search (include_graph=True, graph_hops=2)
        hits_g = vault.search(query="deadlock", track="errors", include_graph=True, graph_hops=2)
        self.assertGreaterEqual(len(hits_g), 1)
        self.assertIn("graph_context", hits_g[0])
        ctx = hits_g[0]["graph_context"]
        self.assertIn("text_injection", ctx)
        self.assertGreaterEqual(ctx["node_count"], 3)
        self.assertGreaterEqual(len(ctx["paths"]), 2)
        self.assertIn("Knowledge Graph Context", ctx["text_injection"])

        # L2: Standalone read
        read_std = vault.read("fix_1", include_graph=False)
        self.assertTrue(read_std["found"])
        self.assertIn("communicate()", read_std["memory"]["content"])
        self.assertNotIn("graph_context", read_std)

        # L2: Graph-paired read
        read_g = vault.read("fix_1", include_graph=True, graph_hops=2)
        self.assertTrue(read_g["found"])
        self.assertIn("graph_context", read_g)
        self.assertGreaterEqual(read_g["graph_context"]["node_count"], 3)

        # Direct graph retrieval
        graph_view = vault.get_graph("fix_1", hops=2)
        self.assertGreaterEqual(graph_view["node_count"], 3)
        self.assertGreaterEqual(len(graph_view["paths"]), 2)

        # Verify database is created strictly inside component's data subfolder
        self.assertTrue((vault_data_dir / "vault.db").exists())

    def test_nexus_shelf_progressive_disclosure_and_section_slicing(self):
        shelf_data_dir = self.tmp_path / "nexus_shelf_data"
        skill_dir = self.tmp_path / "skills" / "modular"
        skill_dir.mkdir(parents=True, exist_ok=True)
        (skill_dir / "SKILL.md").write_text(
            "---\nname: py-modular\ndescription: Splits files exceeding 800 lines.\n---\n"
            "# Modularizer\nOverview description of the modularizer.\n\n"
            "## Usage\nSplit scripts into subpackages.\n\n"
            "## Examples\nRun py-modular on target file.\n",
            encoding="utf-8",
        )

        shelf = SkillShelfEngine(
            skill_roots=[self.tmp_path / "skills"],
            allowed_workspaces=[self.tmp_path],
            data_dir=shelf_data_dir,
        )

        # L0: Catalog
        catalog = shelf.list_catalog()
        self.assertEqual(len(catalog), 1)
        self.assertEqual(catalog[0]["name"], "py-modular")

        # L1: Search with dynamic match_snippet
        hits = shelf.search("800 lines")
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0]["name"], "py-modular")
        self.assertIn("match_snippet", hits[0])
        self.assertIn("800 lines", hits[0]["match_snippet"])

        # L2: Full Read with sections list
        full_read = shelf.read("py-modular")
        self.assertTrue(full_read["found"])
        self.assertIn("sections", full_read["skill"])
        self.assertIn("Usage", full_read["skill"]["sections"])

        # L2: Section-sliced read
        sec_read = shelf.read("py-modular", section="usage")
        self.assertTrue(sec_read["found"])
        self.assertTrue(sec_read["section_found"])
        self.assertEqual(sec_read["section"], "Usage")
        self.assertIn("Split scripts into subpackages.", sec_read["content"])

        # L2: Non-existent section
        missing_sec = shelf.read("py-modular", section="nonexistent")
        self.assertTrue(missing_sec["found"])
        self.assertFalse(missing_sec["section_found"])
        self.assertIn("available_sections", missing_sec)

        # Verify cache file created in data subfolder
        self.assertTrue((shelf_data_dir / "index_cache.json").exists())

        # Cliff Guard check
        test_file = self.tmp_path / "large.py"
        test_file.write_text("line = 1\n" * 100, encoding="utf-8")
        guard_res = shelf.guard("cliff_check", target_path=str(test_file), content="x = 1\n")
        self.assertFalse(guard_res["pass"])


if __name__ == "__main__":
    unittest.main()
