# Generated manually for the bounded adviser-workbench planner binding.

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("planning", "0002_planner_run_evidence")]

    operations = [
        migrations.AddField(
            model_name="interventionallocation",
            name="demand_id",
            field=models.CharField(default="legacy-unbound", max_length=64),
        ),
        migrations.AddField(
            model_name="interventionallocation",
            name="resource_id",
            field=models.CharField(default="legacy-unbound", max_length=64),
        ),
        migrations.AddField(
            model_name="interventionallocation",
            name="scheduled_on",
            field=models.DateField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="interventionallocation",
            name="waiting_days",
            field=models.PositiveIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="interventionallocation",
            name="effort_hours",
            field=models.PositiveIntegerField(default=1),
        ),
        migrations.AddField(
            model_name="interventionallocation",
            name="plan_variant",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="interventionallocation",
            name="supersedes",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=models.deletion.PROTECT,
                related_name="replacement_proposals",
                to="planning.interventionallocation",
            ),
        ),
        migrations.RemoveConstraint(
            model_name="interventionallocation",
            name="allocation_planner_proposal_once",
        ),
        migrations.AddConstraint(
            model_name="interventionallocation",
            constraint=models.UniqueConstraint(
                fields=("case_id", "need", "planner_run_id", "demand_id", "plan_variant"),
                name="allocation_planner_binding_once",
            ),
        ),
    ]
