import django.db.models.deletion
from django.db import migrations, models

# ruff: noqa
import career_codesk.domain


class Migration(migrations.Migration):
    dependencies = [
        ("planning", "0003_allocation_planner_binding"),
        ("decisions", "0001_initial"),
        ("export", "0001_initial"),
    ]
    operations = [
        migrations.CreateModel(
            name="StructuredExport",
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
                ("destination", models.CharField(default="local-mock-outbox", max_length=64)),
                ("payload_version", models.CharField(max_length=32)),
                ("canonical_payload", models.JSONField()),
                ("payload_digest", models.CharField(db_index=True, max_length=64)),
                ("idempotency_key", models.CharField(max_length=128, unique=True)),
                (
                    "allocation",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="structured_exports",
                        to="planning.interventionallocation",
                    ),
                ),
                (
                    "decision",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="structured_exports",
                        to="decisions.supportdecision",
                    ),
                ),
            ],
        )
    ]
