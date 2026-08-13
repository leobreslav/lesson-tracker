"""
Правка плана отзывает поданный запрос на утверждение.

Сигналы, а не вызов в каждой вьюхе: правок у плана десяток — создание,
переименование, удаление, перемещение, — и забыть одну из них означало бы
показывать методисту запрос на план, которого уже нет.

`bulk_create`/`bulk_update` сигналов не шлют, поэтому массовые операции
(импорт CSV, синхронизация, импорт из библиотеки) зовут `approval.withdraw`
сами. Это единственное исключение, и оно названо здесь, чтобы искать его не
пришлось.
"""

from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from . import approval
from .models import PlanNode


@receiver(post_save, sender=PlanNode)
@receiver(post_delete, sender=PlanNode)
def withdraw_on_edit(sender, instance, **kwargs):
    approval.withdraw(instance.teacher_id, instance.course_id)
