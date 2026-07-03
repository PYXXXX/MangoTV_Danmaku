import tempfile
import unittest
from pathlib import Path

from tools.setup_feishu_bot import Wizard, configure_feishu, format_id_list, load_config, parse_id_list, save_config


class SetupFeishuBotTest(unittest.TestCase):
    def test_parse_id_list_accepts_commas_and_whitespace(self):
        self.assertEqual(parse_id_list("ou_1, ou_2，ou_3\nou_4"), ["ou_1", "ou_2", "ou_3", "ou_4"])
        self.assertEqual(parse_id_list("*"), ["*"])
        self.assertEqual(parse_id_list(""), [])

    def test_format_id_list_filters_example_placeholders(self):
        self.assertEqual(format_id_list(["ou_xxx", "oc_xxx"]), "")
        self.assertEqual(format_id_list(["*", "ou_real"]), "*, ou_real")

    def test_configure_temporary_whitelist(self):
        answers = iter([
            "",  # enable
            "",  # websocket
            "cli_real",
            "https://example.com/results",
            "",  # temporary whitelist
        ])
        secrets = iter(["secret_real"])
        output: list[str] = []
        wizard = Wizard(lambda prompt: next(answers), lambda prompt: next(secrets), output.append)
        config, strategy = configure_feishu({"listen": {}, "feishu": {"enabled": False}}, wizard)
        self.assertEqual(strategy, "temporary")
        self.assertTrue(config["feishu"]["enabled"])
        self.assertEqual(config["feishu"]["connection_mode"], "websocket")
        self.assertEqual(config["feishu"]["app_id"], "cli_real")
        self.assertEqual(config["feishu"]["app_secret"], "secret_real")
        self.assertEqual(config["feishu"]["allowed_open_ids"], ["*"])
        self.assertEqual(config["feishu"]["allowed_chat_ids"], ["*"])

    def test_configure_exact_whitelist(self):
        answers = iter([
            "y",
            "websocket",
            "cli_real",
            "",
            "exact",
            "ou_1,ou_2",
            "oc_1",
        ])
        secrets = iter(["secret_real"])
        wizard = Wizard(lambda prompt: next(answers), lambda prompt: next(secrets), lambda message: None)
        config, strategy = configure_feishu({"feishu": {}}, wizard)
        self.assertEqual(strategy, "exact")
        self.assertEqual(config["feishu"]["allowed_open_ids"], ["ou_1", "ou_2"])
        self.assertEqual(config["feishu"]["allowed_chat_ids"], ["oc_1"])

    def test_load_and_save_local_config(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            example = root / "config.example.json"
            config = root / "config.json"
            example.write_text('{"feishu": {"enabled": false}}', encoding="utf-8")
            loaded, created = load_config(config, example)
            self.assertTrue(created)
            loaded["feishu"]["enabled"] = True
            backup = save_config(config, loaded, make_backup=False)
            self.assertIsNone(backup)
            loaded_again, created_again = load_config(config, example)
            self.assertFalse(created_again)
            self.assertTrue(loaded_again["feishu"]["enabled"])


if __name__ == "__main__":
    unittest.main()
