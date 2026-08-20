from django.urls import path

from .views import (
    ProblemView,
    SolutionsView,
    SourceView,
    SourcesView,
    TagLinkView,
    TagsView,
)

urlpatterns = [
    path("sources/", SourcesView.as_view(), name="bank-sources"),
    path("sources/<int:pk>/", SourceView.as_view(), name="bank-source"),
    path("problems/<int:pk>/", ProblemView.as_view(), name="bank-problem"),
    path("solutions/", SolutionsView.as_view(), name="bank-solutions"),
    path("tags/", TagsView.as_view(), name="bank-tags"),
    path("tag-links/", TagLinkView.as_view(), name="bank-tag-links"),
]
