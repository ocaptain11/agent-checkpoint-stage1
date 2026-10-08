from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from pilot.pilot_runner import PilotRunner


class PilotRunnerTests(unittest.TestCase):
    def test_plan_does_not_claim_pass_or_execute(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            marker = root / "must_not_exist"
            config = {
                "run_id": "plan-only",
                "vllm": {"start_command": ["python", "-c", f"open(r'{marker}', 'w').write('bad')"]},
            }
            plan = PilotRunner(config, root / "run").plan()
            self.assertEqual(plan["mode"], "plan")
            self.assertIn("cannot establish PILOT_PASS", plan["warning"])
            self.assertFalse(marker.exists())
            self.assertFalse((root / "run" / "pilot_evidence.json").exists())

    def test_execute_with_placeholder_is_invalid_not_pass(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = {
                "run_id": "bad-config",
                "real_guest_required": True,
                "vllm": {"start_command": ["REPLACE_ME"]},
            }
            evidence = PilotRunner(config, root / "run").execute()
            self.assertEqual(evidence["status"], "INVALID_INFRA")
            self.assertFalse(evidence["official_evaluator"])
            self.assertTrue((root / "run" / "failure_log.json").exists())

    def test_guest_fallback_is_rejected_before_launch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = {"run_id": "fallback", "guest_fallback": True}
            evidence = PilotRunner(config, root / "run").execute()
            self.assertEqual(evidence["status"], "INVALID_INFRA")
            self.assertTrue(evidence["guest_fallback"])
            failures = json.loads((root / "run" / "failure_log.json").read_text())
            self.assertIn("guest_fallback is forbidden", failures["failures"][0]["error"])


if __name__ == "__main__":
    unittest.main()
