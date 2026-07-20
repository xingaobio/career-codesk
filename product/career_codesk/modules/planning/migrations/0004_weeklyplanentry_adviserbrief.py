# ruff: noqa
# Generated manually for approval-gated weekly execution packages.

import django.db.models.deletion
from django.db import migrations, models

import career_codesk.domain


class Migration(migrations.Migration):
    dependencies = [("decisions", "0001_initial"), ("planning", "0003_allocation_planner_binding")]

    operations = [
        migrations.CreateModel(
            name="WeeklyPlanEntry",
            fields=[
                (
                    "id",
                    models.CharField(
                        default=career_codesk.domain.domain_id,
                        editable=False,
                        max_length=32,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("schema_version", models.CharField(default="1.0", max_length=32)),
                ("fixture_scope", models.CharField(default="synthetic-demo-v1", max_length=64)),
                ("case_id", models.CharField(db_index=True, max_length=32)),
                ("route_code", models.CharField(max_length=64)),
                ("resource_owner_id", models.CharField(max_length=64)),
                ("scheduled_on", models.DateField()),
                ("deadline", models.DateField()),
                ("effort_hours", models.PositiveIntegerField()),
                ("capacity_effect", models.JSONField(default=dict)),
                ("reviewed_capture_ids", models.JSONField(default=list)),
                ("reviewed_hypothesis_ids", models.JSONField(default=list)),
                (
                    "allocation",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="weekly_plan_entry",
                        to="planning.interventionallocation",
                    ),
                ),
                (
                    "decision",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="weekly_plan_entry",
                        to="decisions.supportdecision",
                    ),
                ),
                (
                    "need",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="weekly_entries",
                        to="planning.need",
                    ),
                ),
                (
                    "planner_run",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="weekly_plan_entries",
                        to="planning.plannerrun",
                    ),
                ),
            ],
        ),
        migrations.CreateModel(
            name="AdviserBrief",
            fields=[
                (
                    "id",
                    models.CharField(
                        default=career_codesk.domain.domain_id,
                        editable=False,
                        max_length=32,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("schema_version", models.CharField(default="1.0", max_length=32)),
                ("fixture_scope", models.CharField(default="synthetic-demo-v1", max_length=64)),
                ("known_facts", models.TextField()),
                ("questions_to_ask", models.TextField()),
                ("assumptions_prohibited", models.TextField()),
                ("intended_outcome", models.TextField()),
                ("source_capture_ids", models.JSONField(default=list)),
                ("provisional_hypothesis_ids", models.JSONField(default=list)),
                (
                    "weekly_entry",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="adviser_brief",
                        to="planning.weeklyplanentry",
                    ),
                ),
            ],
        ),
    ]
