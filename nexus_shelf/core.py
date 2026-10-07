"""Nexus Shelf: Dynamic Skill Indexing, BM25 Scoring, and Governance.

Standalone, zero-dependency architecture component providing dynamic skill discovery,
bilingual BM25 retrieval, and physical code truncation governance.
All runtime persistence files (cache, index, reports) default to the component's data/ subfolder.
"""

from __future__ import annotations

import json
import math
import os
import re
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

DEFAULT_DATA_DIR = Path(__file__).resolve().parent / "data"


# ============================================================================
# 1. Thread-Safe In-Memory TTL Cache
# ============================================================================

class TTLCache:
    """Thread-safe in-memory cache with time-to-live expiration."""

    def __init__(self, default_ttl: float = 60.0):
        self.default_ttl = default_ttl
        self._store: Dict[str, Tuple[float, Any]] = {}
        self._lock = threading.Lock()

    def get(self, key: str) -> Optional[Any]:
        with self._lock:
            if key not in self._store:
                return None
            expiry, val = self._store[key]
            if time.time() > expiry:
                del self._store[key]
                return None
            return val

    def set(self, key: str, val: Any, ttl: Optional[float] = None) -> None:
        with self._lock:
            t = ttl if ttl is not None else self.default_ttl
            self._store[key] = (time.time() + t, val)

    def clear(self) -> None:
        with self._lock:
            self._store.clear()


# ============================================================================
# 2. Dynamic Skill Indexer & BM25 Scoring Engine
# ============================================================================

class SkillIndexer:
    """Indexes markdown skills with bilingual BM25 length-normalized scoring."""

    def __init__(self, skill_roots: Optional[List[str | Path]] = None, data_dir: Optional[str | Path] = None):
        self.data_dir = Path(data_dir or DEFAULT_DATA_DIR).resolve()
        self.data_dir.mkdir(parents=True, exist_ok=True)

        default_roots = [Path(p.strip()) for p in os.environ.get("SKILL_ROOTS", "skills").split(";") if p.strip()]
        self.skill_roots = [Path(p).resolve() for p in (skill_roots or default_roots)]
        self.skills: Dict[str, Dict[str, Any]] = {}
        self.doc_tokens: Dict[str, List[str]] = {}
        self.doc_freq: Dict[str, int] = {}
        self.avg_doc_len: float = 0.0
        self.total_docs: int = 0
        self._lock = threading.RLock()
        self.refresh()

    def _tokenize(self, text: str) -> List[str]:
        """Tokenize text into English alphanumeric words and Chinese 2-grams."""
        text_lower = text.lower()
        words = re.findall(r"[a-z0-9_\-]+", text_lower)
        han_chars = re.findall(r"[\u4e00-\u9fa5]", text_lower)
        two_grams = [han_chars[i] + han_chars[i + 1] for i in range(len(han_chars) - 1)]
        return words + two_grams

    def _parse_frontmatter(self, content: str) -> Dict[str, str]:
        """Extract YAML-style frontmatter headers from markdown."""
        meta: Dict[str, str] = {}
        match = re.match(r"^---\s*\n(.*?)\n---\s*\n", content, re.DOTALL)
        if match:
            for line in match.group(1).splitlines():
                if ":" in line:
                    k, v = line.split(":", 1)
                    meta[k.strip()] = v.strip().strip("\"'")
        return meta

    def refresh(self) -> None:
        """Scan skill roots and compile BM25 inverted index."""
        with self._lock:
            self.skills.clear()
            self.doc_tokens.clear()
            self.doc_freq.clear()
            all_lens = []

            for root in self.skill_roots:
                if not root.is_dir():
                    continue
                for skill_path in root.glob("**/SKILL.md"):
                    try:
                        raw_content = skill_path.read_text(encoding="utf-8", errors="replace")
                        meta = self._parse_frontmatter(raw_content)
                        skill_name = meta.get("name") or skill_path.parent.name
                        category = skill_path.parent.parent.name if skill_path.parent.parent != root else "general"
                        description = meta.get("description", "")

                        if not description:
                            lines = [l.strip() for l in raw_content.splitlines() if l.strip() and not l.startswith(("#", "---"))]
                            description = lines[0] if lines else "No description available."

                        tokens = self._tokenize(f"{skill_name} {category} {description} {raw_content[:2500]}")
                        doc_len = len(tokens)
                        all_lens.append(doc_len)

                        self.skills[skill_name] = {
                            "name": skill_name,
                            "category": category,
                            "description": description,
                            "path": str(skill_path),
                            "content": raw_content,
                            "doc_len": doc_len,
                        }
                        self.doc_tokens[skill_name] = tokens

                        for term in set(tokens):
                            self.doc_freq[term] = self.doc_freq.get(term, 0) + 1
                    except Exception:
                        continue

            self.total_docs = len(self.skills)
            self.avg_doc_len = (sum(all_lens) / self.total_docs) if self.total_docs > 0 else 0.0

            # Cache index metadata in data/ subfolder
            try:
                cache_file = self.data_dir / "index_cache.json"
                cache_data = {
                    "total_docs": self.total_docs,
                    "avg_doc_len": self.avg_doc_len,
                    "skills": list(self.skills.keys()),
                    "updated_at": time.time(),
                }
                cache_file.write_text(json.dumps(cache_data, indent=2, ensure_ascii=False), encoding="utf-8")
            except Exception:
                pass

    def _extract_snippet(self, content: str, query: str = "", max_chars: int = 150) -> str:
        """Extract a concise context window centered around query tokens from markdown content."""
        if not content:
            return ""
        clean = " ".join(content.split())
        if not query.strip():
            return clean[:max_chars] + ("..." if len(clean) > max_chars else "")

        lower_clean = clean.lower()
        q_tokens = self._tokenize(query)
        idx = -1
        matched_tok = ""
        for tok in q_tokens:
            pos = lower_clean.find(tok)
            if pos != -1:
                idx = pos
                matched_tok = tok
                break

        if idx == -1:
            return clean[:max_chars] + ("..." if len(clean) > max_chars else "")

        start = max(0, idx - 40)
        end = min(len(clean), idx + len(matched_tok) + 100)
        prefix = "..." if start > 0 else ""
        suffix = "..." if end < len(clean) else ""
        return prefix + clean[start:end].strip() + suffix

    def search(self, query: str, top_k: int = 5, category: Optional[str] = None) -> List[Dict[str, Any]]:
        """Score skills against query using BM25 ranking."""
        with self._lock:
            if not self.skills or not query.strip():
                return []

            q_tokens = self._tokenize(query)
            if not q_tokens:
                return []

            scores: Dict[str, float] = {}
            k1 = 1.5
            b = 0.75

            for skill_name, skill_data in self.skills.items():
                if category and skill_data["category"].lower() != category.lower():
                    continue

                doc_len = skill_data["doc_len"]
                tokens = self.doc_tokens.get(skill_name, [])
                tf_map: Dict[str, int] = {}
                for t in tokens:
                    tf_map[t] = tf_map.get(t, 0) + 1

                score = 0.0
                for t in q_tokens:
                    if t not in tf_map:
                        continue
                    tf = tf_map[t]
                    df = self.doc_freq.get(t, 0)
                    idf = math.log((self.total_docs - df + 0.5) / (df + 0.5) + 1.0)
                    tf_norm = (tf * (k1 + 1)) / (tf + k1 * (1 - b + b * (doc_len / max(1.0, self.avg_doc_len))))
                    score += idf * tf_norm

                if score > 0.0:
                    scores[skill_name] = score

            ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:top_k]
            results = []
            for name, score in ranked:
                item = self.skills[name].copy()
                raw_content = item.get("content", "")
                item.pop("content", None)
                item["score"] = round(score, 4)
                item["match_snippet"] = self._extract_snippet(raw_content, query=query)
                results.append(item)

            return results

    def read_skill(self, skill_name: str) -> Optional[Dict[str, Any]]:
        """Retrieve full markdown content for a skill."""
        with self._lock:
            return self.skills.get(skill_name)


# ============================================================================
# 3. Governance & Quality Guard Engine
# ============================================================================

class GovernanceEngine:
    """Physical safety, cliff truncation defense, and line budget governance."""

    def __init__(
        self,
        allowed_workspaces: Optional[List[str | Path]] = None,
        cliff_threshold: float = 0.35,
        max_lines: int = 800,
        data_dir: Optional[str | Path] = None,
    ):
        self.data_dir = Path(data_dir or DEFAULT_DATA_DIR).resolve()
        self.data_dir.mkdir(parents=True, exist_ok=True)

        default_ws = [Path.cwd()]
        self.allowed_workspaces = [Path(w).resolve() for w in (allowed_workspaces or default_ws)]
        self.cliff_threshold = cliff_threshold
        self.max_lines = max_lines

    def check_workspace_access(self, target_path: str | Path) -> Tuple[bool, str]:
        """Verify whether target path is contained within configured workspaces."""
        resolved = Path(target_path).resolve()
        for ws in self.allowed_workspaces:
            try:
                resolved.relative_to(ws)
                return True, f"Path {resolved} is contained in workspace {ws}"
            except ValueError:
                continue
        return False, f"Access denied: {resolved} is outside allowed workspaces {[str(w) for w in self.allowed_workspaces]}"

    def check_cliff_truncation(self, target_path: str | Path, new_content: str) -> Tuple[bool, str]:
        """Detect dangerous code deletion / accidental truncation stubs."""
        p = Path(target_path)
        if not p.is_file():
            return True, "Target file does not exist; creation is safe"

        try:
            old_content = p.read_text(encoding="utf-8", errors="replace")
        except Exception as exc:
            return True, f"Read check skipped due to I/O notice: {exc}"

        old_len = len(old_content)
        new_len = len(new_content)
        if old_len < 150:
            return True, "File is small; truncation check passed"

        ratio = new_len / old_len
        if ratio < self.cliff_threshold:
            # Re-export shim whitelist pattern detection
            is_shim = any(m in new_content for m in ("__all__", "import ", "from .", "deprecated", "shim")) and new_len < 2000
            if is_shim:
                return True, f"Shim pattern detected (safe re-export refactor). Ratio: {ratio:.2%}"
            return False, f"Cliff truncation blocked! Content shrank from {old_len} to {new_len} chars ({ratio:.2%} < {self.cliff_threshold:.2%}). Accidental overwrite suspected."

        return True, f"Cliff check passed. Ratio: {ratio:.2%}"

    def check_file_length(self, target_path: str | Path, content: Optional[str] = None) -> Tuple[bool, str]:
        """Enforce file line budget discipline (< 800 lines)."""
        if content is not None:
            num_lines = len(content.splitlines())
        else:
            p = Path(target_path)
            if not p.is_file():
                return True, "File does not exist"
            num_lines = len(p.read_text(encoding="utf-8", errors="replace").splitlines())

        if num_lines > self.max_lines:
            return False, f"Line budget exceeded! File has {num_lines} lines (budget limit: {self.max_lines}). Modularize into subpackages."
        return True, f"Line budget passed ({num_lines}/{self.max_lines} lines)"


# ============================================================================
# 4. Universal Skill Shelf Engine (Facade)
# ============================================================================

class SkillShelfEngine:
    """Universal high-level facade coordinating discovery, indexing, and governance."""

    def __init__(
        self,
        skill_roots: Optional[List[str | Path]] = None,
        allowed_workspaces: Optional[List[str | Path]] = None,
        data_dir: Optional[str | Path] = None,
    ):
        self.data_dir = Path(data_dir or DEFAULT_DATA_DIR).resolve()
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.indexer = SkillIndexer(skill_roots=skill_roots, data_dir=self.data_dir)
        self.governance = GovernanceEngine(allowed_workspaces=allowed_workspaces, data_dir=self.data_dir)

    def search(self, query: str, top_k: int = 5, category: Optional[str] = None) -> List[Dict[str, Any]]:
        """Search local skill shelf with BM25 score."""
        return self.indexer.search(query=query, top_k=top_k, category=category)

    def _parse_sections(self, content: str) -> Dict[str, str]:
        """Parse markdown content into sections by headers (#, ##, ###)."""
        lines = content.splitlines()
        sections: Dict[str, List[str]] = {}
        current_section = "overview"
        sections[current_section] = []

        header_re = re.compile(r"^(#{1,6})\s+(.+)$")
        for line in lines:
            m = header_re.match(line.strip())
            if m:
                current_section = m.group(2).strip()
                if current_section not in sections:
                    sections[current_section] = []
            else:
                sections[current_section].append(line)

        cleaned_sections: Dict[str, str] = {}
        for sec, sec_lines in sections.items():
            sec_text = "\n".join(sec_lines).strip()
            if sec_text:
                cleaned_sections[sec] = sec_text
        return cleaned_sections

    def read(self, skill_name: str, section: Optional[str] = None) -> Dict[str, Any]:
        """Read full instructions or a specific section for a specified skill."""
        sk = self.indexer.read_skill(skill_name)
        if not sk:
            return {"found": False, "error": f"Skill '{skill_name}' not found on shelf"}

        raw_content = sk.get("content", "")
        available_sections = self._parse_sections(raw_content)

        if not section:
            result_skill = sk.copy()
            result_skill["sections"] = list(available_sections.keys())
            return {"found": True, "skill": result_skill}

        norm_target = section.strip().lower()
        matched_sec = None
        for sec_name in available_sections:
            if norm_target == sec_name.lower() or norm_target in sec_name.lower():
                matched_sec = sec_name
                break

        if not matched_sec:
            return {
                "found": True,
                "section_found": False,
                "skill_name": skill_name,
                "requested_section": section,
                "error": f"Section '{section}' not found in skill '{skill_name}'",
                "available_sections": list(available_sections.keys()),
            }

        return {
            "found": True,
            "section_found": True,
            "skill_name": skill_name,
            "section": matched_sec,
            "content": available_sections[matched_sec],
            "available_sections": list(available_sections.keys()),
        }

    def guard(self, action: str, target_path: Optional[str] = None, content: Optional[str] = None) -> Dict[str, Any]:
        """Execute physical governance checks."""
        if action == "cliff_check":
            if not target_path or content is None:
                return {"pass": False, "reason": "Missing target_path or content for cliff_check"}
            ok, msg = self.governance.check_cliff_truncation(target_path, content)
            return {"pass": ok, "message": msg}

        if action == "length_check":
            if not target_path:
                return {"pass": False, "reason": "Missing target_path"}
            ok, msg = self.governance.check_file_length(target_path, content)
            return {"pass": ok, "message": msg}

        if action == "workspace_check":
            if not target_path:
                return {"pass": False, "reason": "Missing target_path"}
            ok, msg = self.governance.check_workspace_access(target_path)
            return {"pass": ok, "message": msg}

        return {"pass": False, "reason": f"Unknown guard action '{action}'"}

    def list_catalog(self) -> List[Dict[str, Any]]:
        """List summary catalog of all indexed skills."""
        return [
            {
                "name": s["name"],
                "category": s["category"],
                "description": s["description"],
            }
            for s in self.indexer.skills.values()
        ]

    def refresh(self) -> None:
        """Re-scan skill directories and rebuild index."""
        self.indexer.refresh()


if __name__ == "__main__":
    import tempfile
    print("Testing Nexus Shelf...")
    with tempfile.TemporaryDirectory() as tmp_dir:
        # Create mock skill directory
        skill_dir = Path(tmp_dir) / "domain" / "mock-tool"
        skill_dir.mkdir(parents=True, exist_ok=True)
        (skill_dir / "SKILL.md").write_text(
            "---\nname: mock-tool\ndescription: Mock testing tool for OCR and speech transcription.\n---\n# Mock Tool\nDetails here.\n## Usage\nRun tool.",
            encoding="utf-8",
        )

        shelf = SkillShelfEngine(skill_roots=[tmp_dir], allowed_workspaces=[tmp_dir], data_dir=Path(tmp_dir) / "data")

        # Test 1: Search with dynamic match_snippet
        res = shelf.search(query="OCR transcription")
        assert len(res) == 1
        assert res[0]["name"] == "mock-tool"
        assert "match_snippet" in res[0]

        # Test 2: Read Full
        detail = shelf.read("mock-tool")
        assert detail["found"]
        assert "Mock Tool" in detail["skill"]["content"]
        assert "sections" in detail["skill"]

        # Test 3: Read Section Slicing
        sec_read = shelf.read("mock-tool", section="usage")
        assert sec_read["found"] and sec_read["section_found"]
        assert "Run tool." in sec_read["content"]

        # Test 4: Read Missing Section
        missing_sec = shelf.read("mock-tool", section="nonexistent")
        assert missing_sec["found"] and not missing_sec["section_found"]
        assert "available_sections" in missing_sec

        # Test 5: Cliff Guard
        file_to_test = Path(tmp_dir) / "code.py"
        file_to_test.write_text("x = 1\n" * 200, encoding="utf-8")
        guard_res = shelf.guard("cliff_check", target_path=str(file_to_test), content="x = 1\n")
        assert not guard_res["pass"]

        print("Nexus Shelf tests passed successfully.")
