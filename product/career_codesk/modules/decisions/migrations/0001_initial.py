# ruff: noqa
# fmt: off
from django.db import migrations, models
import django.db.models.deletion
import career_codesk.domain


class Migration(migrations.Migration):
    initial = True
    dependencies = [("planning", "0001_initial")]
    operations = [
        migrations.CreateModel(
            name="SupportDecision",
            fields=[
                ("id", models.CharField(default=career_codesk.domain.domain_id, editable=False, max_length=32, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True, editable=False)),
                ("schema_version", models.CharField(default="1.0", max_length=32)),
                ("fixture_scope", models.CharField(default="synthetic-demo-v1", max_length=64)),
                ("case_id", models.CharField(db_index=True, max_length=32)),
                ("action", models.CharField(choices=[("approve", "Approve"), ("amend", "Amend"), ("reject", "Reject")], max_length=16)),
                ("adviser_id", models.CharField(max_length=64)),
                ("reason", models.TextField()),
                ("policy_version", models.CharField(max_length=64)),
                ("planner_version", models.CharField(max_length=64)),
                ("allocation", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="support_decisions", to="planning.interventionallocation")),
                ("predecessor", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="successors", to="decisions.supportdecision")),
            ],
        ),
        migrations.CreateModel(
            name="ReviewedInput",
            fields=[
                ("id", models.CharField(default=career_codesk.domain.domain_id, editable=False, max_length=32, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True, editable=False)),
                ("schema_version", models.CharField(default="1.0", max_length=32)),
                ("fixture_scope", models.CharField(default="synthetic-demo-v1", max_length=64)),
                ("record_type", models.CharField(max_length=32)),
                ("record_id", models.CharField(max_length=32)),
                ("decision", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="reviewed_inputs", to="decisions.supportdecision")),
            ],
        ),
        migrations.AddConstraint(model_name="reviewedinput", constraint=models.UniqueConstraint(fields=("decision", "record_type", "record_id"), name="decision_reviewed_input_once")),
    ]
