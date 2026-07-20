import django.db.models.deletion

# ruff: noqa
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("planning", "0004_weeklyplanentry_adviserbrief"),
        ("export", "0002_structuredexport"),
    ]
    operations = [
        migrations.AddField(
            model_name="structuredexport",
            name="weekly_entry",
            field=models.OneToOneField(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="structured_export",
                to="planning.weeklyplanentry",
            ),
        ),
        migrations.AddField(
            model_name="writebackattempt",
            name="structured_export",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="attempts",
                to="export.structuredexport",
            ),
        ),
        migrations.AddConstraint(
            model_name="structuredexport",
            constraint=models.UniqueConstraint(
                fields=("decision", "allocation", "payload_version"),
                name="structured_export_approval_once",
            ),
        ),
    ]
