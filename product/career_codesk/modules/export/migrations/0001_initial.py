# ruff: noqa
# fmt: off
from django.db import migrations, models
import django.db.models.deletion
import career_codesk.domain


class Migration(migrations.Migration):
    initial = True
    dependencies = [("decisions", "0001_initial"), ("planning", "0001_initial")]
    operations = [
        migrations.CreateModel(
            name="WritebackAttempt",
            fields=[
                ("id", models.CharField(default=career_codesk.domain.domain_id, editable=False, max_length=32, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True, editable=False)),
                ("schema_version", models.CharField(default="1.0", max_length=32)),
                ("fixture_scope", models.CharField(default="synthetic-demo-v1", max_length=64)),
                ("idempotency_key", models.CharField(max_length=128)),
                ("payload_version", models.CharField(max_length=32)),
                ("payload_digest", models.CharField(max_length=64)),
                ("attempt_number", models.PositiveIntegerField()),
                ("result", models.CharField(choices=[("pending", "Pending"), ("succeeded", "Succeeded locally"), ("failed", "Failed"), ("not_sent", "Not sent")], max_length=16)),
                ("failure_reason", models.TextField(blank=True)),
                ("allocation", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="writeback_attempts", to="planning.interventionallocation")),
                ("decision", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="writeback_attempts", to="decisions.supportdecision")),
            ],
        ),
        migrations.AddConstraint(model_name="writebackattempt", constraint=models.UniqueConstraint(fields=("allocation", "payload_version", "attempt_number"), name="writeback_attempt_number_once")),
    ]
