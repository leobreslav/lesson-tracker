from rest_framework.routers import DefaultRouter

from .views import PlanTemplateViewSet

router = DefaultRouter()
router.register("templates", PlanTemplateViewSet, basename="plantemplate")

# the teacher's side — POST /api/plan/import-from-template/ — is declared in
# plans/urls.py: it writes into a plan, so it belongs next to the plan
urlpatterns = router.urls
