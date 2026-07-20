import django.db.models.deletion
from django.db import migrations, models

# ruff: noqa
import career_codesk.domain


class Migration(migrations.Migration):
    dependencies = [
        ("intake_provenance", "0003_importbatch_manifest_digest"),
        ("delivery_feedback", "0001_initial"),
    ]
    operations = [
        migrations.CreateModel(
            name="LearnerActionFeedback",
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
                ("actor_id", models.CharField(max_length=64)),
                (
                    "kind",
                    models.CharField(
                        choices=[
                            ("helped", "Helped"),
                            ("unresolved", "Unresolved"),
                            ("human_help", "Human help requested"),
                            ("correction", "Correction requested"),
                        ],
                        max_length=16,
                    ),
                ),
                ("exact_response", models.TextField()),
                (
                    "correction_capture",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="learner_feedback_corrections",
                        to="intake_provenance.needcapture",
                    ),
                ),
            ],
        )
    ]
