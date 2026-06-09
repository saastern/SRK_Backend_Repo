from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('students', '0003_class_class_group'),
    ]

    operations = [
        migrations.AddField(
            model_name='studentprofile',
            name='father_name',
            field=models.CharField(blank=True, max_length=100),
        ),
        migrations.AddField(
            model_name='studentprofile',
            name='mother_name',
            field=models.CharField(blank=True, max_length=100),
        ),
        migrations.AddField(
            model_name='studentprofile',
            name='parent_email',
            field=models.EmailField(blank=True, max_length=254),
        ),
        migrations.AddField(
            model_name='studentprofile',
            name='address',
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name='studentprofile',
            name='gender',
            field=models.CharField(
                blank=True,
                choices=[('Male', 'Male'), ('Female', 'Female'), ('Other', 'Other')],
                max_length=10,
            ),
        ),
        migrations.AlterField(
            model_name='studentprofile',
            name='mother_phone',
            field=models.CharField(blank=True, max_length=15),
        ),
        migrations.AlterField(
            model_name='studentprofile',
            name='father_phone',
            field=models.CharField(blank=True, max_length=15),
        ),
    ]
