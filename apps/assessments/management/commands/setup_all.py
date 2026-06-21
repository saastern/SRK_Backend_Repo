from django.core.management import call_command
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = (
        "One-shot setup: runs migrate, collectstatic, class-order fix, max-marks "
        "backfill, and summary recompute in order. Intended as a MANUAL run "
        "(e.g. after a deploy or a new-year setup) -- not as the every-deploy "
        "preDeployCommand, because set_class_orders deletes empty junk classes."
    )

    def add_arguments(self, parser):
        parser.add_argument('--skip-migrate', action='store_true',
                            help='Skip migrate (e.g. if preDeploy already ran it).')
        parser.add_argument('--skip-collectstatic', action='store_true',
                            help='Skip collectstatic.')
        parser.add_argument('--skip-orders', action='store_true',
                            help='Skip set_class_orders (the only destructive step).')

    def _step(self, title, func):
        self.stdout.write(self.style.MIGRATE_HEADING(f'\n=== {title} ==='))
        try:
            func()
            self.stdout.write(self.style.SUCCESS(f'✓ {title} done'))
        except Exception as e:
            # Don't abort the whole chain on one failure; report and continue.
            self.stdout.write(self.style.ERROR(f'✗ {title} failed: {e}'))

    def handle(self, *args, **options):
        self.stdout.write(self.style.MIGRATE_HEADING('Running full setup (setup_all)…'))

        if not options['skip_migrate']:
            self._step('migrate', lambda: call_command('migrate', interactive=False, verbosity=1))

        if not options['skip_collectstatic']:
            self._step('collectstatic',
                       lambda: call_command('collectstatic', interactive=False, verbosity=0))

        if not options['skip_orders']:
            self._step('set class orders + delete junk classes',
                       lambda: call_command('set_class_orders_cmd'))

        self._step('backfill max marks', lambda: call_command('backfill_max_marks'))

        self._step('recompute summaries', lambda: call_command('recompute_summaries'))

        self.stdout.write(self.style.SUCCESS('\nAll setup steps attempted. Review any ✗ above.'))
