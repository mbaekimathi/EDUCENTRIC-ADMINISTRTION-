from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("curriculum", "0030_subject_attendance_lesson_plan_outcome"),
    ]

    operations = [
        migrations.RemoveField(model_name="classsubjectlessonplan", name="content"),
        migrations.RemoveField(model_name="classsubjectlessonplan", name="homework"),
        migrations.RemoveField(model_name="classsubjectlessonplan", name="objectives"),
        migrations.RemoveField(model_name="classsubjectlessonplan", name="resources"),
        migrations.RemoveField(model_name="classsubjectlessonplan", name="title"),
        migrations.AddField(
            model_name="classsubjectlessonplan",
            name="core_competencies",
            field=models.TextField(blank=True, verbose_name="core competencies"),
        ),
        migrations.AddField(
            model_name="classsubjectlessonplan",
            name="introduction",
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name="classsubjectlessonplan",
            name="key_inquiry_questions",
            field=models.TextField(blank=True, verbose_name="key inquiry questions"),
        ),
        migrations.AddField(
            model_name="classsubjectlessonplan",
            name="learning_resources",
            field=models.TextField(blank=True, verbose_name="learning resources"),
        ),
        migrations.AddField(
            model_name="classsubjectlessonplan",
            name="lesson_development",
            field=models.TextField(blank=True, verbose_name="lesson development"),
        ),
        migrations.AddField(
            model_name="classsubjectlessonplan",
            name="lesson_learning_outcomes",
            field=models.TextField(blank=True, verbose_name="lesson learning outcomes"),
        ),
        migrations.AddField(
            model_name="classsubjectlessonplan",
            name="organization_of_learning",
            field=models.TextField(blank=True, verbose_name="organization of learning"),
        ),
        migrations.AddField(
            model_name="classsubjectlessonplan",
            name="pcis",
            field=models.TextField(blank=True, verbose_name="PCIs"),
        ),
        migrations.AddField(
            model_name="classsubjectlessonplan",
            name="strand",
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.AddField(
            model_name="classsubjectlessonplan",
            name="substrand",
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.AddField(
            model_name="classsubjectlessonplan",
            name="values",
            field=models.TextField(blank=True),
        ),
    ]
