import django.db.models.deletion
from django.db import migrations, models

# ruff: noqa
import career_codesk.domain


class Migration(migrations.Migration):
    dependencies = [("casework", "0002_casetransition_unresolved_outcome")]
    operations = [
        migrations.CreateModel(
            name="CaseReviewRequest",
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
                ("feedback_id", models.CharField(max_length=32, unique=True)),
                ("reason", models.TextField()),
                ("actor_id", models.CharField(max_length=64)),
                (
                    "case",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="review_requests",
                        to="casework.case",
                    ),
                ),
            ],
        )
    ]
