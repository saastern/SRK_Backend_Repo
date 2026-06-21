from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status
from django.shortcuts import get_object_or_404
from django.db import transaction
from datetime import datetime
from decimal import Decimal
from .models import *
from .services import GradingService
from apps.students.models import Class

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_marks_entry_form_data(request):
    """Get all data needed for marks entry form in one API call"""
    try:
        class_id = request.GET.get('class_id')
        exam_id = request.GET.get('exam_id')
        subject_id = request.GET.get('subject_id')
        
        if not class_id or not exam_id:
            return Response({
                'success': False,
                'message': 'class_id and exam_id are required'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # Get current academic year
        academic_year = AcademicYear.objects.filter(is_current=True).first()
        if not academic_year:
            return Response({
                'success': False,
                'message': 'No current academic year found'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # Get class and exam info
        class_obj = get_object_or_404(Class, id=class_id)
        exam = get_object_or_404(Exam, id=exam_id)
        
        # Get students in this class
        students = StudentProfile.objects.filter(
            student_class=class_obj
        ).select_related('user').order_by('roll_number')
        
        # Get subjects for this class
        subject_mappings = ClassSubjectMapping.objects.filter(
            student_class=class_obj,
            academic_year=academic_year
        ).select_related('subject')
        
        if subject_id:
            subject_mappings = subject_mappings.filter(subject_id=subject_id)
        
        subjects = [mapping.subject for mapping in subject_mappings]
        
        # Get existing marks
        existing_marks = {}
        if subjects:
            marks_qs = StudentMark.objects.filter(
                student__student_class=class_obj,
                exam=exam,
                subject__in=subjects,
                academic_year=academic_year
            )
            
            for mark in marks_qs:
                student_id = str(mark.student.id)
                subject_id_str = str(mark.subject.id)
                
                if student_id not in existing_marks:
                    existing_marks[student_id] = {}
                existing_marks[student_id][subject_id_str] = {
                    'marks': float(mark.marks_obtained),
                    'grade': mark.grade,
                    'is_absent': mark.is_absent
                }
        
        return Response({
            'success': True,
            'form_data': {
                'class': {
                    'id': class_obj.id,
                    'name': class_obj.name,
                    'class_group': class_obj.class_group
                },
                'exam': {
                    'id': exam.id,
                    'name': exam.name,
                    'max_marks': exam.get_max_marks(class_obj.class_group)
                },
                'subjects': [
                    {
                        'id': subj.id,
                        'name': subj.name,
                        'is_main': next((m.is_main_subject for m in subject_mappings if m.subject == subj), True)
                    }
                    for subj in subjects
                ],
                'students': [
                    {
                        'id': student.id,
                        'name': student.user.get_full_name(),
                        'roll_number': student.roll_number
                    }
                    for student in students
                ],
                'existing_marks': existing_marks,
                'academic_year_id': academic_year.id
            }
        })
        
    except Exception as e:
        return Response({
            'success': False,
            'message': f'Error: {str(e)}'
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def enter_marks(request):
    """Enter marks for students"""
    try:
        data = request.data
        subject_id = data.get('subject_id')
        exam_id = data.get('exam_id')
        academic_year_id = data.get('academic_year_id')
        marks_data = data.get('marks', [])
        
        # Get objects
        subject = get_object_or_404(Subject, id=subject_id)
        exam = get_object_or_404(Exam, id=exam_id)
        academic_year = get_object_or_404(AcademicYear, id=academic_year_id)
        
        saved_count = 0
        
        for mark_entry in marks_data:
            student_id = mark_entry.get('student_id')
            marks = mark_entry.get('marks', 0)
            is_absent = mark_entry.get('is_absent', False)
            
            student = get_object_or_404(StudentProfile, id=student_id)
            max_marks = exam.get_max_marks(student.student_class.class_group)
            
            # Create or update marks
            student_mark, created = StudentMark.objects.update_or_create(
                student=student,
                subject=subject,
                exam=exam,
                academic_year=academic_year,
                defaults={
                    'marks_obtained': marks if not is_absent else 0,
                    'max_marks': max_marks,
                    'is_absent': is_absent,
                    'entered_by': request.user
                }
            )
            saved_count += 1
            
            # Calculate summary
            GradingService.calculate_student_exam_summary(
                student_id, exam_id, academic_year_id
            )
        
        return Response({
            'success': True,
            'message': f'Marks saved for {saved_count} students'
        })
        
    except Exception as e:
        return Response({
            'success': False,
            'message': f'Error: {str(e)}'
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

# Preferred subject display order for the marks grid
SUBJECT_ORDER = {
    'telugu': 1, 'hindi': 2, 'english': 3,
    'mathematics': 4, 'maths': 4,
    'physical science': 5, 'natural science': 6, 'science': 5,
    'social studies': 7, 'social': 7,
}


def _subject_priority(name):
    lower = (name or '').lower()
    for key, priority in SUBJECT_ORDER.items():
        if key in lower:
            return priority
    return 100


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_class_marks_grid(request):
    """GET /api/assessments/marks-grid/?class_id=X&exam_id=Y

    Returns the full editable grid (students x subjects) for a class + exam,
    including any existing marks. Used by the React class-grid entry screen.
    """
    try:
        class_id = request.GET.get('class_id')
        exam_id = request.GET.get('exam_id')

        if not class_id or not exam_id:
            return Response({
                'success': False,
                'message': 'class_id and exam_id are required'
            }, status=status.HTTP_400_BAD_REQUEST)

        academic_year = AcademicYear.objects.filter(is_current=True).first()
        if not academic_year:
            return Response({
                'success': False,
                'message': 'No current academic year found'
            }, status=status.HTTP_400_BAD_REQUEST)

        class_obj = get_object_or_404(Class, id=class_id)
        exam = get_object_or_404(Exam, id=exam_id)
        class_group = class_obj.class_group

        # Students sorted numerically by roll number
        from django.db.models.functions import Cast
        from django.db.models import IntegerField
        students = StudentProfile.objects.filter(
            student_class=class_obj
        ).select_related('user').annotate(
            roll_int=Cast('roll_number', output_field=IntegerField())
        ).order_by('roll_int')

        # Subjects for this class, in display order
        subject_mappings = list(ClassSubjectMapping.objects.filter(
            student_class=class_obj,
            academic_year=academic_year
        ).select_related('subject'))
        subject_mappings.sort(key=lambda m: _subject_priority(m.subject.name))
        subjects = [m.subject for m in subject_mappings]

        # Existing marks: { student_id: { subject_id: {marks, grade, is_absent} } }
        existing_marks = {}
        if subjects:
            marks_qs = StudentMark.objects.filter(
                student__student_class=class_obj,
                exam=exam,
                subject__in=subjects,
                academic_year=academic_year
            )
            for mark in marks_qs:
                sid = str(mark.student_id)
                existing_marks.setdefault(sid, {})[str(mark.subject_id)] = {
                    'marks': float(mark.marks_obtained),
                    'grade': mark.grade,
                    'is_absent': mark.is_absent,
                }

        return Response({
            'success': True,
            'academic_year_id': academic_year.id,
            'class': {'id': class_obj.id, 'name': class_obj.name, 'class_group': class_group},
            'exam': {'id': exam.id, 'name': exam.name, 'exam_type': exam.exam_type},
            'subjects': [
                {
                    'id': m.subject.id,
                    'name': m.subject.name,
                    'is_main': m.is_main_subject,
                    'max_marks': exam.get_max_marks(class_group, m.subject),
                }
                for m in subject_mappings
            ],
            'students': [
                {
                    'id': s.id,
                    'name': s.user.get_full_name() or f'Student {s.roll_number}',
                    'roll_number': s.roll_number,
                }
                for s in students
            ],
            'existing_marks': existing_marks,
        })

    except Exception as e:
        return Response({
            'success': False,
            'message': f'Error: {str(e)}'
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def save_class_marks_grid(request):
    """POST /api/assessments/marks-grid/save/

    Body: {
      "class_id": X, "exam_id": Y,
      "marks": { "<student_id>": { "<subject_id>": {"marks": 18, "is_absent": false}, ... }, ... }
    }
    Saves every cell, recomputes grades (via model.save) and per-student summaries.
    """
    try:
        data = request.data
        exam_id = data.get('exam_id')
        marks_map = data.get('marks', {})

        if not exam_id:
            return Response({'success': False, 'message': 'exam_id is required'},
                            status=status.HTTP_400_BAD_REQUEST)

        academic_year = AcademicYear.objects.filter(is_current=True).first()
        if not academic_year:
            return Response({'success': False, 'message': 'No current academic year found'},
                            status=status.HTTP_400_BAD_REQUEST)

        exam = get_object_or_404(Exam, id=exam_id)

        saved_cells = 0
        for student_id, subjects_marks in marks_map.items():
            student = get_object_or_404(StudentProfile, id=student_id)
            class_group = student.student_class.class_group

            for subject_id, cell in subjects_marks.items():
                subject = get_object_or_404(Subject, id=subject_id)

                # A cell can be a bare number or an object {marks, is_absent}
                if isinstance(cell, dict):
                    raw_marks = cell.get('marks')
                    is_absent = cell.get('is_absent', False)
                else:
                    raw_marks = cell
                    is_absent = False

                # Skip empty cells so we don't overwrite with zeros unintentionally
                if not is_absent and (raw_marks is None or raw_marks == ''):
                    continue

                max_marks = exam.get_max_marks(class_group, subject)
                marks_value = Decimal('0') if is_absent else Decimal(str(raw_marks))

                StudentMark.objects.update_or_create(
                    student=student,
                    subject=subject,
                    exam=exam,
                    academic_year=academic_year,
                    defaults={
                        'marks_obtained': marks_value,
                        'max_marks': max_marks,
                        'is_absent': is_absent,
                        'entered_by': request.user,
                    }
                )
                saved_cells += 1

            # Recompute summary once per student
            GradingService.calculate_student_exam_summary(
                student.id, exam.id, academic_year.id
            )

        return Response({
            'success': True,
            'message': f'Saved {saved_cells} marks',
            'saved': saved_cells,
        })

    except Exception as e:
        return Response({
            'success': False,
            'message': f'Error: {str(e)}'
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
def get_classes_and_exams(request):
    """Get classes and exams for dropdowns"""
    classes = Class.objects.all() # Rely on Meta ordering [order, name]
    exams = Exam.objects.filter(is_active=True).order_by('exam_type', 'order')
    
    return Response({
        'success': True,
        'data': {
            'classes': [
                {'id': cls.id, 'name': cls.name, 'class_group': cls.class_group}
                for cls in classes
            ],
            'exams': [
                {'id': exam.id, 'name': exam.name, 'exam_type': exam.exam_type}
                for exam in exams
            ]
        }
    })
@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_student_marks(request, student_id, exam_id):
    """Get all marks for a student with overall grade and class rank"""
    try:
        academic_year = AcademicYear.objects.filter(is_current=True).first()
        student = StudentProfile.objects.get(id=student_id)
        
        # Get student's marks
        marks = StudentMark.objects.filter(
            student_id=student_id,
            exam_id=exam_id,
            academic_year=academic_year
        ).select_related('subject')
        
        total_marks = 0
        max_marks = 0
        marks_data = []
        
        for mark in marks:
            marks_data.append({
                'subject': mark.subject.name,
                'marks_obtained': float(mark.marks_obtained),
                'max_marks': mark.max_marks,
                'grade': mark.grade,
                'grade_point': float(mark.grade_point),
                'is_absent': mark.is_absent
            })
            total_marks += mark.marks_obtained
            max_marks += mark.max_marks
        
        percentage = (total_marks / max_marks * 100) if max_marks > 0 else 0

        # Overall grade from the GradeScale table (single source of truth)
        exam_obj = Exam.objects.filter(id=exam_id).first()
        exam_type = exam_obj.exam_type if exam_obj else 'SA'
        overall_grade, overall_gp = GradingService.get_grade_from_percentage(
            percentage, student.student_class.class_group, exam_type
        )
        overall_gpa = float(overall_gp)
        
        # Calculate class rank
        from django.db.models import Sum, F
        class_students = StudentProfile.objects.filter(
            student_class=student.student_class
        ).values('id')
        
        # Get total marks for all students in the same class and exam
        student_totals = []
        for class_student in class_students:
            student_marks_sum = StudentMark.objects.filter(
                student_id=class_student['id'],
                exam_id=exam_id,
                academic_year=academic_year
            ).aggregate(total=Sum('marks_obtained'))['total'] or 0
            
            student_totals.append({
                'student_id': class_student['id'],
                'total_marks': student_marks_sum
            })
        
        # Sort by total marks (descending) to get ranks
        student_totals.sort(key=lambda x: x['total_marks'], reverse=True)
        
        # Find current student's rank
        current_rank = 1
        for i, student_total in enumerate(student_totals, 1):
            if student_total['student_id'] == student_id:
                current_rank = i
                break
        
        return Response({
            'success': True,
            'student_id': student_id,
            'student_name': student.user.get_full_name() or student.user.username,
            'class_name': student.student_class.name,
            'exam_id': exam_id,
            'marks': marks_data,
            'summary': {
                'total_marks_obtained': float(total_marks),
                'total_max_marks': max_marks,
                'percentage': round(percentage, 2),
                'overall_grade': overall_grade,
                'overall_gpa': overall_gpa,
                'class_rank': current_rank,
                'total_students_in_class': len(student_totals),
                'total_subjects': len(marks_data)
            }
        })
        
    except Exception as e:
        return Response({
            'success': False,
            'message': str(e)
        }, status=500)


# ---------------------------------------------------------------------------
# Grade scale configuration (Settings -> Grade Configuration)
# ---------------------------------------------------------------------------

GRADE_CLASS_GROUPS = ['pre', '1-5', '6-10']
GRADE_EXAM_TYPES = ['FA', 'SA']


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_grade_scales(request):
    """GET /api/assessments/grade-scales/?class_group=1-5&exam_type=FA

    Returns the ordered grade bands for a (class_group, exam_type) plus the
    available option lists for the dropdowns.
    """
    class_group = request.GET.get('class_group')
    exam_type = request.GET.get('exam_type')

    bands = []
    if class_group and exam_type:
        qs = GradeScale.objects.filter(
            class_group=class_group, exam_type=exam_type
        ).order_by('-min_marks')
        bands = [
            {
                'id': s.id,
                'min_marks': s.min_marks,
                'max_marks': s.max_marks,
                'grade': s.grade,
                'grade_point': float(s.grade_point),
            }
            for s in qs
        ]

    return Response({
        'success': True,
        'class_groups': GRADE_CLASS_GROUPS,
        'exam_types': GRADE_EXAM_TYPES,
        'bands': bands,
    })


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def save_grade_scales(request):
    """POST /api/assessments/grade-scales/save/

    Body: { class_group, exam_type, bands: [{min_marks, max_marks, grade, grade_point}] }
    Replace-all within the (class_group, exam_type): validate, delete existing,
    recreate. Bands must be non-overlapping and start at 0.
    """
    data = request.data
    class_group = data.get('class_group')
    exam_type = data.get('exam_type')
    bands = data.get('bands', [])

    if class_group not in GRADE_CLASS_GROUPS:
        return Response({'success': False, 'message': 'Invalid class_group'},
                        status=status.HTTP_400_BAD_REQUEST)
    if exam_type not in GRADE_EXAM_TYPES:
        return Response({'success': False, 'message': 'Invalid exam_type'},
                        status=status.HTTP_400_BAD_REQUEST)
    if not bands:
        return Response({'success': False, 'message': 'At least one band is required'},
                        status=status.HTTP_400_BAD_REQUEST)

    # Normalise + validate each band
    cleaned = []
    for i, b in enumerate(bands):
        try:
            min_m = int(b['min_marks'])
            max_m = int(b['max_marks'])
            grade = str(b['grade']).strip()
            gp = Decimal(str(b['grade_point']))
        except (KeyError, ValueError, TypeError):
            return Response({'success': False, 'message': f'Band {i + 1} has invalid values'},
                            status=status.HTTP_400_BAD_REQUEST)
        if not grade:
            return Response({'success': False, 'message': f'Band {i + 1} is missing a grade label'},
                            status=status.HTTP_400_BAD_REQUEST)
        if min_m > max_m:
            return Response({'success': False, 'message': f'Band {grade}: min cannot exceed max'},
                            status=status.HTTP_400_BAD_REQUEST)
        cleaned.append({'min': min_m, 'max': max_m, 'grade': grade, 'gp': gp})

    # Check for overlaps and that the lowest band starts at 0
    ordered = sorted(cleaned, key=lambda x: x['min'])
    if ordered[0]['min'] != 0:
        return Response({'success': False, 'message': 'The lowest band must start at 0'},
                        status=status.HTTP_400_BAD_REQUEST)
    for prev, nxt in zip(ordered, ordered[1:]):
        if nxt['min'] <= prev['max']:
            return Response({
                'success': False,
                'message': f"Bands overlap: {prev['grade']} (..{prev['max']}) and {nxt['grade']} ({nxt['min']}..)",
            }, status=status.HTTP_400_BAD_REQUEST)

    try:
        with transaction.atomic():
            GradeScale.objects.filter(
                class_group=class_group, exam_type=exam_type
            ).delete()
            GradeScale.objects.bulk_create([
                GradeScale(
                    class_group=class_group,
                    exam_type=exam_type,
                    min_marks=c['min'],
                    max_marks=c['max'],
                    grade=c['grade'],
                    grade_point=c['gp'],
                )
                for c in cleaned
            ])
    except Exception as e:
        return Response({'success': False, 'message': f'Error: {str(e)}'},
                        status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    return Response({
        'success': True,
        'message': f'Saved {len(cleaned)} grade bands for {class_group} / {exam_type}',
    })
