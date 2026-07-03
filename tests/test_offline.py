import json
import subprocess
import tempfile
import unittest
from pathlib import Path


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


if __name__ == "__main__":
    unittest.main()

