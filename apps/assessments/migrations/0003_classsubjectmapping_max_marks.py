from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('assessments', '0002_academicyear_remove_bulkuploadjob_uploaded_by_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='classsubjectmapping',
            name='fa_max_marks',
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name='classsubjectmapping',
            name='sa_max_marks',
            field=models.PositiveIntegerField(default=0),
        ),
    ]
