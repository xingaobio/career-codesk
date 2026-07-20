# ruff: noqa
# fmt: off
# Generated as the initial deterministic prototype schema.
from django.db import migrations, models
import django.db.models.deletion
import career_codesk.domain


class Migration(migrations.Migration):
    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="Learner",
            fields=[
                ("id", models.CharField(default=career_codesk.domain.domain_id, editable=False, max_length=32, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True, editable=False)),
                ("schema_version", models.CharField(default="1.0", max_length=32)),
                ("fixture_scope", models.CharField(default="synthetic-demo-v1", max_length=64)),
                ("synthetic_identifier", models.CharField(max_length=128, unique=True)),
                ("fixture_version", models.CharField(max_length=64)),
            ],
        ),
        migrations.CreateModel(
            name="Enrolment",
            fields=[
                ("id", models.CharField(default=career_codesk.domain.domain_id, editable=False, max_length=32, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True, editable=False)),
                ("schema_version", models.CharField(default="1.0", max_length=32)),
                ("fixture_scope", models.CharField(default="synthetic-demo-v1", max_length=64)),
                ("course_code", models.CharField(max_length=64)),
                ("cohort_code", models.CharField(max_length=64)),
                ("source_row", models.PositiveIntegerField()),
                ("source_version", models.CharField(max_length=64)),
                ("learner", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="enrolments", to="intake_provenance.learner")),
            ],
        ),
        migrations.CreateModel(
            name="NeedCapture",
            fields=[
                ("id", models.CharField(default=career_codesk.domain.domain_id, editable=False, max_length=32, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True, editable=False)),
                ("schema_version", models.CharField(default="1.0", max_length=32)),
                ("fixture_scope", models.CharField(default="synthetic-demo-v1", max_length=64)),
                ("case_id", models.CharField(db_index=True, max_length=32)),
                ("source_type", models.CharField(choices=[("csv", "CSV"), ("learner", "Learner"), ("adviser", "Adviser")], max_length=16)),
                ("source_payload", models.JSONField()),
                ("source_version", models.CharField(max_length=64)),
                ("source_row", models.PositiveIntegerField(blank=True, null=True)),
                ("field_allowlist_passed", models.BooleanField()),
                ("enrolment", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="need_captures", to="intake_provenance.enrolment")),
                ("learner", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="need_captures", to="intake_provenance.learner")),
                ("supersedes", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="corrections", to="intake_provenance.needcapture")),
            ],
        ),
        migrations.CreateModel(
            name="SafetyExit",
            fields=[
                ("id", models.CharField(default=career_codesk.domain.domain_id, editable=False, max_length=32, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True, editable=False)),
                ("schema_version", models.CharField(default="1.0", max_length=32)),
                ("fixture_scope", models.CharField(default="synthetic-demo-v1", max_length=64)),
                ("signal_metadata", models.JSONField()),
                ("restricted_access_marker", models.BooleanField(default=True, editable=False)),
                ("human_handling_status", models.CharField(default="restricted_human_handling", max_length=64)),
                ("source_capture", models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, related_name="+", to="intake_provenance.needcapture")),
            ],
        ),
        migrations.AddConstraint(model_name="learner", constraint=models.CheckConstraint(check=models.Q(("synthetic_identifier__startswith", "synthetic-")), name="learner_identifier_is_synthetic")),
        migrations.AddConstraint(model_name="enrolment", constraint=models.UniqueConstraint(fields=("learner", "source_version", "source_row"), name="enrolment_source_row_once")),
        migrations.AddConstraint(model_name="safetyexit", constraint=models.CheckConstraint(check=models.Q(("restricted_access_marker", True)), name="safety_exit_is_restricted")),
    ]
