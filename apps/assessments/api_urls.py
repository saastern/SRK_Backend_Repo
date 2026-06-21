from django.urls import path
from .api_views import *
from .views import *

urlpatterns = [
    # Classes
    path('classes/', ClassListAPIView.as_view(), name='api-classes'),
    
    # Students
    path('students/', StudentListAPIView.as_view(), name='api-students'),
    path('student-marks/<str:student_id>/', StudentMarksDetailAPIView.as_view(), name='api-student-marks'),

    # Marks entry (React class-grid)
    path('marks-grid/', get_class_marks_grid, name='api-marks-grid'),
    path('marks-grid/save/', save_class_marks_grid, name='api-marks-grid-save'),

    # Grade scale configuration (Settings -> Grade Configuration)
    path('grade-scales/', get_grade_scales, name='api-grade-scales'),
    path('grade-scales/save/', save_grade_scales, name='api-grade-scales-save'),

    # Per-class subject configuration (Settings -> Subject Configuration)
    path('class-subjects/', get_class_subjects_config, name='api-class-subjects'),
    path('class-subjects/save/', save_class_subjects_config, name='api-class-subjects-save'),

    # Authentication
    path('auth/login/', teacher_login_api, name='api-teacher-login'),
]
