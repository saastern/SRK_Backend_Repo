from django.urls import path
from . import views

urlpatterns = [
    path('search/', views.search_students, name='search_students'),

    # Student management (teacher "Manage Students" page)
    path('class/<int:class_id>/', views.class_students, name='class_students'),
    path('add/', views.add_student, name='add_student'),
    path('add-bulk/', views.add_students_bulk, name='add_students_bulk'),
    path('<int:student_id>/delete/', views.delete_student, name='delete_student'),
]
