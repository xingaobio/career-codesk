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
    _concrete_adapter_names = {"DeterministicFakeAdapter"}
    _provider_modules = {
        "openai",
        "anthropic",
        "google.generativeai",
        "boto3",
        "requests",
        "httpx",
    }

    @classmethod
    def _ai_boundary_violations(cls, source_text):
        """Return provider/adapter bypasses, resolving simple import aliases."""
        tree = ast.parse(source_text)
        adapter_aliases = set()
        violations = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for imported in node.names:
                    if any(
                        imported.name == provider or imported.name.startswith(f"{provider}.")
                        for provider in cls._provider_modules
                    ):
                        violations.append(f"provider import: {imported.name}")
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if any(
                    module == provider or module.startswith(f"{provider}.")
                    for provider in cls._provider_modules
                ):
                    violations.append(f"provider import: {module}")
                for imported in node.names:
                    if imported.name in cls._concrete_adapter_names:
                        adapter_aliases.add(imported.asname or imported.name)
                        violations.append(f"adapter import: {imported.name}")
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if isinstance(node.func, ast.Name) and (
                node.func.id in adapter_aliases or node.func.id in cls._concrete_adapter_names
            ):
                violations.append(f"adapter construction: {node.func.id}")
            elif (
                isinstance(node.func, ast.Attribute)
                and node.func.attr in cls._concrete_adapter_names
            ):
                violations.append(f"qualified adapter construction: {node.func.attr}")
        return violations

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
        self.assertTrue(callable(foundation.ai_gateway.interpret))
        self.assertEqual(foundation.planning.identity().algorithm_version, "capacity-planner-v1")
        self.assertEqual(foundation.export.destination(), "local-mock-outbox")
        self.assertTrue(foundation.casework.convention().records_persisted)
        self.assertTrue(foundation.delivery_feedback.convention().feedback_persisted)
        self.assertFalse(foundation.audit.convention().events_persisted)

    def test_production_adapter_wiring_lives_only_in_the_composition_root(self):
        package_root = Path(__file__).resolve().parents[1] / "career_codesk"
        adapter_names = {
            "DeterministicFakeAdapter",
            "DeterministicPlanningService",
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

    def test_only_composition_constructs_ai_adapters(self):
        package_root = Path(__file__).resolve().parents[1] / "career_codesk"
        for source in package_root.rglob("*.py"):
            violations = self._ai_boundary_violations(source.read_text(encoding="utf-8"))
            if violations:
                self.assertEqual(
                    source.relative_to(package_root).as_posix(),
                    "composition.py",
                    f"{source}: {violations}",
                )

    def test_ai_boundary_checker_rejects_alias_qualified_and_provider_submodule_bypasses(self):
        fixtures = (
            (
                "from career_codesk.modules.ai_gateway.contracts "
                "import DeterministicFakeAdapter as Alias\nAlias()"
            ),
            (
                "import career_codesk.modules.ai_gateway.contracts as gateway_contracts\n"
                "gateway_contracts.DeterministicFakeAdapter()"
            ),
            (
                "from career_codesk.modules.ai_gateway import contracts as gateway_contracts\n"
                "gateway_contracts.DeterministicFakeAdapter()"
            ),
            "import openai.chat",
            "from httpx._client import Client",
        )
        for fixture in fixtures:
            with self.subTest(fixture=fixture):
                self.assertTrue(self._ai_boundary_violations(fixture))

    def test_only_gateway_service_invokes_adapter_generate(self):
        package_root = Path(__file__).resolve().parents[1] / "career_codesk"
        for source in package_root.rglob("*.py"):
            tree = ast.parse(source.read_text(encoding="utf-8"))
            generate_calls = [
                node
                for node in ast.walk(tree)
                if isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "generate"
            ]
            if generate_calls:
                self.assertEqual(
                    source.relative_to(package_root).as_posix(),
                    "modules/ai_gateway/services.py",
                )
