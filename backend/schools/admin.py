from django.contrib import admin

from .models import Invitation, School


@admin.register(School)
class SchoolAdmin(admin.ModelAdmin):
    list_display = ("name", "created_at")
    search_fields = ("name",)


@admin.register(Invitation)
class InvitationAdmin(admin.ModelAdmin):
    list_display = ("email", "school", "is_school_admin", "accepted_at")
    list_filter = ("school", "is_school_admin")
    search_fields = ("email",)
