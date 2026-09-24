"""
Бланк с подписями задач на скачивание.

Ручка одна на два входа — со страницы работы (подписи из имён её задач) и из
списка работ (подписи набирают руками, работы нет вовсе), — и потому про
работу она не знает ничего: приходят пятнадцать строк, уходит PDF. Хранить
тут нечего: бланк собирается за доли секунды, а подписи, вписанные для
печати, в задачи не записываются.
"""

from config.access import IsSchoolMember, IsTeacher
from django.http import HttpResponse
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from . import blank


class BlankView(APIView):
    """POST `{labels: [...]}` → PDF бланка с этими подписями над клетками."""

    permission_classes = [IsAuthenticated, IsSchoolMember, IsTeacher]

    def post(self, request):
        content = blank.render(request.data.get("labels", []))
        response = HttpResponse(content, content_type="application/pdf")
        response["Content-Disposition"] = 'attachment; filename="blank.pdf"'
        return response
