from pathlib import Path
import importlib.util
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "skills" / "deepseek-token-saver" / "scripts" / "deepseek_delegate.py"


def load_module():
    spec = importlib.util.spec_from_file_location("deepseek_delegate_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class RoutingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_module()

    def test_final_phase_uses_gpt55(self):
        decision = self.module.infer_route("review this release", "final", "low", "normal")
        self.assertEqual(decision.route, "gpt-5.5")

    def test_draft_phase_uses_deepseek(self):
        decision = self.module.infer_route("draft three options", "draft", "low", "low")
        self.assertEqual(decision.route, "deepseek")
        self.assertTrue(decision.requires_gpt55_review)

    def test_implementation_is_hybrid(self):
        decision = self.module.infer_route("write a helper function", "implement", "low", "normal")
        self.assertEqual(decision.route, "hybrid")
        self.assertTrue(decision.requires_gpt55_review)

    def test_high_risk_uses_gpt55(self):
        decision = self.module.infer_route("handle auth credentials", "auto", "high", "normal")
        self.assertEqual(decision.route, "gpt-5.5")

    def test_redacts_api_key(self):
        fake_key = "sk-" + "abc123456789"
        redacted = self.module.redact_secrets("Authorization: Bearer " + fake_key)
        self.assertNotIn("abc123456789", redacted)

    def test_estimates_tokens(self):
        self.assertGreater(self.module.estimate_tokens("hello world"), 0)


if __name__ == "__main__":
    unittest.main()
