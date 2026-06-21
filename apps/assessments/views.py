from rest_framework import generics, status
from rest_framework.response import Response
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.views import APIView
from django.shortcuts import get_object_or_404
from .models import *
from django.db.models import Sum, Avg, Count, Q, IntegerField
from django.db.models.functions import Cast
from .serializers import *
from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
import json
from .models import *
from .services import GradingService
from apps.students.models import Class, StudentProfile
from decimal import Decimal


@login_required
def marks_entry_sheet(request):
    """Excel-like marks entry interface"""
    classes = Class.objects.all().order_by('name')
    exams = Exam.objects.all().order_by('order')
    academic_year = AcademicYear.objects.filter(is_current=True).first()
    
    context = {
        'classes': classes,
        'exams': exams,
        'academic_year': academic_year,
    }
    return render(request, 'assessments/marks_entry_sheet.html', context)


@csrf_exempt
def get_marks_sheet_data(request):
    """Get students and subjects for selected class and exam"""
    if request.method == 'POST':
        data = json.loads(request.body)
        class_id = data.get('class_id')
        exam_id = data.get('exam_id')
        
        try:
            academic_year = AcademicYear.objects.filter(is_current=True).first()
            selected_class = Class.objects.get(id=class_id)
            selected_exam = Exam.objects.get(id=exam_id)
            class_group = selected_class.class_group
            max_marks = selected_exam.get_max_marks(class_group)
            # Get students in this class - sort numerically by roll_number
            from django.db.models.functions import Cast
            from django.db.models import IntegerField
            
            students = StudentProfile.objects.filter(
                student_class=selected_class
            ).annotate(
                roll_int=Cast('roll_number', IntegerField())
            ).order_by('roll_int')
            
            # Get subjects for this class
            subjects_list = ClassSubjectMapping.objects.filter(
                student_class=selected_class,
                academic_year=academic_year
            ).select_related('subject')
            
            # Custom sorting for subjects
            subject_order = {
                'Telugu': 1,
                'Hindi': 2,
                'English': 3,
                'Mathematics': 4,
                'Maths': 4,
                'Physical Science': 5,
                'Natural Science': 6,
                'Science': 5,
                'Social Studies': 7,
                'Social': 7
            }
            
            def get_subject_priority(mapping):
                name = mapping.subject.name
                # Try to find exact match or partial match
                for key, priority in subject_order.items():
                    if key.lower() in name.lower():
                        return priority
                return 100 # Default priority for other subjects
            
            subjects = sorted(subjects_list, key=get_subject_priority)
            
            # Get existing marks
            existing_marks = {}
            for student in students:
                student_marks = StudentMark.objects.filter(
                    student=student,
                    exam=selected_exam,
                    academic_year=academic_year
                ).select_related('subject')
                
                existing_marks[student.id] = {}
                for mark in student_marks:
                    existing_marks[student.id][mark.subject.id] = {
                        'marks': float(mark.marks_obtained),
                        'grade': mark.grade,
                        'is_absent': mark.is_absent
                    }
            
            return JsonResponse({
                'success': True,
                'students': [
                    {
                        'id': s.id,
                        'name': s.user.get_full_name() or s.user.username,
                        'roll_number': s.roll_number
                    } for s in students
                ],
                'subjects': [
                    {
                        'id': s.subject.id,
                        'name': s.subject.name,
                        'is_main': s.is_main_subject,
                        'max_marks': selected_exam.get_max_marks(class_group, s.subject)
                    } for s in subjects
                ],
                'existing_marks': existing_marks,
                'max_marks': selected_exam.get_max_marks(class_group)
            })
            
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)})


@csrf_exempt 
def save_marks_sheet(request):
    """Save marks from the spreadsheet"""
    if request.method == 'POST':
        data = json.loads(request.body)
        
        try:
            academic_year = AcademicYear.objects.filter(is_current=True).first()
            exam = Exam.objects.get(id=data['exam_id'])
            
            for student_id, subjects_marks in data['marks'].items():
                student = StudentProfile.objects.get(id=student_id)
                class_group = student.student_class.class_group
                
                for subject_id, mark_data in subjects_marks.items():
                    subject = Subject.objects.get(id=subject_id)
                    
                    max_marks = exam.get_max_marks(class_group, subject)
                    # Update or create mark
                    StudentMark.objects.update_or_create(
                        student=student,
                        exam=exam,
                        subject=subject,
                        academic_year=academic_year,
                        defaults={
                            'marks_obtained': Decimal(str(mark_data)) if mark_data else 0,
                            'max_marks': max_marks,
                            'entered_by': request.user if request.user.is_authenticated else None
                        }
                    )
            
            # Update summaries for all students in this class/exam
            academic_year = AcademicYear.objects.filter(is_current=True).first()
            exam = Exam.objects.get(id=data['exam_id'])
            student_ids = data['marks'].keys()
            
            for s_id in student_ids:
                student = StudentProfile.objects.get(id=s_id)
                # Calculate summary
                marks = StudentMark.objects.filter(student=student, exam=exam, academic_year=academic_year)
                if marks.exists():
                    total_obtained = sum(float(m.marks_obtained) for m in marks)
                    total_max = sum(m.max_marks for m in marks)
                    percentage = (total_obtained / total_max * 100) if total_max > 0 else 0
                    
                    StudentExamSummary.objects.update_or_create(
                        student=student,
                        exam=exam,
                        academic_year=academic_year,
                        defaults={
                            'total_marks_obtained': total_obtained,
                            'total_max_marks': total_max,
                            'percentage': percentage,
                            'subjects_count': marks.count()
                        }
                    )

            return JsonResponse({'success': True, 'message': 'Marks saved and summaries updated successfully'})
            
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)})


# ✅ UPDATED: Database-driven class listing
@api_view(['GET'])
@permission_classes([AllowAny])
def get_class_results(request):
    """Get exam results for all students in a class"""
    class_id = request.query_params.get('class_id')
    exam_id = request.query_params.get('exam_id')
    
    if not class_id or not exam_id:
        return Response({'error': 'class_id and exam_id required'}, status=400)
        
    summaries = StudentExamSummary.objects.filter(
        student__student_class_id=class_id,
        exam_id=exam_id
    ).select_related('student')
    
    results = []
    for s in summaries:
        results.append({
            'studentName': s.student.name,
            'rollNo': s.student.roll_number,
            'totalObtained': s.total_marks_obtained,
            'totalMax': s.total_max_marks,
            'percentage': s.percentage,
            'subjectCount': s.subjects_count
        })
        
    return Response({'results': results})

@api_view(['POST'])
@permission_classes([AllowAny])
def initialize_class_orders(request):
    """Utility to set default class orders with exact and partial matching"""
    order_map = {
        'Nursery': 1, 'LKG': 2, 'UKG': 3,
        '1st': 10, '2nd': 20, '3rd': 30, '4th': 40, '5th': 50,
        '6th': 60, '7th': 70, '8th': 80, '9th': 90, '10th': 100,
        # Common variations
        '1': 10, '2': 20, '3': 30, '4': 40, '5': 50,
        '6': 60, '7': 70, '8': 80, '9': 90, '10': 100
    }
    updated = 0
    for name, order in order_map.items():
        count = Class.objects.filter(name__icontains=name).update(order=order)
        updated += count
    return Response({'success': True, 'updated': updated})

class ClassListAPIView(APIView):
    """GET /api/assessments/classes/ - List all classes with student counts"""
    permission_classes = [AllowAny]
    
    def get(self, request):
        # Now relies on Meta: ordering = ['order', 'name']
        classes = Class.objects.all()
        
        classes_data = []
        for cls in classes:
            classes_data.append({
                'id': str(cls.id),           # ✅ Use database ID (always unique)
                'name': cls.name,            # ✅ Use actual class name
                'displayName': cls.name,     # ✅ Display actual name
                'studentCount': cls.studentprofile_set.count()
            })
        
        return Response({'classes': classes_data})


class ExamListAPIView(APIView):
    """GET /api/assessments/exams/ - List all exams"""
    permission_classes = [AllowAny]
    
    def get(self, request):
        exams = Exam.objects.all().order_by('order')
        return Response({
            'exams': [{
                'id': e.id,
                'name': e.name,
                'type': e.exam_type,
                'order': e.order
            } for e in exams]
        })


class SubjectListAPIView(APIView):
    """GET /api/assessments/subjects/ - List all subjects"""
    permission_classes = [AllowAny]
    
    def get(self, request):
        subjects = Subject.objects.all().order_by('name')
        return Response({
            'subjects': [{
                'id': s.id,
                'name': s.name,
                'code': s.code
            } for s in subjects]
        })


# ✅ UPDATED: Database-driven student listing
class StudentListAPIView(APIView):
    """GET /api/assessments/students/?class_id=X - Get students by class"""
    permission_classes = [AllowAny]
    
    def get(self, request):
        class_id = request.query_params.get('class_id')
        if not class_id:
            return Response({'error': 'Class ID is required'}, status=400)
        
        try:
            # ✅ Use database ID directly (no mapping needed)
            selected_class = Class.objects.get(id=class_id)
            
            students = StudentProfile.objects.filter(
                student_class=selected_class
            ).annotate(
                roll_int=Cast('roll_number', output_field=IntegerField())
            ).order_by('roll_int')
            
            # Format students data
            students_data = []
            for student in students:
                students_data.append({
                    'id': str(student.id),       # ✅ Use student's actual database ID
                    'rollNo': str(student.roll_number),
                    'name': student.user.get_full_name() or f"Student {student.roll_number}",
                    'className': selected_class.name
                })
            
            return Response({
                'students': students_data,
                'className': selected_class.name
            })
            
        except Class.DoesNotExist:
            return Response({'error': 'Class not found'}, status=404)


# ✅ UPDATED: Database-driven student marks
class StudentMarksDetailAPIView(APIView):
    """GET /api/assessments/student-marks/{student_id}/ - Get REAL student marks"""
    permission_classes = [AllowAny]
    
    def get(self, request, student_id):
        try:
            # ✅ Use student ID directly (no complex parsing needed)
            student = StudentProfile.objects.get(id=student_id)
            
            academic_year = AcademicYear.objects.filter(is_current=True).first()
            if not academic_year:
                return Response({'error': 'No active academic year found'}, status=400)

            response_data = {
                'student': {
                    'id': str(student.id),
                    'name': student.user.get_full_name() or f"Student {student.roll_number}",
                    'rollNo': str(student.roll_number).zfill(2) if isinstance(student.roll_number, int) or str(student.roll_number).isdigit() else str(student.roll_number),
                    'className': student.student_class.name,
                    'classId': str(student.student_class.id) if student.student_class else None,
                },
                'subjects': self.get_subjects_data(student, academic_year),
                'termSummaries': self.get_term_summaries(student, academic_year),
                'classConfig': self.get_class_config(student.student_class),
                'exams': self.get_exams_meta(),
            }

            return Response(response_data)

        except StudentProfile.DoesNotExist:
            return Response({'error': 'Student not found'}, status=404)
        except Exception as e:
            return Response({'error': str(e)}, status=500)
    
    def get_exams_meta(self):
        """Return exam id/name/key list so the editable grid can map cells -> exams."""
        exams_meta = []
        for exam_name in ['FA1', 'FA2', 'FA3', 'FA4', 'SA1', 'SA2']:
            exam = Exam.objects.filter(name=exam_name).first()
            if exam:
                exams_meta.append({
                    'id': exam.id,
                    'name': exam.name,
                    'key': exam.name.lower(),  # matches subject_data keys (fa1, sa1, ...)
                })
        return exams_meta

    def get_subjects_data(self, student, academic_year):
        """Get REAL subject marks data from database"""
        # Get all marks for this student
        marks_queryset = StudentMark.objects.filter(
            student=student,
            academic_year=academic_year
        ).select_related('subject', 'exam')

        # Get all subjects for this class
        class_subjects = ClassSubjectMapping.objects.filter(
            student_class=student.student_class,
            academic_year=academic_year
        ).select_related('subject')

        class_group = student.student_class.class_group
        exams = list(Exam.objects.filter(name__in=['FA1', 'FA2', 'FA3', 'FA4', 'SA1', 'SA2']))
        exams_by_key = {e.name.lower(): e for e in exams}

        subjects_data = []

        for class_subject in class_subjects:
            subject = class_subject.subject

            # `id` lets the editable grid map a cell -> (subject, exam).
            # `examCaps` carries the max marks for every term even when no mark
            # exists yet, so the editor can clamp input. We deliberately keep the
            # per-cell `maxMarks` at 0 when empty so the read-only table still
            # renders "N/A" for terms with no marks.
            subject_data = {
                'id': subject.id,
                'name': subject.name,
                'fa1': {'marks': 0, 'grade': 'N/A', 'maxMarks': 0},
                'fa2': {'marks': 0, 'grade': 'N/A', 'maxMarks': 0},
                'fa3': {'marks': 0, 'grade': 'N/A', 'maxMarks': 0},
                'fa4': {'marks': 0, 'grade': 'N/A', 'maxMarks': 0},
                'sa1': {'marks': 0, 'grade': 'N/A', 'maxMarks': 0},
                'sa2': {'marks': 0, 'grade': 'N/A', 'maxMarks': 0},
                'examCaps': {
                    key: (exams_by_key[key].get_max_marks(class_group, subject) if key in exams_by_key else 0)
                    for key in ['fa1', 'fa2', 'fa3', 'fa4', 'sa1', 'sa2']
                },
            }

            # Fill with REAL marks data
            subject_marks = marks_queryset.filter(subject=subject)
            for mark in subject_marks:
                exam_key = mark.exam.name.lower()
                if exam_key in subject_data:
                    subject_data[exam_key] = {
                        'marks': float(mark.marks_obtained),
                        'grade': mark.grade,
                        'maxMarks': mark.max_marks
                    }

            subjects_data.append(subject_data)

        return subjects_data
    
    def get_term_summaries(self, student, academic_year):
        """Calculate REAL term summaries from database"""
        summaries = []
        
        for exam_name in ['FA1', 'FA2', 'FA3', 'FA4', 'SA1', 'SA2']:
            try:
                exam = Exam.objects.get(name=exam_name)
                
                # Get marks for this exam
                exam_marks = StudentMark.objects.filter(
                    student=student,
                    exam=exam,
                    academic_year=academic_year
                )
                
                if exam_marks.exists():
                    total_marks = sum(float(m.marks_obtained) for m in exam_marks)
                    max_marks = sum(m.max_marks for m in exam_marks)
                    percentage = (total_marks / max_marks * 100) if max_marks > 0 else 0
                    
                    # Calculate grade from the GradeScale table (single source of truth)
                    grade = self.calculate_overall_grade(
                        percentage,
                        student.student_class.class_group,
                        exam.exam_type,
                    )

                    # Calculate class rank (simplified - you can enhance this)
                    class_rank = self.calculate_class_rank(student, exam, academic_year)
                    
                    summaries.append({
                        'term': exam_name.replace('FA', 'FA-').replace('SA', 'SA-'),
                        'totalMarks': int(total_marks),
                        'maxMarks': max_marks,
                        'percentage': round(percentage, 2),
                        'grade': grade,
                        'classRank': class_rank,
                        'totalStudents': student.student_class.studentprofile_set.count()
                    })
                
            except Exam.DoesNotExist:
                continue
        
        return summaries
    
    def calculate_overall_grade(self, percentage, class_group, exam_type):
        """Overall grade from the GradeScale table (single source of truth)."""
        grade, _ = GradingService.get_grade_from_percentage(percentage, class_group, exam_type)
        return grade
    
    def calculate_class_rank(self, student, exam, academic_year):
        """Calculate student's rank in class for this exam"""
        # This is a simplified ranking - you can enhance it
        # Get all students' totals for this exam in this class
        class_students = StudentProfile.objects.filter(student_class=student.student_class)
        
        student_totals = []
        for cls_student in class_students:
            cls_marks = StudentMark.objects.filter(
                student=cls_student,
                exam=exam,
                academic_year=academic_year
            )
            if cls_marks.exists():
                total = sum(float(m.marks_obtained) for m in cls_marks)
                student_totals.append((cls_student.id, total))
        
        # Sort by total marks (highest first)
        student_totals.sort(key=lambda x: x[1], reverse=True)
        
        # Find rank
        for rank, (student_id, total) in enumerate(student_totals, 1):
            if student_id == student.id:
                return rank
        
        return 1  # Default rank
    
    def get_class_config(self, student_class):
        """Get class configuration based on class group"""
        class_group = student_class.class_group
        
        # Map to frontend class config format
        if class_group == 'pre':
            return {
                'faMarks': 50,
                'saMarks': 100,
                'excludeFromTotal': ['Color'],
                'gradingScale': 'lower'
            }
        elif class_group in ['1-2', '1-5', '3-5']:
            return {
                'faMarks': 25,
                'saMarks': 100,
                'excludeFromTotal': ['GK', 'Computer'],
                'gradingScale': 'lower'
            }
        else:  # 6-10
            return {
                'faMarks': 50,
                'saMarks': 100,
                'excludeFromTotal': ['GK', 'Computer'],
                'gradingScale': 'higher'
            }


@api_view(['POST'])
@permission_classes([AllowAny])
def teacher_login_api(request):
    """POST /api/assessments/auth/login/ - Teacher authentication"""
    email = request.data.get('email')
    password = request.data.get('password')
    
    if not email or not password:
        return Response({'error': 'Email and password required'}, status=400)
    
    # TODO: Implement real authentication with your User model
    # For now, returning success for any valid email/password
    if email and password:
        return Response({
            'teacher': {
                'id': '1',
                'name': 'Teacher Name',  # Get from your User model
                'email': email
            }
        })
    
    return Response({'error': 'Invalid credentials'}, status=401)