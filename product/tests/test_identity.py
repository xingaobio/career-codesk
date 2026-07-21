from django.test import SimpleTestCase

from career_codesk.identity import UnsupportedRoleError, actor_for, available_actors


class IdentityTests(SimpleTestCase):
    def test_exactly_two_fixed_simulated_actors(self):
        actors = available_actors()
        self.assertEqual(
            [(actor.id, actor.role) for actor in actors],
            [("actor-manager-001", "manager"), ("actor-adviser-001", "adviser")],
        )
        self.assertEqual(actor_for("adviser").display_name, "Synthetic Adviser")

    def test_unsupported_role_is_rejected(self):
        with self.assertRaises(UnsupportedRoleError):
            actor_for("learner")
