"""Nexus Gate: Unified Execution Safety, Ephemeral Snapshots, and State Engine.

Standalone, zero-dependency architecture component providing deterministic
compiler-in-the-loop syntax verification, instantaneous Git shadow plumbing,
and tiered attention ladder state management.
"""

from __future__ import annotations

import ast
import json
import os
import re
import shutil
import subprocess
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Optional

DEFAULT_DATA_DIR = Path(__file__).resolve().parent / "data"


# ============================================================================
# 1. Verification & Boundary Safety Data Models
# ============================================================================

@dataclass(frozen=True)
class SyntaxResult:
    """Result of static AST syntax verification."""
    is_valid: bool
    filename: str
    error_type: Optional[str] = None
    line_number: Optional[int] = None
    column_offset: Optional[int] = None
    error_message: Optional[str] = None

    def format_diagnostic(self) -> str:
        if self.is_valid:
            return f"[AST_OK] Syntax valid for {self.filename}"
        return (
            f"[AST_FAIL] {self.filename}:{self.line_number}:{self.column_offset}: "
            f"{self.error_type}: {self.error_message}"
        )


@dataclass(frozen=True)
class SafetyResult:
    """Result of path boundary and containment checks."""
    is_safe: bool
    resolved_path: str
    reason: str


@dataclass(frozen=True)
class SnapshotResult:
    """Result of a shadow snapshot capture."""
    success: bool
    commit_hash: Optional[str] = None
    tree_hash: Optional[str] = None
    error: Optional[str] = None


@dataclass(frozen=True)
class RollbackResult:
    """Result of a physical rollback operation."""
    success: bool
    target_hash: str
    error: Optional[str] = None


# ============================================================================
# 2. Ground Truth Verifier
# ============================================================================

class GroundTruthVerifier:
    """In-memory syntax and boundary safety verification engine."""

    @staticmethod
    def verify_syntax(code: str, filename: str = "<memory>") -> SyntaxResult:
        """Verify Python code syntax via abstract syntax tree parsing."""
        try:
            ast.parse(code, filename=filename)
            return SyntaxResult(is_valid=True, filename=filename)
        except SyntaxError as exc:
            return SyntaxResult(
                is_valid=False,
                filename=filename,
                error_type=type(exc).__name__,
                line_number=exc.lineno,
                column_offset=exc.offset,
                error_message=exc.msg,
            )
        except Exception as exc:
            return SyntaxResult(
                is_valid=False,
                filename=filename,
                error_type=type(exc).__name__,
                line_number=0,
                column_offset=0,
                error_message=str(exc),
            )

    @staticmethod
    def verify_boundary_safety(target_path: str | Path, workspace_root: str | Path) -> SafetyResult:
        """Verify that target file path resides strictly inside workspace root."""
        try:
            target = Path(target_path).resolve()
            root = Path(workspace_root).resolve()
            if target == root or root in target.parents:
                return SafetyResult(is_safe=True, resolved_path=str(target), reason="Path is within workspace boundary")
            return SafetyResult(is_safe=False, resolved_path=str(target), reason=f"Path escapes workspace: {root}")
        except Exception as exc:
            return SafetyResult(is_safe=False, resolved_path=str(target_path), reason=f"Path resolution error: {exc}")

    @staticmethod
    def is_readonly_command(cmd: str) -> bool:
        """Detect whether a shell command is purely diagnostic or read-only."""
        c = cmd.strip()
        pats = (
            r"^(git\s+(status|log|diff|branch|show|rev-parse|tag))\b",
            r"^(pytest|python\s+-m\s+unittest)\b",
            r"^(dir|ls|cat|type|echo|pwd|which|where)\b",
        )
        return any(re.search(p, c, re.IGNORECASE) for p in pats)


# ============================================================================
# 3. Git Shadow Snapshot & Rollback Engine
# ============================================================================

class GitSnapshotEngine:
    """Manages ephemeral shadow references and instant workspace rollbacks."""

    SHADOW_REF = "refs/nexus/shadow-head"

    def __init__(self, workspace_root: str | Path) -> None:
        self.workspace_root = Path(workspace_root).resolve()

    def _run_git(self, args: list[str]) -> tuple[int, str, str]:
        proc = subprocess.run(
            ["git", *args],
            cwd=str(self.workspace_root),
            capture_output=True,
            check=False,
        )
        out = (proc.stdout or b"").decode("utf-8", errors="replace").strip()
        err = (proc.stderr or b"").decode("utf-8", errors="replace").strip()
        return proc.returncode, out, err

    def is_git_repo(self) -> bool:
        if (self.workspace_root / ".git").is_dir():
            return True
        code, out, _ = self._run_git(["rev-parse", "--is-inside-work-tree"])
        return code == 0 and out == "true"

    def ensure_repo_initialized(self) -> bool:
        """Auto-initialize git repository with exclusion rules in <10ms."""
        if self.is_git_repo():
            return True
        code, _, _ = self._run_git(["init"])
        if code == 0:
            ex = self.workspace_root / ".git" / "info" / "exclude"
            if ex.parent.exists():
                ex.write_text(".nexus\n*.sqlite3*\n", encoding="utf-8")
            return True
        return False

    def take_snapshot(self, label: str = "checkpoint") -> SnapshotResult:
        """Capture an instant shadow commit of workspace state without detaching HEAD."""
        if not self.is_git_repo():
            if not self.ensure_repo_initialized():
                return SnapshotResult(success=False, error="Workspace is not a git repository")

        code, _, err = self._run_git(["add", "-A"])
        if code != 0:
            return SnapshotResult(success=False, error=f"git add failed: {err}")

        code, tree_hash, err = self._run_git(["write-tree"])
        if code != 0 or not tree_hash:
            return SnapshotResult(success=False, error=f"git write-tree failed: {err}")

        parent_args: list[str] = []
        code, head_hash, _ = self._run_git(["rev-parse", "HEAD"])
        if code == 0 and head_hash:
            parent_args = ["-p", head_hash]

        msg = f"nexus-shadow: {label}"
        code, commit_hash, err = self._run_git(["commit-tree", tree_hash, *parent_args, "-m", msg])
        if code != 0 or not commit_hash:
            return SnapshotResult(success=False, error=f"git commit-tree failed: {err}")

        self._run_git(["update-ref", self.SHADOW_REF, commit_hash])
        return SnapshotResult(success=True, commit_hash=commit_hash, tree_hash=tree_hash)

    def rollback_to(self, commit_or_tree_hash: str) -> RollbackResult:
        """Physically revert the workspace to the exact specified snapshot."""
        if not self.is_git_repo():
            return RollbackResult(success=False, target_hash=commit_or_tree_hash, error="Not a git repo")

        code, _, err = self._run_git(["checkout", commit_or_tree_hash, "--", "."])
        if code != 0:
            return RollbackResult(success=False, target_hash=commit_or_tree_hash, error=f"git checkout failed: {err}")
        self._run_git(["clean", "-fd"])
        return RollbackResult(success=True, target_hash=commit_or_tree_hash)

    def rollback_latest(self) -> RollbackResult:
        code, head, _ = self._run_git(["rev-parse", self.SHADOW_REF])
        if code != 0 or not head:
            return RollbackResult(success=False, target_hash="NONE", error="No shadow snapshot found")
        return self.rollback_to(head)

    def cleanup_shadows(self) -> bool:
        code, _, _ = self._run_git(["update-ref", "-d", self.SHADOW_REF])
        return code == 0


# ============================================================================
# 4. Attention Ladder & Plan State Engine
# ============================================================================

@dataclass
class AnchorState:
    mission_goal: str = "Default Task"
    current_stage: str = "Phase 1/1"
    active_subtask: str = "Initial Setup"
    checklist: list[dict[str, str]] = field(default_factory=list)
    scope_whitelist: list[str] = field(default_factory=list)
    verification_gate: str = "pytest"
    tier: int = 1
    error_count: int = 0
    last_reconciled_step: int = -1

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AnchorState:
        valid_keys = {f.name for f in cls.__dataclass_fields__.values()}
        return cls(**{k: v for k, v in data.items() if k in valid_keys})


class PlanCompiler:
    """Zero-dependency compiler converting Markdown plans into AnchorState."""

    @staticmethod
    def compile(md_text: str) -> AnchorState:
        goal, checklist, scope, verification = "Task Execution", [], [], "pytest"
        for line in md_text.splitlines():
            s = line.strip()
            if s.startswith("# ") and goal == "Task Execution":
                goal = s.lstrip("# ").strip()
            elif any(s.startswith(p) for p in ("- [", "* [", "1.", "2.", "3.", "4.", "5.", "6.", "7.", "8.", "9.", "###")):
                m = re.match(r"^(?:###|\d+[\.\)]|[\-\*])\s*(?:\[([\s\w/])\])?\s*(.*)", s)
                if m:
                    box, text = (m.group(1) or "").strip().lower(), m.group(2).strip()
                    if text and not text.lower().startswith("verification"):
                        st = "DONE" if box == "x" else ("ACTIVE" if box == "/" else "PENDING")
                        checklist.append({"step": text, "status": st})
            for sc in re.findall(r"\[(?:MODIFY|NEW|DELETE)\]\s+\[(.*?)\]", s):
                scope.append(sc.strip())
            if any(k in s for k in ("pytest", "python -m unittest", "go test", "cargo test")):
                verification = s.strip("` ")

        active_subtask, stage = "Execute Plan", "Phase 1/1"
        if checklist:
            if not any(it["status"] == "ACTIVE" for it in checklist):
                for it in checklist:
                    if it["status"] != "DONE":
                        it["status"] = "ACTIVE"
                        break
            act = [it["step"] for it in checklist if it["status"] == "ACTIVE"]
            done_cnt = sum(1 for it in checklist if it["status"] == "DONE")
            if act:
                active_subtask, stage = act[0], f"Phase {done_cnt + 1}/{len(checklist)}"
            elif done_cnt == len(checklist):
                active_subtask, stage = "Mission Complete", "Finished"
            else:
                active_subtask = checklist[0]["step"]
        else:
            checklist = [{"step": "Execute Plan", "status": "ACTIVE"}]

        tier = 0 if (stage == "Finished" and active_subtask == "Mission Complete") else 1
        return AnchorState(
            mission_goal=goal,
            current_stage=stage,
            active_subtask=active_subtask,
            checklist=checklist,
            scope_whitelist=scope,
            verification_gate=verification,
            tier=tier,
        )


class AttentionLadder:
    """Renders tiered attention HUD based on current system health."""

    @staticmethod
    def render(state: AnchorState) -> str:
        if state.tier == 0 or (state.current_stage == "Finished" and state.active_subtask == "Mission Complete" and state.tier <= 2):
            return ""
        done = sum(1 for i in state.checklist if i.get("status") == "DONE")
        progress = int((done / max(1, len(state.checklist))) * 100)

        if state.tier == 1:
            return f"[NEXUS_HUD:T1] GOAL: {state.mission_goal} | STAGE: {state.current_stage} | ACTIVE: {state.active_subtask} | PROGRESS: {progress}%"
        elif state.tier == 2:
            lines = [f"=== [NEXUS_FOCUS_CHAIN:T2] ===", f"MISSION: {state.mission_goal} (Progress: {progress}%)", "CHECKLIST:"]
            for item in state.checklist:
                m = "[x]" if item.get("status") == "DONE" else ("[>]" if item.get("status") == "ACTIVE" else "[ ]")
                lines.append(f"  {m} {item.get('step', '')}")
            lines.append("==============================")
            return "\n".join(lines)
        elif state.tier == 3:
            return (
                f"*** [NEXUS_STICKY_LOCK:T3 (PHYSICAL GATE ARMED)] ***\n"
                f"WARNING: Friction detected (Errors: {state.error_count}).\n"
                f"LOCKED TARGET: {state.active_subtask}\n"
                f"SCOPE ALLOWED: {', '.join(state.scope_whitelist) or 'All'}\n"
                f"EXIT CRITERIA: {state.verification_gate}\n"
                f"*** Movement restricted until physical verification passes ***"
            )
        return json.dumps({
            "nexus_pipeline_handoff": {
                "mission_goal": state.mission_goal,
                "progress": f"{progress}%",
                "completed": [i["step"] for i in state.checklist if i.get("status") == "DONE"],
                "active_subtask": state.active_subtask,
            }
        }, indent=2)


class AnchorManager:
    """Manages persistence, physical gating, and dynamic escalation of AnchorState."""

    def __init__(self, state_file: Optional[Path] = None, data_dir: Optional[Path] = None, target_path: Optional[str | Path] = None):
        self.data_dir = Path(data_dir or DEFAULT_DATA_DIR).resolve()
        self.data_dir.mkdir(parents=True, exist_ok=True)

        if state_file:
            self.state_file, self.is_governed = Path(state_file).resolve(), True
        else:
            base_dir = Path.cwd().resolve()
            if target_path:
                try:
                    tp = Path(target_path).resolve()
                    if not (tp == base_dir or str(tp).startswith(str(base_dir))):
                        self.state_file, self.is_governed = self.data_dir / "anchor_state.json", False
                        return
                except Exception:
                    pass
            ws_nexus = self.data_dir / "anchor_state.json"
            self.is_governed = ws_nexus.is_file() or self.data_dir.is_dir()
            self.state_file = ws_nexus

    def load(self) -> AnchorState:
        if self.state_file.exists():
            try:
                return AnchorState.from_dict(json.loads(self.state_file.read_text(encoding="utf-8")))
            except Exception:
                pass
        return AnchorState(tier=0 if not self.is_governed else 1)

    def save(self, state: AnchorState) -> None:
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.state_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(state.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self.state_file)

    def sync_if_plan_updated(self, plan_paths: Optional[list[Path]] = None) -> bool:
        if not self.is_governed:
            return False
        for p in (plan_paths or [Path.cwd() / "implementation_plan.md", self.data_dir / "implementation_plan.md"]):
            if p.is_file():
                try:
                    if p.stat().st_mtime > (self.state_file.stat().st_mtime if self.state_file.exists() else 0):
                        self.save(PlanCompiler.compile(p.read_text(encoding="utf-8")))
                        return True
                except Exception:
                    pass
        return False

    def inspect_action(self, tool_name: str, target: str) -> Optional[dict[str, str]]:
        if not self.is_governed:
            return None
        st = self.load()
        if st.tier == 3 and st.scope_whitelist and target:
            tnorm = str(target).replace("\\", "/").lower()
            if not any(w.lower() in tnorm or tnorm.endswith(w.lower()) for w in st.scope_whitelist):
                return {
                    "decision": "deny",
                    "reason": f"[NEXUS_ANCHOR: T3_LOCKED] Modification of '{target}' blocked. Out of Plan scope whitelist ({st.scope_whitelist}).",
                }
        return None

    def record_physical_fact(self, success: bool, exit_code: int = 0, is_verification: bool = True) -> tuple[int, str]:
        st = self.load()
        if success and exit_code == 0:
            st.error_count = 0
            if st.tier == 3:
                st.tier = 2
            if is_verification:
                for i, it in enumerate(st.checklist):
                    if it.get("status") == "ACTIVE":
                        it["status"] = "DONE"
                        if i + 1 < len(st.checklist):
                            st.checklist[i + 1]["status"] = "ACTIVE"
                            st.active_subtask = st.checklist[i + 1]["step"]
                            st.current_stage = f"Phase {i + 2}/{len(st.checklist)}"
                        else:
                            st.active_subtask = "Mission Complete"
                            st.current_stage = "Finished"
                            st.tier = 0
                        break
        else:
            st.error_count += 1
            if st.error_count >= 2 and st.tier < 3:
                st.tier = 3
        self.save(st)
        return st.tier, AttentionLadder.render(st)


# ============================================================================
# 5. Nexus Gate Orchestrator
# ============================================================================

class NexusGate:
    """Unified gatekeeper coordinating AST checking, snapshots, and ladder state."""

    MUTATING_TOOLS = ("write_to_file", "replace_file_content", "multi_replace_file_content", "run_command", "nexus_patch_chunk")
    READONLY_TOOLS = ("view_file", "grep_search", "find_by_name", "read_url_content", "shelf_search", "vault_search", "call_mcp_tool", "search_web", "list_dir")

    def __init__(self, workspace_root: Optional[str | Path] = None, data_dir: Optional[str | Path] = None):
        self.workspace_root = Path(workspace_root or Path.cwd()).resolve()
        self.data_dir = Path(data_dir or DEFAULT_DATA_DIR).resolve()
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.snapshot_engine = GitSnapshotEngine(self.workspace_root)
        self.anchor_manager = AnchorManager(state_file=self.data_dir / "anchor_state.json", data_dir=self.data_dir)

    def evaluate_pre_tool(self, tool_name: str, args: dict[str, Any]) -> dict[str, Any]:
        """Pre-tool evaluation: AST syntax check, danger command check, shadow snapshot."""
        target = args.get("TargetFile") or args.get("path") or args.get("file")
        code = args.get("CodeContent") or args.get("ReplacementContent") or args.get("content")

        # 1. Anchor scope check
        if target:
            anchor_decision = self.anchor_manager.inspect_action(tool_name, str(target))
            if anchor_decision:
                return anchor_decision

        # 2. Dangerous command block
        if tool_name == "run_command":
            cmd = str(args.get("CommandLine") or args.get("command") or "")
            for pat in (r"\brm\s+-[rf]{1,2}\s+[/*]", r"\bmkfs\b", r"\bdd\s+if=", r"\bformat\s+[a-z]:", r"\bgit\s+clean\s+-[fdx]{2,}\b"):
                if re.search(pat, cmd, re.IGNORECASE):
                    return {"decision": "deny", "reason": f"[COMMAND_DENIED] Dangerous command pattern '{pat}' blocked."}

        # 3. Static AST syntax verification on Python mutations
        if tool_name == "write_to_file" and target and str(target).endswith(".py") and isinstance(code, str):
            res = GroundTruthVerifier.verify_syntax(code, filename=str(target))
            if not res.is_valid:
                self.anchor_manager.record_physical_fact(success=False)
                return {"decision": "deny", "reason": f"[JIT_CAPSULE: SYNTAX_ERROR] {res.format_diagnostic()}"}

        # 4. Ephemeral Git shadow snapshot for mutating actions
        is_mutating = tool_name in self.MUTATING_TOOLS
        if tool_name == "run_command":
            cmd = str(args.get("CommandLine") or args.get("command") or "")
            if GroundTruthVerifier.is_readonly_command(cmd):
                is_mutating = False

        if is_mutating:
            self.snapshot_engine.take_snapshot(label=f"pre_{tool_name}")

        return {"decision": "allow"}

    def evaluate_post_tool(self, tool_name: str, args: dict[str, Any], exit_code: int = 0, is_error: bool = False) -> dict[str, Any]:
        """Post-tool evaluation: ladder advancement, read-only immunity, catastrophic rollback."""
        if tool_name in self.READONLY_TOOLS:
            return {"decision": "allow"}

        target = args.get("TargetFile") or args.get("path") or args.get("file")
        if target and str(target).lower().endswith("implementation_plan.md"):
            self.anchor_manager.sync_if_plan_updated([Path(str(target))])

        if is_error or exit_code != 0:
            self.anchor_manager.record_physical_fact(success=False, exit_code=exit_code or 1)
            if exit_code in (134, 139, -9):
                self.snapshot_engine.rollback_latest()
        else:
            cmd = str(args).lower()
            is_verif = (tool_name == "run_command" and any(k in cmd for k in ("pytest", "unittest", "go test", "cargo test")))
            self.anchor_manager.record_physical_fact(success=True, exit_code=0, is_verification=is_verif)

        return {"decision": "allow"}

    def evaluate_pre_invocation(self) -> str:
        """Render live Attention HUD text for prompt injection (Tier 0 is completely silent)."""
        if self.anchor_manager.is_governed:
            self.anchor_manager.sync_if_plan_updated()
            return AttentionLadder.render(self.anchor_manager.load())
        return ""


if __name__ == "__main__":
    import tempfile
    print("Testing Nexus Gate...")
    with tempfile.TemporaryDirectory() as tmp:
        gate = NexusGate(workspace_root=tmp, data_dir=Path(tmp) / "data")
        # Test 1: Syntax verification
        valid_res = GroundTruthVerifier.verify_syntax("def hello(): return 42\n")
        assert valid_res.is_valid
        invalid_res = GroundTruthVerifier.verify_syntax("def error(\n")
        assert not invalid_res.is_valid

        # Test 2: Plan compiler
        md = "# Demo\n1. [x] Step 1\n2. [ ] Step 2\n"
        st = PlanCompiler.compile(md)
        assert st.checklist[0]["status"] == "DONE"
        assert st.checklist[1]["status"] == "ACTIVE"

        print("Nexus Gate tests passed successfully.")
