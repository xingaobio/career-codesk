# ruff: noqa
# fmt: off
from django.db import migrations, models
import django.db.models.deletion
import career_codesk.domain


class Migration(migrations.Migration):
    initial = True
    dependencies = [("planning", "0001_initial")]
    operations = [
        migrations.CreateModel(
            name="DeliveryEvent",
            fields=[
                ("id", models.CharField(default=career_codesk.domain.domain_id, editable=False, max_length=32, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True, editable=False)),
                ("schema_version", models.CharField(default="1.0", max_length=32)),
                ("fixture_scope", models.CharField(default="synthetic-demo-v1", max_length=64)),
                ("case_id", models.CharField(db_index=True, max_length=32)),
                ("actor_id", models.CharField(max_length=64)),
                ("result", models.CharField(max_length=64)),
                ("source", models.CharField(max_length=64)),
                ("allocation", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="delivery_events", to="planning.interventionallocation")),
            ],
        ),
        migrations.CreateModel(
            name="OutcomeConfirmation",
            fields=[
                ("id", models.CharField(default=career_codesk.domain.domain_id, editable=False, max_length=32, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True, editable=False)),
                ("schema_version", models.CharField(default="1.0", max_length=32)),
                ("fixture_scope", models.CharField(default="synthetic-demo-v1", max_length=64)),
                ("case_id", models.CharField(db_index=True, max_length=32)),
                ("actor_id", models.CharField(max_length=64)),
                ("response", models.CharField(choices=[("helped", "Helped"), ("unresolved", "Unresolved"), ("confirmed", "Confirmed")], max_length=16)),
                ("exact_response", models.TextField()),
                ("delivery_event", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="outcome_confirmations", to="delivery_feedback.deliveryevent")),
            ],
        ),
    ]
