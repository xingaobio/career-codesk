# ruff: noqa
# fmt: off
# Generated as deterministic provenance for synthetic CSV intake.
from django.db import migrations, models
import django.db.models.deletion
import career_codesk.domain


class Migration(migrations.Migration):
    dependencies = [("intake_provenance", "0001_initial")]

    operations = [
        migrations.CreateModel(
            name="ImportBatch",
            fields=[
                ("id", models.CharField(default=career_codesk.domain.domain_id, editable=False, max_length=32, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True, editable=False)),
                ("fixture_scope", models.CharField(default="synthetic-demo-v1", max_length=64)),
                ("source_label", models.CharField(max_length=96)),
                ("schema_version", models.CharField(max_length=32)),
                ("fixture_version", models.CharField(max_length=64)),
                ("source_version", models.CharField(max_length=64)),
                ("fixed_clock_utc", models.CharField(max_length=32)),
                ("seed", models.CharField(max_length=32)),
                ("synthetic_data_attestation", models.BooleanField()),
                ("payload_digest", models.CharField(max_length=64)),
            ],
        ),
        migrations.CreateModel(
            name="ImportRowResult",
            fields=[
                ("id", models.CharField(default=career_codesk.domain.domain_id, editable=False, max_length=32, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True, editable=False)),
                ("schema_version", models.CharField(default="1.0", max_length=32)),
                ("fixture_scope", models.CharField(default="synthetic-demo-v1", max_length=64)),
                ("row_number", models.PositiveIntegerField()),
                ("status", models.CharField(choices=[("accepted", "Accepted"), ("rejected", "Rejected"), ("quarantined", "Quarantined")], max_length=16)),
                ("error_codes", models.JSONField(default=list)),
                ("fields", models.JSONField(default=list)),
                ("import_batch", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="row_results", to="intake_provenance.importbatch")),
            ],
        ),
        migrations.AddField(model_name="enrolment", name="import_batch", field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="enrolments", to="intake_provenance.importbatch")),
        migrations.AddField(model_name="needcapture", name="import_batch", field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="need_captures", to="intake_provenance.importbatch")),
        migrations.AddConstraint(model_name="importbatch", constraint=models.UniqueConstraint(fields=("source_label", "source_version"), name="import_source_version_once")),
        migrations.AddConstraint(model_name="importrowresult", constraint=models.UniqueConstraint(fields=("import_batch", "row_number"), name="import_row_outcome_once")),
    ]
