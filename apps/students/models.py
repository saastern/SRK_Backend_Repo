from django.db import models
from apps.users.models import User

class Class(models.Model):
    name = models.CharField(max_length=30)
    class_group  = models.CharField(max_length=10, choices=[('pre','Pre-Primary'),('1-5','Primary'),('6-10','Secondary')]) # E.g. "A", "B", etc.
    order = models.IntegerField(default=0)
    
    class Meta:
        ordering = ['order', 'name']
    
    def __str__(self): return self.name

class StudentProfile(models.Model):
    GENDER_CHOICES = [
        ('Male', 'Male'),
        ('Female', 'Female'),
        ('Other', 'Other'),
    ]

    user = models.OneToOneField(User, on_delete=models.CASCADE)
    student_class = models.ForeignKey(Class, on_delete=models.SET_NULL, null=True)
    roll_number = models.CharField(max_length=10)
    mother_phone = models.CharField(max_length=15, blank=True)
    father_phone = models.CharField(max_length=15, blank=True)

    # Extended profile / guardian details
    father_name = models.CharField(max_length=100, blank=True)
    mother_name = models.CharField(max_length=100, blank=True)
    parent_email = models.EmailField(blank=True)
    address = models.TextField(blank=True)
    gender = models.CharField(max_length=10, choices=GENDER_CHOICES, blank=True)

    def __str__(self):
        return f"{self.user.first_name} {self.user.last_name} ({self.student_class})"
