from django.urls import path
from . import views

urlpatterns = [
    path('search/', views.search_students, name='search_students'),

    # Student management (teacher "Manage Students" page)
    path('class/<int:class_id>/', views.class_students, name='class_students'),
    path('add/', views.add_student, name='add_student'),
    path('add-bulk/', views.add_students_bulk, name='add_students_bulk'),

    # Promotion / year rollover (Settings -> Promote Students)
    path('classes/set-orders/', views.set_class_orders, name='set_class_orders'),
    path('promotion/preview/', views.promotion_preview, name='promotion_preview'),
    path('promotion/run/', views.promotion_run, name='promotion_run'),

    path('<int:student_id>/delete/', views.delete_student, name='delete_student'),
]
