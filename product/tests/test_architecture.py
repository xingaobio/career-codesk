import ast
from pathlib import Path

from django.test import SimpleTestCase

from career_codesk.composition import Foundation, compose_foundation
from career_codesk.identity import actor_for

MODULES = {
    "intake_provenance",
    "casework",
    "ai_gateway",
    "planning",
    "decisions",
    "delivery_feedback",
    "export",
    "audit",
}


class ArchitectureTests(SimpleTestCase):
    def test_all_rfc_module_packages_and_composition_exist(self):
        root = Path(__file__).resolve().parents[1] / "career_codesk" / "modules"
        actual = {
            path.name for path in root.iterdir() if path.is_dir() and not path.name.startswith("_")
        }
        self.assertEqual(actual, MODULES)
        self.assertEqual(len(compose_foundation().module_names), 8)

    def test_decision_gate_accepts_only_adviser(self):
        gate = compose_foundation().decisions
        self.assertTrue(gate.may_decide(actor_for("adviser")))
        self.assertFalse(gate.may_decide(actor_for("manager")))

    def test_composition_publishes_safe_adapter_identities(self):
        foundation = compose_foundation()
        self.assertIsInstance(foundation, Foundation)
        self.assertEqual(foundation.ai_gateway.preview("capture-1").status, "provisional")
        self.assertEqual(foundation.planning.identity().algorithm_version, "planner-foundation-v1")
        self.assertEqual(foundation.export.destination(), "local-mock-outbox")
        self.assertFalse(foundation.casework.convention().records_persisted)
        self.assertFalse(foundation.delivery_feedback.convention().feedback_persisted)
        self.assertFalse(foundation.audit.convention().events_persisted)

    def test_production_adapter_wiring_lives_only_in_the_composition_root(self):
        package_root = Path(__file__).resolve().parents[1] / "career_codesk"
        adapter_names = {
            "DeterministicFakeAiGateway",
            "DeterministicPlanner",
            "AdviserDecisionGate",
            "LocalMockOutbox",
            "ProvenanceIntake",
            "DeferredCaseworkService",
            "DeferredFeedbackRecorder",
            "DeferredAuditProjection",
        }
        for source in package_root.rglob("*.py"):
            tree = ast.parse(source.read_text(encoding="utf-8"))
            calls = {
                node.func.id
                for node in ast.walk(tree)
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
            }
            if calls & adapter_names:
                self.assertEqual(source.name, "composition.py")

    def test_module_contracts_do_not_import_sibling_private_implementation(self):
        root = Path(__file__).resolve().parents[1] / "career_codesk" / "modules"
        for contract in root.glob("*/contracts.py"):
            tree = ast.parse(contract.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.module:
                    parts = node.module.split(".")
                    if len(parts) >= 4 and parts[:2] == ["career_codesk", "modules"]:
                        self.assertFalse(parts[3].startswith("_"), f"{contract}: {node.module}")
