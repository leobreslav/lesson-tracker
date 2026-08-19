from django.urls import path

from .views import BudgetView, SpendView

urlpatterns = [
    path("ai-budget/", BudgetView.as_view(), name="ai-budget"),
    path("ai-spend/", SpendView.as_view(), name="ai-spend"),
]
