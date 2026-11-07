"""Web 自动化测试中心（E1）.

把 ``run_tests.py``（``core.testing.TestRunner`` + YAML 脚本）搬到浏览器：

- 列出 ``tests/scripts/*.yaml``（名称/描述/角色/步骤数）；
- 在**独立子进程**中顺序运行选中的脚本（避免与 Web 会话争 2404 端口、
  也避免测试里的异常拖垮 Web 进程）；
- 实时收集 stdout（``python -u``），供前端轮询展示；
- 报告落在 ``data/test_reports/<run_id>/``，可在线下载 HTML/JSON/TXT；
- 同一时间只允许一个 run，可停止。
"""

from __future__ import annotations

import asyncio
import os
import re
import sys
import time
import uuid
from collections import deque
from collections.abc import Callable
from pathlib import Path

from core.testing import ScriptLoader

ROOT = Path(__file__).resolve().parent.parent
_RUN_ID = re.compile(r"^[A-Za-z0-9_-]+$")
_REPORT_SUFFIXES = {".html", ".json", ".txt"}


class TestCenterService:
    def __init__(
        self,
        scripts_dir: str | Path | None = None,
        reports_dir: str | Path | None = None,
        runner_cmd: list[str] | None = None,
    ) -> None:
        self.scripts_dir = Path(scripts_dir or ROOT / "tests" / "scripts").resolve()
        self.reports_dir = Path(reports_dir or ROOT / "data" / "test_reports").resolve()
        self.reports_dir.mkdir(parents=True, exist_ok=True)
        if runner_cmd is not None:
            self._runner_cmd = runner_cmd
        elif getattr(sys, "frozen", False):
            # 打包版没有独立 Python：用同一个 exe 的 --test 模式跑脚本
            self._runner_cmd = [sys.executable, "--no-history", "--test"]
        else:
            self._runner_cmd = [sys.executable, "-u", str(ROOT / "run_tests.py")]
        self._run: dict | None = None
        self._task: asyncio.Task | None = None
        self._proc: asyncio.subprocess.Process | None = None
        self._stop_requested = False
        self._publish: Callable[[str, dict], None] = lambda kind, data: None

    def set_publisher(self, publish: Callable[[str, dict], None]) -> None:
        self._publish = publish

    # ── 脚本列表 ─────────────────────────────────────────────────

    def list_scripts(self) -> list[dict]:
        rows: list[dict] = []
        if not self.scripts_dir.is_dir():
            return rows
        for path in sorted(self.scripts_dir.glob("*.y*ml")):
            try:
                script = ScriptLoader.load(path)
            except Exception as e:  # noqa: BLE001 — 单个坏脚本不拖垮列表
                rows.append({
                    "id": path.name, "name": path.stem, "description": "",
                    "role": "?", "steps": 0, "error": str(e),
                })
                continue
            rows.append({
                "id": path.name,
                "name": script.name or path.stem,
                "description": script.description,
                "role": script.role,
                "steps": len(script.steps),
                "tags": script.tags,
                "timeout": script.timeout,
            })
        return rows

    def _resolve_scripts(self, names: list[str]) -> tuple[list[Path], str | None]:
        if not names:
            return [], "请至少选择一个脚本"
        paths: list[Path] = []
        for name in names:
            if not isinstance(name, str) or Path(name).name != name:
                return [], f"非法脚本名: {name!r}"
            path = (self.scripts_dir / name).resolve()
            if path.parent != self.scripts_dir or not path.is_file():
                return [], f"脚本不存在: {name}"
            if path.suffix.lower() not in (".yaml", ".yml"):
                return [], f"仅支持 YAML 脚本: {name}"
            paths.append(path)
        return paths, None

    # ── 运行 ─────────────────────────────────────────────────────

    @property
    def running(self) -> bool:
        return bool(self._run and self._run["status"] == "running")

    def status(self) -> dict:
        if self._run is None:
            return {"ok": True, "running": False, "run": None}
        run = dict(self._run)
        run["lines"] = list(self._run["lines"])[-500:]
        run["reports"] = self._list_reports(self._run["id"])
        return {"ok": True, "running": self.running, "run": run}

    def _new_run(self, names: list[str], paths: list[Path]) -> dict:
        run_id = time.strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6]
        run_dir = self.reports_dir / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        return {
            "id": run_id,
            "status": "running",
            "scripts": list(names),
            "started_at": time.time(),
            "ended_at": None,
            "returncode": None,
            "summary": None,
            "lines": deque(maxlen=4000),
            "results": [],
            "dir": str(run_dir),
        }

    def start(self, names: list[str]) -> dict:
        if self.running:
            return {"ok": False, "error": "已有测试在运行"}
        paths, err = self._resolve_scripts(names)
        if err:
            return {"ok": False, "error": err}
        self._run = self._new_run(names, paths)
        self._stop_requested = False
        self._task = asyncio.create_task(self._execute(paths))
        return {"ok": True, "run": self.status()["run"]}

    def stop(self) -> dict:
        if not self.running:
            return {"ok": False, "error": "没有正在运行的测试"}
        self._stop_requested = True
        proc = self._proc
        if proc is not None and proc.returncode is None:
            try:
                proc.terminate()
            except ProcessLookupError:
                pass
        return {"ok": True}

    async def _execute(self, paths: list[Path]) -> None:
        run = self._run
        assert run is not None
        try:
            for path in paths:
                if self._stop_requested:
                    break
                self._append(f"▶ {path.name}")
                code = await self._run_one(path, run["dir"])
                run["results"].append({"script": path.name, "returncode": code})
                if code != 0 and not self._stop_requested:
                    # 测试失败不中断后续脚本：与 run_tests.py 逐个跑目录的语义一致
                    pass
            if self._stop_requested:
                run["status"] = "stopped"
            elif all(r["returncode"] == 0 for r in run["results"]) and run["results"]:
                run["status"] = "passed"
            else:
                run["status"] = "failed"
        except Exception as e:  # noqa: BLE001
            run["status"] = "error"
            self._append(f"运行器异常: {e}")
        finally:
            run["ended_at"] = time.time()
            run["returncode"] = 0 if run["status"] == "passed" else 1
            self._parse_summary(run)
            self._publish("tests.done", {"run_id": run["id"], "status": run["status"]})
            self._proc = None
            self._task = None

    async def _run_one(self, path: Path, report_dir: str) -> int:
        env = dict(os.environ)
        env["PYTHONUNBUFFERED"] = "1"
        cmd = [*self._runner_cmd, str(path), "--report-dir", report_dir]
        self._proc = await asyncio.create_subprocess_exec(
            *cmd, cwd=str(ROOT), env=env,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
        )
        assert self._proc.stdout is not None
        while True:
            line = await self._proc.stdout.readline()
            if not line:
                break
            self._append(line.decode("utf-8", errors="replace").rstrip())
        code = await self._proc.wait()
        self._append(f"退出码 {code}")
        return code

    def _append(self, line: str) -> None:
        if self._run is None:
            return
        self._run["lines"].append(line)
        self._publish("tests.log", {"run_id": self._run["id"], "line": line})

    @staticmethod
    def _parse_summary(run: dict) -> None:
        text = "\n".join(run["lines"])
        match = re.search(
            r"Summary:\s*(\d+)\s*scripts,\s*(\d+)\s*passed,\s*(\d+)\s*failed", text)
        if match:
            run["summary"] = {
                "scripts": int(match.group(1)),
                "passed": int(match.group(2)),
                "failed": int(match.group(3)),
            }

    # ── 报告 ─────────────────────────────────────────────────────

    def _run_dir(self, run_id: str) -> Path | None:
        if not _RUN_ID.match(run_id):
            return None
        path = (self.reports_dir / run_id).resolve()
        if path.parent != self.reports_dir:
            return None
        return path

    def _list_reports(self, run_id: str) -> list[dict]:
        run_dir = self._run_dir(run_id)
        if run_dir is None or not run_dir.is_dir():
            return []
        return [
            {"name": p.name, "format": p.suffix.lstrip("."), "size": p.stat().st_size}
            for p in sorted(run_dir.iterdir())
            if p.is_file() and p.suffix.lower() in _REPORT_SUFFIXES
        ]

    def report_path(self, run_id: str, name: str) -> Path | None:
        run_dir = self._run_dir(run_id)
        if run_dir is None or Path(name).name != name:
            return None
        if Path(name).suffix.lower() not in _REPORT_SUFFIXES:
            return None
        path = run_dir / name
        return path if path.is_file() else None

    async def shutdown(self) -> None:
        if self.running:
            self._stop_requested = True
            proc = self._proc
            if proc is not None and proc.returncode is None:
                try:
                    proc.terminate()
                except ProcessLookupError:
                    pass
            if self._task is not None:
                try:
                    await asyncio.wait_for(self._task, timeout=5)
                except (asyncio.TimeoutError, asyncio.CancelledError):
                    if proc is not None and proc.returncode is None:
                        proc.kill()
