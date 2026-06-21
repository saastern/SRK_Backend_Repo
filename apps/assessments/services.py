from django.db.models import Sum, Avg, Count, Q
from decimal import Decimal
from .models import *

class GradingService:
    """Service to handle all grading calculations and business logic"""
    
    @staticmethod
    def calculate_student_exam_summary(student_id, exam_id, academic_year_id):
        """Calculate comprehensive summary for a student's specific exam (e.g., FA1)"""
        try:
            student = StudentProfile.objects.get(id=student_id)
            exam = Exam.objects.get(id=exam_id)
            academic_year = AcademicYear.objects.get(id=academic_year_id)
        except (StudentProfile.DoesNotExist, Exam.DoesNotExist, AcademicYear.DoesNotExist):
            return None
        
        # Get all MAIN subject marks for this exam (exclude optional subjects)
        main_subject_marks = StudentMark.objects.filter(
            student=student,
            exam=exam,
            academic_year=academic_year
        ).select_related('subject').filter(
            subject__classsubjectmapping__student_class=student.student_class,
            subject__classsubjectmapping__is_main_subject=True,
            subject__classsubjectmapping__academic_year=academic_year
        )
        
        if not main_subject_marks.exists():
            return None
        
        # Calculate totals (only main subjects count toward percentage)
        total_obtained = main_subject_marks.aggregate(Sum('marks_obtained'))['marks_obtained__sum'] or 0
        total_max = main_subject_marks.aggregate(Sum('max_marks'))['max_marks__sum'] or 0
        subjects_count = main_subject_marks.count()
        
        # Calculate percentage
        percentage = (total_obtained / total_max * 100) if total_max > 0 else 0
        
        # Calculate average grade point for overall grade
        avg_grade_point = main_subject_marks.aggregate(Avg('grade_point'))['grade_point__avg'] or 0
        
        # Determine overall grade based on percentage
        overall_grade, overall_gp = GradingService.get_grade_from_percentage(
            percentage, 
            student.student_class.class_group, 
            exam.exam_type
        )
        
        # Calculate class rank
        class_rank = GradingService.calculate_class_rank(
            student, exam, academic_year, total_obtained
        )
        
        # Save or update summary
        summary_obj, created = StudentExamSummary.objects.update_or_create(
            student=student,
            exam=exam,
            academic_year=academic_year,
            defaults={
                'total_marks_obtained': total_obtained,
                'total_max_marks': total_max,
                'percentage': round(percentage, 2),
                'overall_grade': overall_grade,
                'overall_grade_point': overall_gp,
                'class_rank': class_rank,
                'subjects_count': subjects_count
            }
        )
        
        return {
            'student': student,
            'exam': exam,
            'total_obtained': float(total_obtained),
            'total_max': total_max,
            'percentage': round(percentage, 2),
            'overall_grade': overall_grade,
            'overall_grade_point': float(overall_gp),
            'class_rank': class_rank,
            'subjects_count': subjects_count,
            'subject_marks': main_subject_marks,
            'summary_obj': summary_obj
        }
    
    @staticmethod
    def get_grade_from_percentage(percentage, class_group, exam_type):
        """Get grade and grade point from a percentage using the GradeScale table.

        The GradeScale bands are stored in raw marks (e.g. 1-5/FA bands run 0..25),
        so we convert the percentage back to marks against the *actual* ceiling of
        the configured scale for this (class_group, exam_type) rather than a
        hardcoded map. This is the single source of truth for grading.
        """
        try:
            scales = GradeScale.objects.filter(
                class_group=class_group,
                exam_type=exam_type,
            )

            # Ceiling = the top of the highest configured band for this scale.
            ceiling = max((s.max_marks for s in scales), default=0)
            if ceiling <= 0:
                return 'D2', Decimal('3.0')

            marks = (Decimal(str(percentage)) * ceiling) / 100

            grade_scale = scales.filter(
                min_marks__lte=marks,
                max_marks__gte=marks,
            ).order_by('-min_marks').first()

            if grade_scale:
                return grade_scale.grade, grade_scale.grade_point

        except Exception as e:
            print(f"Error getting grade from percentage: {e}")

        # Default fallback (lowest band) when nothing matches
        return 'D2', Decimal('3.0')
    
    @staticmethod
    def calculate_class_rank(student, exam, academic_year, student_total):
        """Calculate student's rank in class for specific exam"""
        # Get all students in the same class
        class_students = StudentProfile.objects.filter(
            student_class=student.student_class
        )
        
        # Get total marks for each student in this exam (main subjects only)
        student_totals = []
        for class_student in class_students:
            total = StudentMark.objects.filter(
                student=class_student,
                exam=exam,
                academic_year=academic_year
            ).filter(
                subject__classsubjectmapping__student_class=student.student_class,
                subject__classsubjectmapping__is_main_subject=True,
                subject__classsubjectmapping__academic_year=academic_year
            ).aggregate(Sum('marks_obtained'))['marks_obtained__sum'] or 0
            
            student_totals.append((class_student.id, float(total)))
        
        # Sort by total marks (descending - highest first)
        student_totals.sort(key=lambda x: x[1], reverse=True)
        
        # Find current student's rank
        for rank, (student_id, total) in enumerate(student_totals, 1):
            if student_id == student.id:
                return rank
        
        return len(student_totals)  # Last rank if not found
    
    @staticmethod
    def get_student_report_card(student_id, academic_year_id):
        """Generate comprehensive report card for a student"""
        try:
            student = StudentProfile.objects.get(id=student_id)
            academic_year = AcademicYear.objects.get(id=academic_year_id)
        except (StudentProfile.DoesNotExist, AcademicYear.DoesNotExist):
            return None
        
        # Get all exams
        exams = Exam.objects.filter(is_active=True).order_by('exam_type', 'order')
        
        # Get all subjects for this student's class
        subjects = Subject.objects.filter(
            classsubjectmapping__student_class=student.student_class,
            classsubjectmapping__academic_year=academic_year
        ).distinct()
        
        # Separate main and optional subjects
        main_subjects = subjects.filter(
            classsubjectmapping__is_main_subject=True,
            classsubjectmapping__student_class=student.student_class
        )
        optional_subjects = subjects.filter(
            classsubjectmapping__is_main_subject=False,
            classsubjectmapping__student_class=student.student_class
        )
        
        # Build report structure
        report = {
            'student': {
                'id': student.id,
                'name': student.user.get_full_name(),
                'roll_number': student.roll_number,
                'class': student.student_class.name,
                'class_group': student.student_class.class_group
            },
            'academic_year': academic_year.name,
            'exams': {},
            'subjects': {
                'main': [],
                'optional': []
            },
            'overall_summary': {}
        }
        
        # Get marks for each exam
        for exam in exams:
            exam_summary = GradingService.calculate_student_exam_summary(
                student_id, exam.id, academic_year_id
            )
            
            if exam_summary:
                report['exams'][exam.name] = {
                    'total_obtained': exam_summary['total_obtained'],
                    'total_max': exam_summary['total_max'],
                    'percentage': exam_summary['percentage'],
                    'overall_grade': exam_summary['overall_grade'],
                    'class_rank': exam_summary['class_rank'],
                    'subjects_count': exam_summary['subjects_count']
                }
        
        # Get subject-wise marks
        all_marks = StudentMark.objects.filter(
            student=student,
            academic_year=academic_year
        ).select_related('subject', 'exam')
        
        # Organize marks by subject
        subject_marks = {}
        for mark in all_marks:
            subject_name = mark.subject.name
            if subject_name not in subject_marks:
                subject_marks[subject_name] = {}
            subject_marks[subject_name][mark.exam.name] = {
                'marks': float(mark.marks_obtained),
                'max_marks': mark.max_marks,
                'grade': mark.grade,
                'grade_point': float(mark.grade_point),
                'is_absent': mark.is_absent
            }
        
        # Add subjects to report
        for subject in main_subjects:
            report['subjects']['main'].append({
                'name': subject.name,
                'code': subject.code,
                'marks': subject_marks.get(subject.name, {})
            })
        
        for subject in optional_subjects:
            report['subjects']['optional'].append({
                'name': subject.name,
                'code': subject.code,
                'marks': subject_marks.get(subject.name, {})
            })
        
        return report
    
    @staticmethod
    def get_class_performance_summary(class_id, exam_id, academic_year_id):
        """Get performance summary for entire class in specific exam"""
        try:
            class_obj = Class.objects.get(id=class_id)
            exam = Exam.objects.get(id=exam_id)
            academic_year = AcademicYear.objects.get(id=academic_year_id)
        except (Class.DoesNotExist, Exam.DoesNotExist, AcademicYear.DoesNotExist):
            return None
        
        # Get all students in class
        students = StudentProfile.objects.filter(student_class=class_obj)
        
        # Get exam summaries for all students
        summaries = StudentExamSummary.objects.filter(
            student__student_class=class_obj,
            exam=exam,
            academic_year=academic_year
        ).select_related('student__user').order_by('-total_marks_obtained')
        
        if not summaries.exists():
            return None
        
        # Calculate class statistics
        total_students = summaries.count()
        avg_percentage = summaries.aggregate(Avg('percentage'))['percentage__avg'] or 0
        highest_marks = summaries.aggregate(models.Max('total_marks_obtained'))['total_marks_obtained__max'] or 0
        lowest_marks = summaries.aggregate(models.Min('total_marks_obtained'))['total_marks_obtained__min'] or 0
        
        # Grade distribution
        grade_distribution = {}
        for summary in summaries:
            grade = summary.overall_grade
            grade_distribution[grade] = grade_distribution.get(grade, 0) + 1
        
        return {
            'class': class_obj.name,
            'exam': exam.name,
            'total_students': total_students,
            'average_percentage': round(avg_percentage, 2),
            'highest_marks': float(highest_marks),
            'lowest_marks': float(lowest_marks),
            'grade_distribution': grade_distribution,
            'student_summaries': [
                {
                    'student_name': summary.student.user.get_full_name(),
                    'roll_number': summary.student.roll_number,
                    'total_marks': float(summary.total_marks_obtained),
                    'percentage': float(summary.percentage),
                    'grade': summary.overall_grade,
                    'rank': summary.class_rank
                }
                for summary in summaries
            ]
        }
