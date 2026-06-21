from django.core.management.base import BaseCommand

from apps.assessments.models import AcademicYear, ClassSubjectMapping, Exam


class Command(BaseCommand):
    help = (
        "Populate ClassSubjectMapping.fa_max_marks / sa_max_marks for the current "
        "year from the legacy default values, so existing subjects have configured "
        "max marks instead of 0. Run once after migrating. Only fills rows where "
        "the value is still 0 (won't overwrite anything already configured)."
    )

    def add_arguments(self, parser):
        parser.add_argument('--year', dest='year', default=None,
                            help='Academic year name (defaults to current).')
        parser.add_argument('--force', action='store_true',
                            help='Overwrite even rows that already have a non-zero value.')

    def handle(self, *args, **options):
        year_name = options.get('year')
        if year_name:
            academic_year = AcademicYear.objects.filter(name=year_name).first()
        else:
            academic_year = AcademicYear.objects.filter(is_current=True).first()

        if not academic_year:
            self.stdout.write(self.style.ERROR('No matching academic year found.'))
            return

        force = options.get('force')

        # Any FA exam / any SA exam is enough to get the default per (class, subject).
        fa_exam = Exam.objects.filter(exam_type='FA').first()
        sa_exam = Exam.objects.filter(exam_type='SA').first()

        mappings = ClassSubjectMapping.objects.filter(
            academic_year=academic_year
        ).select_related('student_class', 'subject')

        updated = 0
        for m in mappings:
            cg = m.student_class.class_group if m.student_class else None
            changed = False

            if fa_exam and (force or m.fa_max_marks == 0):
                m.fa_max_marks = fa_exam._default_max_marks(cg, m.subject)
                changed = True
            if sa_exam and (force or m.sa_max_marks == 0):
                m.sa_max_marks = sa_exam._default_max_marks(cg, m.subject)
                changed = True

            if changed:
                m.save(update_fields=['fa_max_marks', 'sa_max_marks'])
                updated += 1

        self.stdout.write(self.style.SUCCESS(
            f'Backfilled max marks on {updated} mappings for {academic_year.name}.'
        ))
