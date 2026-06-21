from django.core.management.base import BaseCommand

from apps.assessments.models import AcademicYear, StudentMark
from apps.assessments.services import GradingService


class Command(BaseCommand):
    help = (
        "Recompute StudentExamSummary rows (totals, percentage, overall grade, "
        "rank) from current StudentMark data using the GradeScale table. Run "
        "once after deploying the grade-logic unification to fix any historically "
        "wrong overall_grade values."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--year',
            dest='year',
            default=None,
            help='Academic year name (e.g. 2024-2025). Defaults to the current year.',
        )

    def handle(self, *args, **options):
        year_name = options.get('year')
        if year_name:
            academic_year = AcademicYear.objects.filter(name=year_name).first()
        else:
            academic_year = AcademicYear.objects.filter(is_current=True).first()

        if not academic_year:
            self.stdout.write(self.style.ERROR('No matching academic year found.'))
            return

        # Distinct (student, exam) pairs that have marks in this year.
        pairs = (
            StudentMark.objects
            .filter(academic_year=academic_year)
            .values_list('student_id', 'exam_id')
            .distinct()
        )

        count = 0
        for student_id, exam_id in pairs:
            GradingService.calculate_student_exam_summary(
                student_id, exam_id, academic_year.id
            )
            count += 1

        self.stdout.write(self.style.SUCCESS(
            f'Recomputed {count} student-exam summaries for {academic_year.name}.'
        ))
