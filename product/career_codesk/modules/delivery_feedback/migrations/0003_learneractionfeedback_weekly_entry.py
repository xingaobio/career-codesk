import django.db.models.deletion

# ruff: noqa
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("planning", "0004_weeklyplanentry_adviserbrief"),
        ("delivery_feedback", "0002_learneractionfeedback"),
    ]
    operations = [
        migrations.AddField(
            model_name="learneractionfeedback",
            name="weekly_entry",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="learner_feedback",
                to="planning.weeklyplanentry",
            ),
        )
    ]
