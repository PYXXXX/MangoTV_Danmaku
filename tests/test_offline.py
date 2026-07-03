import json
import subprocess
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from types import SimpleNamespace

from server.precise_results import parse_precise_result, validate_precise_result


ROOT = Path(__file__).resolve().parents[1]


class OfflinePipelineTest(unittest.TestCase):
    def test_clean_and_merge(self):
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp) / "out"
            subprocess.run(
                ["python3", str(ROOT / "tools/offline_clean.py"), str(ROOT / "tests/fixtures/sample.jsonl"), "--out", str(out)],
                check=True,
                capture_output=True,
                text=True,
            )
            preliminary = json.loads((out / "preliminary.json").read_text(encoding="utf-8"))
            self.assertEqual(preliminary["ruleAcceptedMessages"], 3)
            self.assertEqual(preliminary["reviewMessages"], 3)
            self.assertEqual(preliminary["ruleVoteCounts"], {"c1": 1, "c2": 2})

            review_ids = []
            for path in (out / "review_batches").glob("*.jsonl"):
                review_ids.extend(json.loads(line)["i"] for line in path.read_text(encoding="utf-8").splitlines())
            decisions = [
                {"i": record_id, "c": [], "r": "reject"}
                for record_id in review_ids
            ]
            (out / "codex_decisions.jsonl").write_text(
                "\n".join(json.dumps(item, ensure_ascii=False) for item in decisions) + "\n",
                encoding="utf-8",
            )
            subprocess.run(["python3", str(ROOT / "tools/merge_results.py"), str(out)], check=True, capture_output=True, text=True)
            result = json.loads((out / "final_result.json").read_text(encoding="utf-8"))
            self.assertEqual(result["ranking"][0]["name"], "窦靖童")
            self.assertEqual(result["ranking"][0]["votes"], 2)
            self.assertEqual(result["unresolvedReviewMessages"], 0)
            self.assertTrue((out / "AGENT_INSTRUCTIONS.md").exists())

            precise_path = out / "precise_result.json"
            precise = json.loads(precise_path.read_text(encoding="utf-8"))
            self.assertEqual(precise["resultType"], "precise")
            self.assertEqual(precise["sessionId"], "sample-session")
            self.assertEqual(precise["audit"]["inputMessages"], 7)
            self.assertEqual(precise["audit"]["unresolvedReviewMessages"], 0)
            self.assertEqual(ET.parse(out / "precise_result.xml").getroot().tag, "preciseResult")

            meta = SimpleNamespace(
                id="sample-session", activity="未分类活动", name=precise["sessionName"],
                candidates=[
                    SimpleNamespace(id="c1", name="张远"),
                    SimpleNamespace(id="c2", name="窦靖童"),
                    SimpleNamespace(id="c3", name="陈楚生"),
                ],
                messageCount=7,
            )
            content = precise_path.read_bytes()
            normalized = validate_precise_result(parse_precise_result("precise_result.json", content), meta, content, "precise_result.json")
            self.assertEqual(normalized["voteCounts"]["c2"], 2)
            xml_content = (out / "precise_result.xml").read_bytes()
            normalized_xml = validate_precise_result(parse_precise_result("precise_result.xml", xml_content), meta, xml_content, "precise_result.xml")
            self.assertEqual(normalized_xml["source"]["format"], "xml")


if __name__ == "__main__":
    unittest.main()
