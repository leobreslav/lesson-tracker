from django.urls import path
from rest_framework.routers import SimpleRouter

from .views import PlanNodeViewSet, SectionMoveView

router = SimpleRouter()
# префикс пустой: приложение подключено как /api/plan/
router.register("", PlanNodeViewSet, basename="plannode")

urlpatterns = [
    # объявлено до маршрутов роутера, чтобы sections не приняли за id узла
    path("sections/<int:pk>/move/", SectionMoveView.as_view(), name="plansection-move"),
    *router.urls,
]
