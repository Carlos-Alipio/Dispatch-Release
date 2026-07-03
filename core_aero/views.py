"""
Views de página (HTML) do core_aero.

Páginas não são API: elas vivem aqui, fora do Django Ninja, e são montadas
diretamente no urls.py do projeto. A API (JSON/GeoJSON) vive em api.py.
"""
from django.conf import settings
from django.shortcuts import render


def cockpit(request):
    """Interface do Cockpit (MapLibre), com a config vinda do ambiente injetada no template."""
    return render(request, "template.html", {"owm_api_key": settings.OWM_API_KEY})
