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
from apps.assessments.models import AcademicYear, ClassSubjectMapping


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


# ---------------------------------------------------------------------------
# Promotion / year rollover (Settings -> Promote Students)
# ---------------------------------------------------------------------------

def _ordered_classes():
    """All classes ordered by their promotion order (lowest -> highest)."""
    return list(Class.objects.all().order_by('order', 'name'))


def _next_class_map(classes):
    """Map each class -> the next-higher class (None for the final class)."""
    mapping = {}
    for i, cls in enumerate(classes):
        mapping[cls.id] = classes[i + 1] if i + 1 < len(classes) else None
    return mapping


def _normalize_class_name(name):
    """Lowercase and strip dots/spaces so 'L.K.G' -> 'lkg', 'Class 1' -> 'class1'."""
    return ''.join((name or '').lower().split()).replace('.', '')


# Canonical promotion order (lowest -> highest). Keys are normalized names.
CANONICAL_CLASS_ORDER = {
    'nursery': 1,
    'lkg': 2,
    'ukg': 3,
    '1': 10, '1st': 10, 'class1': 10,
    '2': 20, '2nd': 20, 'class2': 20,
    '3': 30, '3rd': 30, 'class3': 30,
    '4': 40, '4th': 40, 'class4': 40,
    '5': 50, '5th': 50, 'class5': 50,
    '6': 60, '6th': 60, 'class6': 60,
    '7': 70, '7th': 70, 'class7': 70,
    '8': 80, '8th': 80, 'class8': 80,
    '9': 90, '9th': 90, 'class9': 90,
    '10': 100, '10th': 100, 'class10': 100,
}


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def set_class_orders(request):
    """POST /api/students/classes/set-orders/

    Sets each Class.order from a canonical, exact (normalized) name match -- no
    substring matching, so '1' never collides with '10'. Deletes junk classes
    that have 0 students and an unrecognized name (e.g. a stray '.').
    Returns what it did so the UI can show it.
    """
    updated = []
    unrecognized = []
    deleted = []

    with transaction.atomic():
        for cls in Class.objects.all():
            key = _normalize_class_name(cls.name)
            order = CANONICAL_CLASS_ORDER.get(key)

            if order is not None:
                if cls.order != order:
                    cls.order = order
                    cls.save(update_fields=['order'])
                updated.append({'name': cls.name, 'order': order})
                continue

            # Unrecognized name. Delete only if it's empty (junk), else flag it.
            if cls.studentprofile_set.count() == 0:
                deleted.append(cls.name)
                cls.delete()
            else:
                unrecognized.append({'name': cls.name, 'students': cls.studentprofile_set.count()})

    return Response({
        'success': True,
        'message': f'Set order on {len(updated)} classes'
                   + (f', deleted {len(deleted)} empty junk class(es)' if deleted else '')
                   + (f', {len(unrecognized)} unrecognized non-empty class(es) need manual order' if unrecognized else ''),
        'updated': sorted(updated, key=lambda x: x['order']),
        'deleted': deleted,
        'unrecognized': unrecognized,
    })


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def promotion_preview(request):
    """GET /api/students/promotion/preview/

    Shows what a year rollover would do: each class, its student count, and the
    class students would move into ("Graduate" for the final class).
    """
    classes = _ordered_classes()
    nxt = _next_class_map(classes)

    needs_order_setup = any((c.order or 0) == 0 for c in classes)

    rows = []
    for cls in classes:
        target = nxt[cls.id]
        rows.append({
            'class_id': cls.id,
            'class_name': cls.name,
            'order': cls.order,
            'student_count': cls.studentprofile_set.count(),
            'next_class_name': target.name if target else 'Graduate',
            'graduates': target is None,
        })

    current_year = AcademicYear.objects.filter(is_current=True).first()

    return Response({
        'success': True,
        'rows': rows,
        'current_year': current_year.name if current_year else None,
        'needs_order_setup': needs_order_setup,
    })


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def promotion_run(request):
    """POST /api/students/promotion/run/

    Body: { new_year_name, start_date, end_date }
    Creates + activates a new academic year, copies the subject mappings into it,
    promotes every student up one class, and graduates the final class.
    """
    data = request.data
    new_year_name = str(data.get('new_year_name', '')).strip()
    start_date = data.get('start_date')
    end_date = data.get('end_date')

    if not new_year_name or not start_date or not end_date:
        return Response({
            'success': False,
            'message': 'new_year_name, start_date and end_date are required',
        }, status=400)

    if AcademicYear.objects.filter(name=new_year_name).exists():
        return Response({
            'success': False,
            'message': f'Academic year "{new_year_name}" already exists',
        }, status=400)

    classes = _ordered_classes()
    if not classes:
        return Response({'success': False, 'message': 'No classes found'}, status=400)

    nxt = _next_class_map(classes)
    prev_year = AcademicYear.objects.filter(is_current=True).first()

    promoted_count = 0
    graduated_count = 0

    try:
        with transaction.atomic():
            # 1. Create + activate the new academic year.
            #    AcademicYear.save() clears is_current on the others.
            new_year = AcademicYear.objects.create(
                name=new_year_name,
                start_date=start_date,
                end_date=end_date,
                is_current=True,
                is_active=True,
            )

            # 2. Copy subject mappings from the previous year so the new year
            #    has subjects for marks entry.
            if prev_year:
                old_mappings = ClassSubjectMapping.objects.filter(academic_year=prev_year)
                ClassSubjectMapping.objects.bulk_create([
                    ClassSubjectMapping(
                        student_class=m.student_class,
                        subject=m.subject,
                        is_main_subject=m.is_main_subject,
                        academic_year=new_year,
                    )
                    for m in old_mappings
                ])

            # 3. Promote students, processing classes from highest order down so
            #    we never move the same students twice.
            for cls in reversed(classes):
                target = nxt[cls.id]
                students = StudentProfile.objects.filter(student_class=cls).select_related('user')
                if target is None:
                    # Final class -> graduate (keep records, drop from active lists)
                    for s in students:
                        s.student_class = None
                        s.save(update_fields=['student_class'])
                        if s.user.is_active:
                            s.user.is_active = False
                            s.user.save(update_fields=['is_active'])
                        graduated_count += 1
                else:
                    for s in students:
                        s.student_class = target
                        s.save(update_fields=['student_class'])
                        promoted_count += 1

    except Exception as e:
        return Response({'success': False, 'message': f'Error: {str(e)}'}, status=500)

    return Response({
        'success': True,
        'message': (
            f'Promoted {promoted_count} students, graduated {graduated_count}. '
            f'New academic year {new_year_name} is now active.'
        ),
        'promoted_count': promoted_count,
        'graduated_count': graduated_count,
        'new_year': new_year_name,
    })
