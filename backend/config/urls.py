"""
URL configuration for config project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.1/topics/http/urls/
"""
from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/', include('accounts.urls')),
    path('api/calendar/', include('calendars.urls')),
    path('api/', include('schedule.urls')),
    path('api/plan/', include('plans.urls')),
    path('api/onboarding/', include('onboarding.urls')),
    path('api/school/', include('schools.urls')),
    path('api/schools/', include('schools.admin_urls')),
]
