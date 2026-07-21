# ruff: noqa
# fmt: off
from django.db import migrations, models
import django.db.models.deletion
import career_codesk.domain


class Migration(migrations.Migration):
    initial = True
    dependencies = [("intake_provenance", "0001_initial")]
    operations = [
        migrations.CreateModel(
            name="NeedHypothesis",
            fields=[
                ("id", models.CharField(default=career_codesk.domain.domain_id, editable=False, max_length=32, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True, editable=False)),
                ("schema_version", models.CharField(default="1.0", max_length=32)),
                ("fixture_scope", models.CharField(default="synthetic-demo-v1", max_length=64)),
                ("case_id", models.CharField(db_index=True, max_length=32)),
                ("tags", models.JSONField(default=list)),
                ("explanation", models.TextField()),
                ("confidence", models.DecimalField(blank=True, decimal_places=3, max_digits=4, null=True)),
                ("unknowns", models.JSONField(default=list)),
                ("output_schema_version", models.CharField(max_length=32)),
                ("gateway_policy_version", models.CharField(max_length=64)),
                ("adapter_version", models.CharField(max_length=64)),
                ("status", models.CharField(default="provisional", max_length=32)),
            ],
        ),
        migrations.CreateModel(
            name="NeedHypothesisInput",
            fields=[
                ("id", models.CharField(default=career_codesk.domain.domain_id, editable=False, max_length=32, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True, editable=False)),
                ("schema_version", models.CharField(default="1.0", max_length=32)),
                ("fixture_scope", models.CharField(default="synthetic-demo-v1", max_length=64)),
                ("capture", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="hypothesis_inputs", to="intake_provenance.needcapture")),
                ("hypothesis", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="inputs", to="ai_gateway.needhypothesis")),
            ],
        ),
        migrations.AddConstraint(model_name="needhypothesis", constraint=models.CheckConstraint(check=models.Q(confidence__isnull=True) | (models.Q(confidence__gte=0) & models.Q(confidence__lte=1)), name="hypothesis_confidence_in_range")),
        migrations.AddConstraint(model_name="needhypothesis", constraint=models.CheckConstraint(check=models.Q(("status", "provisional")), name="hypothesis_is_provisional")),
        migrations.AddConstraint(model_name="needhypothesisinput", constraint=models.UniqueConstraint(fields=("hypothesis", "capture"), name="hypothesis_input_once")),
    ]
