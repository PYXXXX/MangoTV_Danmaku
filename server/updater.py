"""Git-backed online update helpers for the operator Web UI."""

from __future__ import annotations

import asyncio
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class UpdateError(RuntimeError):
    """Raised when a version check or online update cannot be completed safely."""


@dataclass(frozen=True)
class GitCommandResult:
    returncode: int
    stdout: str
    stderr: str

    @property
    def combined_output(self) -> str:
        return "\n".join(part.strip() for part in (self.stdout, self.stderr) if part.strip())


class GitUpdater:
    """Checks and applies fast-forward updates from a configured git remote."""

    def __init__(
        self,
        repo_root: Path,
        *,
        remote: str = "origin",
        branch: str = "",
        install_dependencies: bool = True,
        requirements_file: str = "requirements-server.txt",
    ):
        self.repo_root = Path(repo_root)
        self.remote = remote or "origin"
        self.branch = branch
        self.install_dependencies = install_dependencies
        self.requirements_file = requirements_file

    async def _run(
        self,
        command: list[str],
        *,
        cwd: Path | None = None,
        timeout: float = 30,
        check: bool = True,
    ) -> GitCommandResult:
        try:
            process = await asyncio.create_subprocess_exec(
                *command,
                cwd=str(cwd or self.repo_root),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except FileNotFoundError as exc:
            raise UpdateError(f"命令不存在：{command[0]}") from exc

        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(process.communicate(), timeout=timeout)
        except asyncio.TimeoutError as exc:
            process.kill()
            await process.communicate()
            raise UpdateError(f"命令超时：{' '.join(command)}") from exc

        result = GitCommandResult(
            process.returncode,
            stdout_bytes.decode("utf-8", errors="replace"),
            stderr_bytes.decode("utf-8", errors="replace"),
        )
        if check and result.returncode != 0:
            message = result.combined_output or f"退出码 {result.returncode}"
            raise UpdateError(f"命令执行失败：{' '.join(command)}\n{message}")
        return result

    async def _git(self, args: list[str], *, timeout: float = 30, check: bool = True) -> GitCommandResult:
        return await self._run(["git", *args], timeout=timeout, check=check)

    async def _inside_work_tree(self) -> bool:
        result = await self._git(["rev-parse", "--is-inside-work-tree"], check=False)
        return result.returncode == 0 and result.stdout.strip() == "true"

    async def _current_branch(self) -> str:
        result = await self._git(["rev-parse", "--abbrev-ref", "HEAD"])
        return result.stdout.strip()

    async def _target_remote_branch(self) -> tuple[str, str]:
        if self.branch:
            return self.remote, self.branch

        upstream = await self._git(
            ["rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"],
            check=False,
        )
        if upstream.returncode == 0 and "/" in upstream.stdout.strip():
            remote, branch = upstream.stdout.strip().split("/", 1)
            return remote or self.remote, branch

        branch = await self._current_branch()
        if branch == "HEAD":
            branch = "main"
        return self.remote, branch

    async def _remote_url(self, remote: str) -> str:
        result = await self._git(["remote", "get-url", remote], check=False)
        return result.stdout.strip() if result.returncode == 0 else ""

    async def _remote_sha(self, remote: str, branch: str) -> str:
        result = await self._git(["ls-remote", remote, f"refs/heads/{branch}"], timeout=30)
        first = result.stdout.strip().splitlines()[0] if result.stdout.strip() else ""
        return first.split()[0] if first else ""

    async def _dirty_status(self) -> str:
        result = await self._git(["status", "--porcelain"])
        return result.stdout.strip()

    async def status(self) -> dict[str, Any]:
        if not await self._inside_work_tree():
            raise UpdateError(f"{self.repo_root} 不是 git 工作区，无法在线检测版本")

        current_sha = (await self._git(["rev-parse", "HEAD"])).stdout.strip()
        current_short = (await self._git(["rev-parse", "--short", "HEAD"])).stdout.strip()
        branch = await self._current_branch()
        remote, target_branch = await self._target_remote_branch()
        remote_url = await self._remote_url(remote)
        dirty = bool(await self._dirty_status())
        remote_sha = await self._remote_sha(remote, target_branch)

        return {
            "ok": True,
            "repoRoot": str(self.repo_root),
            "currentSha": current_sha,
            "currentShort": current_short,
            "branch": branch,
            "remote": remote,
            "remoteBranch": target_branch,
            "remoteUrl": remote_url,
            "remoteSha": remote_sha,
            "remoteShort": remote_sha[:12] if remote_sha else "",
            "dirty": dirty,
            "updateAvailable": bool(remote_sha and remote_sha != current_sha),
            "requirementsFile": self.requirements_file,
            "installDependencies": self.install_dependencies,
        }

    async def apply_update(self) -> dict[str, Any]:
        before = await self.status()
        if before["dirty"]:
            raise UpdateError("工作区存在未提交或未跟踪文件，已拒绝自动升级。请先清理部署目录。")
        if not before["remoteSha"]:
            raise UpdateError("没有读取到远端分支 commit，无法升级。")
        if not before["updateAvailable"]:
            return {"ok": True, "updated": False, "status": before, "steps": ["当前已经是远端最新 commit。"]}

        remote = before["remote"]
        branch = before["remoteBranch"]
        steps: list[str] = []

        await self._git(["fetch", "--prune", remote, branch], timeout=90)
        fetched_sha = (await self._git(["rev-parse", "FETCH_HEAD"])).stdout.strip()
        ancestor = await self._git(["merge-base", "--is-ancestor", "HEAD", "FETCH_HEAD"], check=False)
        if ancestor.returncode != 0:
            raise UpdateError("当前部署不能快进到远端 commit，已拒绝自动合并。请人工检查是否存在分叉。")

        await self._git(["merge", "--ff-only", "--no-stat", "FETCH_HEAD"], timeout=90)
        steps.append(f"代码已快进到 {fetched_sha[:12]}。")

        requirements = self.repo_root / self.requirements_file
        if self.install_dependencies and requirements.exists():
            await self._run(
                [sys.executable, "-m", "pip", "install", "-r", str(requirements)],
                timeout=180,
            )
            steps.append(f"依赖已按 {self.requirements_file} 更新。")

        after = await self.status()
        return {
            "ok": True,
            "updated": True,
            "from": before["currentSha"],
            "to": after["currentSha"],
            "status": after,
            "steps": steps,
        }
