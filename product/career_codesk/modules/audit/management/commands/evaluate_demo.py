from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from career_codesk.modules.audit.evaluation import PRODUCT_DIR, write_report


class Command(BaseCommand):
    help = "Run every deterministic synthetic evaluation scenario and write its canonical report."

    def add_arguments(self, parser):
        parser.add_argument("--all", action="store_true", help="Run all eight required scenarios.")
        parser.add_argument(
            "--output", type=Path, default=PRODUCT_DIR / "evaluation-output" / "report-v1.json"
        )

    def handle(self, *args, **options):
        if not options["all"]:
            raise CommandError("evaluate_demo requires --all")
        report = write_report(options["output"])
        self.stdout.write(
            self.style.SUCCESS(
                f"evaluation report written: {options['output']} ({report['report_digest']})"
            )
        )
