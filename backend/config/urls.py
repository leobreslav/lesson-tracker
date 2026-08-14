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
    # разделы ученика: у него другой интерфейс целиком, и адреса тоже свои
    path('api/student/', include('schedule.student_urls')),
    path('api/student/', include('works.student_urls')),
    path('api/student/', include('plans.student_urls')),
    path('api/library/', include('library.urls')),
    path('api/works/', include('works.urls')),
    path('api/', include('files.urls')),
    path('api/schools/', include('schools.admin_urls')),
]
