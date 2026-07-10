import tempfile
import unittest
from pathlib import Path

from server.runtime_preflight import (
    RuntimePreflightError,
    migrate_runtime_config,
    redact_sensitive_text,
    run_runtime_preflight,
)


class RuntimePreflightTest(unittest.TestCase):
    def test_migrates_legacy_var_lib_dedup_path_to_runtime_data_dir(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            config_path = root / "config.json"
            config_path.write_text("{}", encoding="utf-8")
            config = {
                "storage": {"directory": str(root / "data")},
                "mgtv": {"dedup_db_path": "/var/lib/mgtv-danmaku/data/fingerprints.sqlite3"},
            }

            result = migrate_runtime_config(config, config_path=config_path, repo_root=root / "repo")

            self.assertTrue(result.changed)
            self.assertEqual(result.config["mgtv"]["dedup_db_path"], str(root / "data" / "fingerprints.sqlite3"))
            self.assertIn("迁移", result.warnings[0])

    def test_keeps_custom_writable_dedup_path(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            custom = root / "custom" / "dedup.sqlite3"
            config = {
                "storage": {"directory": str(root / "data")},
                "mgtv": {"dedup_db_path": str(custom)},
            }

            result = migrate_runtime_config(config, config_path=root / "config.json", repo_root=root / "repo")

            self.assertFalse(result.changed)
            self.assertEqual(result.config["mgtv"]["dedup_db_path"], str(custom))

    def test_preflight_rejects_unwritable_custom_dedup_parent(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            blocking_file = root / "not-a-directory"
            blocking_file.write_text("block", encoding="utf-8")
            config = {
                "storage": {"directory": str(root / "data")},
                "recording": {"directory": str(root / "recordings")},
                "mgtv": {"dedup_db_path": str(blocking_file / "dedup.sqlite3")},
            }

            with self.assertRaisesRegex(RuntimePreflightError, "弹幕去重 SQLite 目录"):
                run_runtime_preflight(config, config_path=root / "config.json", repo_root=root / "repo")

    def test_redacts_lark_websocket_sensitive_query_fields(self):
        raw = (
            "wss://user:password@example.test/ws?access_key=ak-123&ticket=t-456&session=s-789&ok=1 "
            "Cookie: abc token=secret github_pat_abcdefghijklmnopqrstuvwxyz123456"
        )
        redacted = redact_sensitive_text(raw)

        self.assertNotIn("ak-123", redacted)
        self.assertNotIn("t-456", redacted)
        self.assertNotIn("s-789", redacted)
        self.assertNotIn("secret", redacted)
        self.assertNotIn("password", redacted)
        self.assertNotIn("abcdefghijklmnopqrstuvwxyz", redacted)
        self.assertIn("ok=1", redacted)


if __name__ == "__main__":
    unittest.main()
