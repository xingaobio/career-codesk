# ruff: noqa
# fmt: off
from django.db import migrations, models
import django.db.models.deletion
import career_codesk.domain


class Migration(migrations.Migration):
    dependencies = [("ai_gateway", "0001_initial")]

    operations = [
        migrations.CreateModel(
            name="AiGatewayAttempt",
            fields=[
                ("id", models.CharField(default=career_codesk.domain.domain_id, editable=False, max_length=32, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True, editable=False)),
                ("schema_version", models.CharField(default="1.0", max_length=32)),
                ("fixture_scope", models.CharField(default="synthetic-demo-v1", max_length=64)),
                ("task_kind", models.CharField(max_length=32)),
                ("source_record_ids", models.JSONField()),
                ("source_records", models.JSONField()),
                ("input_metadata", models.JSONField()),
                ("input_digest", models.CharField(max_length=64)),
                ("disposition", models.CharField(max_length=40)),
                ("prompt_version", models.CharField(max_length=64)),
                ("output_schema_version", models.CharField(max_length=64)),
                ("model_version", models.CharField(max_length=64)),
                ("adapter_version", models.CharField(max_length=64)),
                ("policy_version", models.CharField(max_length=64)),
            ],
        ),
        migrations.CreateModel(
            name="AiGatewayOutput",
            fields=[
                ("id", models.CharField(default=career_codesk.domain.domain_id, editable=False, max_length=32, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True, editable=False)),
                ("schema_version", models.CharField(default="1.0", max_length=32)),
                ("fixture_scope", models.CharField(default="synthetic-demo-v1", max_length=64)),
                ("validated_payload", models.JSONField(blank=True, null=True)),
                ("output_digest", models.CharField(blank=True, max_length=64)),
                ("validation_errors", models.JSONField(default=list)),
                ("confidence", models.CharField(max_length=16)),
                ("authority", models.CharField(default="provisional_no_decision_authority", max_length=64)),
                ("attempt", models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, related_name="output", to="ai_gateway.aigatewayattempt")),
            ],
        ),
        migrations.AddField(model_name="needhypothesis", name="confidence_state", field=models.CharField(default="unknown", max_length=16)),
        migrations.AddField(model_name="needhypothesis", name="gateway_output", field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="hypotheses", to="ai_gateway.aigatewayoutput")),
        migrations.AddField(model_name="needhypothesis", name="model_version", field=models.CharField(default="legacy-fake-v1", max_length=64)),
        migrations.AddField(model_name="needhypothesis", name="prompt_version", field=models.CharField(default="legacy-prompt-v1", max_length=64)),
        migrations.AddConstraint(model_name="aigatewayattempt", constraint=models.CheckConstraint(check=models.Q(("task_kind__in", ("intake_interpretation", "need_hypothesis", "cohort_explanation", "adviser_draft"))), name="ai_attempt_task_is_allowlisted")),
        migrations.AddConstraint(model_name="aigatewayattempt", constraint=models.CheckConstraint(check=models.Q(("disposition__in", ("provisional_output", "human_review_required", "restricted_safety_escalation", "schema_failure", "timeout", "adapter_error"))), name="ai_attempt_disposition_is_closed")),
        migrations.AddConstraint(model_name="aigatewayoutput", constraint=models.CheckConstraint(check=models.Q(("confidence__in", ("high", "low", "unknown"))), name="ai_output_confidence_is_closed")),
        migrations.AddConstraint(model_name="aigatewayoutput", constraint=models.CheckConstraint(check=models.Q(("authority", "provisional_no_decision_authority")), name="ai_output_has_no_decision_authority")),
    ]
