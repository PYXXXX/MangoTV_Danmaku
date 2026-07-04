import asyncio
import subprocess
import tempfile
import unittest
from pathlib import Path

from server.updater import GitUpdater, UpdateError


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

            result = asyncio.run(updater.apply_update())
            self.assertTrue(result["updated"])
            self.assertEqual(result["to"], next_sha)
            self.assertEqual((deploy / "app.txt").read_text(encoding="utf-8"), "v2\n")
            self.assertFalse(asyncio.run(updater.status())["updateAvailable"])

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
