from django.core.cache import cache
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver


def _invalidate_teacher_nav_flags(teacher_id):
    if teacher_id:
        cache.delete(f"teacher_nav_flags:{teacher_id}")


@receiver(post_save, dispatch_uid="invalidate_teacher_nav_on_class_save")
def invalidate_teacher_nav_on_class_save(sender, instance, **kwargs):
    from apps.curriculum.models import AcademicClass

    if sender is not AcademicClass:
        return
    _invalidate_teacher_nav_flags(instance.class_teacher_id)


@receiver(post_save, dispatch_uid="invalidate_teacher_nav_on_elearning_allocation_save")
def invalidate_teacher_nav_on_elearning_allocation_save(sender, instance, **kwargs):
    from apps.curriculum.models import ELearningSubjectAllocation

    if sender is not ELearningSubjectAllocation:
        return
    _invalidate_teacher_nav_flags(instance.teacher_id)


@receiver(post_delete, dispatch_uid="invalidate_teacher_nav_on_elearning_allocation_delete")
def invalidate_teacher_nav_on_elearning_allocation_delete(sender, instance, **kwargs):
    from apps.curriculum.models import ELearningSubjectAllocation

    if sender is not ELearningSubjectAllocation:
        return
    _invalidate_teacher_nav_flags(instance.teacher_id)


@receiver(post_save, dispatch_uid="invalidate_exam_report_catalog_on_exam_save")
def invalidate_exam_report_catalog_on_exam_save(sender, instance, **kwargs):
    from apps.curriculum.models import GeneratedExamTimetable

    if sender is not GeneratedExamTimetable:
        return
    cache.delete("exam_report_builder_catalog")


@receiver(post_delete, dispatch_uid="invalidate_exam_report_catalog_on_exam_delete")
def invalidate_exam_report_catalog_on_exam_delete(sender, instance, **kwargs):
    from apps.curriculum.models import GeneratedExamTimetable

    if sender is not GeneratedExamTimetable:
        return
    cache.delete("exam_report_builder_catalog")
