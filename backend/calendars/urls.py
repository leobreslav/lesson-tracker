from rest_framework.routers import DefaultRouter

from .views import DayExceptionViewSet, SchoolYearViewSet

router = DefaultRouter()
router.register("years", SchoolYearViewSet, basename="schoolyear")
router.register("exceptions", DayExceptionViewSet, basename="dayexception")

urlpatterns = router.urls
