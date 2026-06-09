from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from django.db import transaction
from django.db.models import Q
from django.db.models.functions import Cast
from django.db.models import IntegerField
from django.utils.crypto import get_random_string

from .models import StudentProfile
from apps.students.models import Class
from apps.users.models import User


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def search_students(request):
    query = request.GET.get('q', '')
    if len(query) < 2:
        return Response({'success': False, 'message': 'Query too short'}, status=400)

    students = StudentProfile.objects.filter(
        Q(user__first_name__icontains=query) |
        Q(user__last_name__icontains=query) |
        Q(roll_number__icontains=query)
    ).select_related('user', 'student_class')[:10]

    results = []
    for s in students:
        results.append({
            'id': s.id,
            'full_name': f"{s.user.first_name} {s.user.last_name}",
            'roll_number': s.roll_number,
            'class_name': s.student_class.name if s.student_class else 'N/A'
        })

    return Response({'success': True, 'students': results})


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _split_name(full_name):
    """Split a single 'name' string into (first_name, last_name)."""
    parts = (full_name or '').strip().split()
    if not parts:
        return '', ''
    if len(parts) == 1:
        return parts[0], ''
    return parts[0], ' '.join(parts[1:])


def _generate_username(class_obj, roll_number):
    """Build a unique, predictable username for a student User."""
    class_slug = (class_obj.name or 'class').lower().replace(' ', '')
    base = f"s_{class_slug}_{roll_number}".strip('_')
    username = base
    counter = 1
    while User.objects.filter(username=username).exists():
        username = f"{base}_{counter}"
        counter += 1
    return username


def _serialize_student(student):
    return {
        'id': student.id,
        'name': student.user.get_full_name() or student.user.username,
        'roll_number': student.roll_number,
        'father_name': student.father_name,
        'mother_name': student.mother_name,
        'parent_phone': student.father_phone or student.mother_phone,
        'parent_email': student.parent_email,
        'address': student.address,
        'gender': student.gender,
    }


def _create_student(class_obj, payload):
    """Create a User + StudentProfile from a frontend payload dict.

    Returns the created StudentProfile. Raises ValueError on validation issues.
    """
    name = payload.get('name', '')
    roll_number = str(payload.get('roll_number', '')).strip()
    if not roll_number:
        raise ValueError('Roll number is required')

    # Roll numbers must be unique within a class
    if StudentProfile.objects.filter(student_class=class_obj, roll_number=roll_number).exists():
        raise ValueError(f'Roll number {roll_number} already exists in {class_obj.name}')

    first_name, last_name = _split_name(name)
    parent_phone = str(payload.get('parent_phone', '')).strip()

    user = User.objects.create_user(
        username=_generate_username(class_obj, roll_number),
        password=get_random_string(20),
        first_name=first_name,
        last_name=last_name,
        email=payload.get('parent_email', '') or '',
        role='student',
    )

    student = StudentProfile.objects.create(
        user=user,
        student_class=class_obj,
        roll_number=roll_number,
        father_name=payload.get('father_name', '') or '',
        mother_name=payload.get('mother_name', '') or '',
        father_phone=parent_phone,
        mother_phone=parent_phone,
        parent_email=payload.get('parent_email', '') or '',
        address=payload.get('address', '') or '',
        gender=payload.get('gender', '') or '',
    )
    return student


# ---------------------------------------------------------------------------
# Student management endpoints (used by the teacher "Manage Students" page)
# ---------------------------------------------------------------------------

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def class_students(request, class_id):
    """GET /api/students/class/<class_id>/ - list students in a class."""
    try:
        class_obj = Class.objects.get(id=class_id)
    except Class.DoesNotExist:
        return Response({'success': False, 'message': 'Class not found'}, status=404)

    students = StudentProfile.objects.filter(
        student_class=class_obj
    ).select_related('user').annotate(
        roll_int=Cast('roll_number', output_field=IntegerField())
    ).order_by('roll_int')

    return Response({
        'success': True,
        'class_name': class_obj.name,
        'students': [_serialize_student(s) for s in students],
    })


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def add_student(request):
    """POST /api/students/add/ - add a single student to a class."""
    data = request.data
    class_id = data.get('class_id')
    if not class_id:
        return Response({'success': False, 'message': 'class_id is required'}, status=400)

    try:
        class_obj = Class.objects.get(id=class_id)
    except Class.DoesNotExist:
        return Response({'success': False, 'message': 'Class not found'}, status=404)

    try:
        with transaction.atomic():
            student = _create_student(class_obj, data)
    except ValueError as e:
        return Response({'success': False, 'message': str(e)}, status=400)
    except Exception as e:
        return Response({'success': False, 'message': f'Error: {str(e)}'}, status=500)

    return Response({
        'success': True,
        'message': 'Student added successfully',
        'student': _serialize_student(student),
    })


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def add_students_bulk(request):
    """POST /api/students/add-bulk/ - add many students at once (CSV import)."""
    data = request.data
    class_id = data.get('class_id')
    students_payload = data.get('students', [])

    if not class_id:
        return Response({'success': False, 'message': 'class_id is required'}, status=400)
    if not students_payload:
        return Response({'success': False, 'message': 'No students provided'}, status=400)

    try:
        class_obj = Class.objects.get(id=class_id)
    except Class.DoesNotExist:
        return Response({'success': False, 'message': 'Class not found'}, status=404)

    created = 0
    errors = []
    for idx, payload in enumerate(students_payload):
        try:
            with transaction.atomic():
                _create_student(class_obj, payload)
            created += 1
        except ValueError as e:
            errors.append({'row': idx + 1, 'roll_number': payload.get('roll_number'), 'error': str(e)})
        except Exception as e:
            errors.append({'row': idx + 1, 'roll_number': payload.get('roll_number'), 'error': str(e)})

    return Response({
        'success': True,
        'message': f'{created} students added' + (f', {len(errors)} skipped' if errors else ''),
        'created': created,
        'errors': errors,
    })


@api_view(['DELETE'])
@permission_classes([IsAuthenticated])
def delete_student(request, student_id):
    """DELETE /api/students/<student_id>/delete/ - remove a student (and their User)."""
    try:
        student = StudentProfile.objects.select_related('user').get(id=student_id)
    except StudentProfile.DoesNotExist:
        return Response({'success': False, 'message': 'Student not found'}, status=404)

    name = student.user.get_full_name() or student.user.username
    user = student.user
    student.delete()
    user.delete()

    return Response({'success': True, 'message': f'{name} removed successfully'})
