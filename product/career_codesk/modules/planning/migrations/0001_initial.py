# ruff: noqa
# fmt: off
from django.db import migrations, models
import django.db.models.deletion
import career_codesk.domain


class Migration(migrations.Migration):
    initial = True
    dependencies = [("ai_gateway", "0001_initial")]
    operations = [
        migrations.CreateModel(
            name="Need",
            fields=[
                ("id", models.CharField(default=career_codesk.domain.domain_id, editable=False, max_length=32, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True, editable=False)),
                ("schema_version", models.CharField(default="1.0", max_length=32)),
                ("fixture_scope", models.CharField(default="synthetic-demo-v1", max_length=64)),
                ("taxonomy_code", models.CharField(max_length=64)),
                ("taxonomy_version", models.CharField(max_length=64)),
                ("permitted_routes", models.JSONField(default=list)),
            ],
        ),
        migrations.CreateModel(
            name="InterventionAllocation",
            fields=[
                ("id", models.CharField(default=career_codesk.domain.domain_id, editable=False, max_length=32, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True, editable=False)),
                ("schema_version", models.CharField(default="1.0", max_length=32)),
                ("fixture_scope", models.CharField(default="synthetic-demo-v1", max_length=64)),
                ("case_id", models.CharField(db_index=True, max_length=32)),
                ("route_code", models.CharField(max_length=64)),
                ("planner_run_id", models.CharField(max_length=64)),
                ("planner_algorithm_version", models.CharField(max_length=64)),
                ("planner_policy_version", models.CharField(max_length=64)),
                ("state", models.CharField(choices=[("proposed", "Proposed"), ("active", "Active"), ("inactive", "Inactive")], default="proposed", max_length=16)),
                ("hypothesis", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="allocations", to="ai_gateway.needhypothesis")),
                ("need", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="allocations", to="planning.need")),
            ],
        ),
        migrations.AddConstraint(model_name="need", constraint=models.UniqueConstraint(fields=("taxonomy_code", "taxonomy_version"), name="need_taxonomy_version_once")),
        migrations.AddConstraint(model_name="interventionallocation", constraint=models.UniqueConstraint(fields=("case_id", "need", "planner_run_id"), name="allocation_planner_proposal_once")),
    ]
