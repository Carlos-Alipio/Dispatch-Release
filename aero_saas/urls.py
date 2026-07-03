from django.contrib import admin
from django.urls import path
from core_aero import views
from core_aero.api import api  # Importamos a nossa API tática

urlpatterns = [
    path('admin/', admin.site.urls),

    # Página principal: o Cockpit (HTML) é uma view Django comum, não API
    path('', views.cockpit, name='cockpit'),

    # Dizemos ao Django: Tudo o que começar por /api/ vai para o Django Ninja
    path('api/', api.urls),
]
