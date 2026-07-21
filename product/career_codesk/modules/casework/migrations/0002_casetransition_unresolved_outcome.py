# ruff: noqa
# fmt: off
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("casework", "0001_initial"),
        ("delivery_feedback", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="casetransition",
            name="unresolved_outcome",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="reopen_transitions",
                to="delivery_feedback.outcomeconfirmation",
            ),
        ),
    ]
