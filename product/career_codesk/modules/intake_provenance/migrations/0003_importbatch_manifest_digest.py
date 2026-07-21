# Generated as deterministic provenance for redacted manifest replay.
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("intake_provenance", "0002_import_provenance")]

    operations = [
        migrations.AddField(
            model_name="importbatch",
            name="manifest_digest",
            field=models.CharField(default="", max_length=64),
            preserve_default=False,
        ),
    ]
