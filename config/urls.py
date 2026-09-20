"""URL configuration.

Slice 0 exposes the admin and a health endpoint. No business views exist — the
admin is ~80% of the ops console and Slices A and B add to it.
"""

from django.contrib import admin
from django.urls import path

from core.views import health, home

urlpatterns = [
    path("admin/", admin.site.urls),
    path("healthz", health, name="health"),
    path("", home, name="home"),
]
