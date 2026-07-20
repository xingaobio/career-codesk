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
            name="Case",
            fields=[
                ("id", models.CharField(default=career_codesk.domain.domain_id, editable=False, max_length=32, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True, editable=False)),
                ("schema_version", models.CharField(default="1.0", max_length=32)),
                ("fixture_scope", models.CharField(default="synthetic-demo-v1", max_length=64)),
                ("state", models.CharField(choices=[("open", "Open"), ("active", "Active"), ("closed", "Closed")], default="open", max_length=16)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("enrolment", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="cases", to="intake_provenance.enrolment")),
                ("learner", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="cases", to="intake_provenance.learner")),
            ],
        ),
        migrations.CreateModel(
            name="CaseTransition",
            fields=[
                ("id", models.CharField(default=career_codesk.domain.domain_id, editable=False, max_length=32, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True, editable=False)),
                ("schema_version", models.CharField(default="1.0", max_length=32)),
                ("fixture_scope", models.CharField(default="synthetic-demo-v1", max_length=64)),
                ("from_state", models.CharField(max_length=16)),
                ("to_state", models.CharField(max_length=16)),
                ("actor_id", models.CharField(max_length=64)),
                ("actor_type", models.CharField(default="adviser", max_length=32)),
                ("reason", models.TextField()),
                ("case", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="transitions", to="casework.case")),
            ],
        ),
        migrations.AddConstraint(model_name="casetransition", constraint=models.CheckConstraint(check=~models.Q(("from_state", models.F("to_state"))), name="case_state_changes")),
    ]
