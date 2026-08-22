"""
Grade levels become a reference list, and «who teaches this course» a table.

Two data steps in the middle, and both matter on a live database:

* the old `grade` was a number on the course. It is renamed out of the way,
  the foreign key is added beside it, and every course is pointed at the
  level with the same number — created if the school did not have it yet.
  Altering the column in place would ask Postgres to reinterpret 9 as a
  primary key, which is either an error or, worse, the wrong row;
* assignments are backfilled from the work that already exists. Until now
  the only trace of «X teaches Y» was a lesson, a plan row or a line of the
  school timetable; without this step every teacher would open the app to an
  empty list of courses.
"""

import django.core.validators
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models

DEFAULT_GRADE_RANGE = range(1, 12)


def fill_grade_levels(apps, schema_editor):
    School = apps.get_model("schools", "School")
    GradeLevel = apps.get_model("schedule", "GradeLevel")
    Course = apps.get_model("schedule", "Course")

    for school in School.objects.all():
        known = set(
            GradeLevel.objects.filter(school=school).values_list("level", flat=True)
        )
        # the same starting list a new school gets, see schools/signals.py
        wanted = set(DEFAULT_GRADE_RANGE) | set(
            Course.objects.filter(school=school, old_grade__isnull=False)
            .values_list("old_grade", flat=True)
            .distinct()
        )
        GradeLevel.objects.bulk_create(
            GradeLevel(school=school, level=level, name=f"Grade {level}")
            for level in sorted(wanted - known)
        )

        levels = {
            level.level: level.pk
            for level in GradeLevel.objects.filter(school=school)
        }
        for course in Course.objects.filter(school=school, old_grade__isnull=False):
            course.grade_id = levels[course.old_grade]
            course.save(update_fields=["grade"])


def backfill_assignments(apps, schema_editor):
    CourseAssignment = apps.get_model("schedule", "CourseAssignment")
    pairs = set()

    for model, teacher_field in (
        (apps.get_model("schedule", "MasterSlot"), "teacher_id"),
        (apps.get_model("schedule", "LessonSlot"), "teacher_id"),
        (apps.get_model("plans", "PlanNode"), "teacher_id"),
    ):
        pairs.update(
            model.objects.exclude(**{f"{teacher_field}__isnull": True})
            .values_list("course_id", teacher_field)
            .distinct()
        )

    CourseAssignment.objects.bulk_create(
        (
            CourseAssignment(course_id=course_id, teacher_id=teacher_id)
            for course_id, teacher_id in sorted(pairs)
        ),
        ignore_conflicts=True,
    )


def nothing(apps, schema_editor):
    """Backwards: the rows go with the columns and the table anyway."""


class Migration(migrations.Migration):

    dependencies = [
        ("schedule", "0003_course_grade_subject_course_subject_and_more"),
        ("schools", "0001_initial"),
        ("plans", "0002_lesson_content"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="GradeLevel",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("level", models.PositiveSmallIntegerField(help_text="The year of study counted from the first one, not the number inside the name. «MYP 4» is the ninth year of study, so its level is 9 — that is what keeps sorting right in a school that uses both systems.", validators=[django.core.validators.MinValueValidator(1), django.core.validators.MaxValueValidator(11)], verbose_name="year of study")),
                ("name", models.CharField(help_text="What the school calls it: «Grade 6», «MYP 4», «10 класс».", max_length=50, verbose_name="name")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("school", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="grade_levels", to="schools.school", verbose_name="school")),
            ],
            options={
                "verbose_name": "grade level",
                "verbose_name_plural": "grade levels",
                "ordering": ("level",),
            },
        ),
        migrations.AddConstraint(
            model_name="gradelevel",
            constraint=models.UniqueConstraint(fields=("school", "level"), name="unique_grade_level_per_school"),
        ),
        migrations.CreateModel(
            name="CourseAssignment",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("course", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="assignments", to="schedule.course", verbose_name="course")),
                ("teacher", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="course_assignments", to=settings.AUTH_USER_MODEL, verbose_name="teacher")),
            ],
            options={
                "verbose_name": "course assignment",
                "verbose_name_plural": "course assignments",
                "ordering": ("course__name", "teacher__last_name", "teacher__email"),
                "constraints": [models.UniqueConstraint(fields=("course", "teacher"), name="unique_course_assignment")],
            },
        ),
        # the number steps aside, the key takes its place
        migrations.RenameField(model_name="course", old_name="grade", new_name="old_grade"),
        migrations.AddField(
            model_name="course",
            name="grade",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="courses", to="schedule.gradelevel", verbose_name="grade level"),
        ),
        migrations.RunPython(fill_grade_levels, nothing),
        migrations.RunPython(backfill_assignments, nothing),
        migrations.RemoveField(model_name="course", name="old_grade"),
        migrations.AlterModelOptions(
            name="course",
            options={"ordering": ("grade__level", "name"), "verbose_name": "course", "verbose_name_plural": "courses"},
        ),
    ]
