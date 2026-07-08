import asyncio
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from server.updater import GitUpdater, UpdateError, parse_transfer_progress


def run(command: list[str], cwd: Path | None = None) -> str:
    result = subprocess.run(
        command,
        cwd=str(cwd) if cwd else None,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return result.stdout.strip()


def configure_identity(repo: Path) -> None:
    run(["git", "config", "user.email", "codex@example.com"], repo)
    run(["git", "config", "user.name", "Codex Test"], repo)


def commit_file(repo: Path, filename: str, body: str, message: str) -> str:
    path = repo / filename
    path.write_text(body, encoding="utf-8")
    run(["git", "add", filename], repo)
    run(["git", "commit", "-m", message], repo)
    return run(["git", "rev-parse", "HEAD"], repo)


def make_remote_and_clone(root: Path) -> tuple[Path, Path, Path]:
    remote = root / "remote.git"
    source = root / "source"
    deploy = root / "deploy"
    run(["git", "init", "--bare", str(remote)])
    run(["git", "clone", str(remote), str(source)])
    configure_identity(source)
    run(["git", "checkout", "-b", "main"], source)
    commit_file(source, "app.txt", "v1\n", "initial")
    run(["git", "push", "-u", "origin", "main"], source)
    run(["git", "--git-dir", str(remote), "symbolic-ref", "HEAD", "refs/heads/main"])
    run(["git", "clone", str(remote), str(deploy)])
    configure_identity(deploy)
    return remote, source, deploy


class GitUpdaterTest(unittest.TestCase):
    def test_parse_transfer_progress_reads_percent_and_speed(self):
        parsed = parse_transfer_progress("Receiving objects: 42% (42/100), 1.23 MiB | 4.56 MiB/s")
        self.assertEqual(parsed["rawPercent"], 42)
        self.assertEqual(parsed["speed"], "4.56 MiB/s")
        self.assertIn("Receiving objects", parsed["detail"])

    def test_detects_and_applies_fast_forward_update(self):
        with tempfile.TemporaryDirectory() as temp:
            _, source, deploy = make_remote_and_clone(Path(temp))
            next_sha = commit_file(source, "app.txt", "v2\n", "second")
            run(["git", "push"], source)

            updater = GitUpdater(deploy, install_dependencies=False)
            status = asyncio.run(updater.status())
            self.assertTrue(status["updateAvailable"])
            self.assertEqual(status["remoteSha"], next_sha)
            self.assertFalse(status["dirty"])

            progress_events = []
            result = asyncio.run(updater.apply_update(progress_events.append))
            self.assertTrue(result["updated"])
            self.assertEqual(result["to"], next_sha)
            self.assertEqual((deploy / "app.txt").read_text(encoding="utf-8"), "v2\n")
            self.assertFalse(asyncio.run(updater.status())["updateAvailable"])
            stages = [event.get("stage") for event in progress_events]
            self.assertIn("fetch", stages)
            self.assertIn("merge", stages)
            self.assertTrue(any(event.get("percent", 0) >= 78 for event in progress_events))

    def test_frontend_source_change_runs_build_without_ci(self):
        with tempfile.TemporaryDirectory() as temp:
            temp_root = Path(temp)
            _, source, deploy = make_remote_and_clone(temp_root)
            frontend = source / "frontend"
            frontend.mkdir()
            (frontend / "package.json").write_text('{"scripts":{"build":"vite build"}}\n', encoding="utf-8")
            (frontend / "package-lock.json").write_text('{"lockfileVersion":3}\n', encoding="utf-8")
            (frontend / "src").mkdir()
            commit_file(source, "frontend/src/app.ts", "v1\n", "frontend initial")
            run(["git", "push"], source)
            run(["git", "pull", "--ff-only"], deploy)

            commit_file(source, "frontend/src/app.ts", "v2\n", "frontend source update")
            run(["git", "push"], source)

            bin_dir = temp_root / "bin"
            bin_dir.mkdir()
            log_path = temp_root / "npm.log"
            npm = bin_dir / "npm"
            npm.write_text(
                "#!/usr/bin/env python3\n"
                "import os, pathlib, sys\n"
                f"pathlib.Path({str(log_path)!r}).write_text(' '.join(sys.argv[1:]) + '\\n', encoding='utf-8')\n",
                encoding="utf-8",
            )
            npm.chmod(0o755)
            old_path = os.environ.get("PATH", "")
            os.environ["PATH"] = f"{bin_dir}{os.pathsep}{old_path}"
            try:
                updater = GitUpdater(deploy, install_dependencies=False, build_frontend=True)
                result = asyncio.run(updater.apply_update())
            finally:
                os.environ["PATH"] = old_path

            self.assertTrue(result["updated"])
            self.assertIn("新版前端已构建", "\n".join(result["steps"]))
            self.assertEqual(log_path.read_text(encoding="utf-8").strip(), "--prefix frontend run build")

    def test_frontend_dependency_change_runs_ci_then_build(self):
        with tempfile.TemporaryDirectory() as temp:
            temp_root = Path(temp)
            _, source, deploy = make_remote_and_clone(temp_root)
            frontend = source / "frontend"
            frontend.mkdir()
            (frontend / "package.json").write_text('{"scripts":{"build":"vite build"},"dependencies":{"a":"1.0.0"}}\n', encoding="utf-8")
            (frontend / "package-lock.json").write_text('{"lockfileVersion":3}\n', encoding="utf-8")
            (frontend / "src").mkdir()
            commit_file(source, "frontend/src/app.ts", "v1\n", "frontend initial")
            run(["git", "add", "frontend/package.json", "frontend/package-lock.json"], source)
            run(["git", "commit", "-m", "frontend deps"], source)
            run(["git", "push"], source)
            run(["git", "pull", "--ff-only"], deploy)

            (source / "frontend" / "package.json").write_text('{"scripts":{"build":"vite build"},"dependencies":{"a":"1.0.1"}}\n', encoding="utf-8")
            run(["git", "add", "frontend/package.json"], source)
            run(["git", "commit", "-m", "frontend dep update"], source)
            run(["git", "push"], source)

            bin_dir = temp_root / "bin"
            bin_dir.mkdir()
            log_path = temp_root / "npm.log"
            npm = bin_dir / "npm"
            npm.write_text(
                "#!/usr/bin/env python3\n"
                "import pathlib, sys\n"
                f"with pathlib.Path({str(log_path)!r}).open('a', encoding='utf-8') as handle: handle.write(' '.join(sys.argv[1:]) + '\\n')\n",
                encoding="utf-8",
            )
            npm.chmod(0o755)
            old_path = os.environ.get("PATH", "")
            os.environ["PATH"] = f"{bin_dir}{os.pathsep}{old_path}"
            try:
                updater = GitUpdater(deploy, install_dependencies=False, build_frontend=True)
                result = asyncio.run(updater.apply_update())
            finally:
                os.environ["PATH"] = old_path

            self.assertTrue(result["updated"])
            self.assertEqual(
                log_path.read_text(encoding="utf-8").splitlines(),
                ["--prefix frontend ci", "--prefix frontend run build"],
            )

    def test_dirty_worktree_rejects_auto_update(self):
        with tempfile.TemporaryDirectory() as temp:
            _, source, deploy = make_remote_and_clone(Path(temp))
            commit_file(source, "app.txt", "v2\n", "second")
            run(["git", "push"], source)
            (deploy / "local.tmp").write_text("local\n", encoding="utf-8")

            updater = GitUpdater(deploy, install_dependencies=False)
            with self.assertRaisesRegex(UpdateError, "工作区存在"):
                asyncio.run(updater.apply_update())

    def test_not_a_git_repo_reports_clear_error(self):
        with tempfile.TemporaryDirectory() as temp:
            updater = GitUpdater(Path(temp), install_dependencies=False)
            with self.assertRaisesRegex(UpdateError, "不是 git 工作区"):
                asyncio.run(updater.status())


if __name__ == "__main__":
    unittest.main()
