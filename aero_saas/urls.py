from django.contrib import admin
from django.urls import path
from core_aero.api import api  # Importamos a nossa API tática

urlpatterns = [
    path('admin/', admin.site.urls),
    
    # Dizemos ao Django: Tudo o que começar por /api/ vai para o Django Ninja
    path('api/', api.urls), 
]
