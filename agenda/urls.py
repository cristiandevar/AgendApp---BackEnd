from django.urls import include, path
from rest_framework.routers import DefaultRouter
from rest_framework_simplejwt.views import TokenRefreshView

from . import views

router = DefaultRouter()
router.register("usuarios", views.UsuarioViewSet, basename="usuario")
router.register("parametros", views.ParametroViewSet, basename="parametro")
router.register("feriados", views.FeriadoViewSet, basename="feriado")
router.register("productos", views.ProductoViewSet, basename="producto")
router.register("tarifas", views.TarifaHoraViewSet, basename="tarifa")
router.register("horarios", views.HorarioAsignadoViewSet, basename="horario")
router.register("notificaciones", views.NotificacionViewSet, basename="notificacion")
router.register("liquidaciones", views.LiquidacionViewSet, basename="liquidacion")
router.register("pagos", views.PagoViewSet, basename="pago")

urlpatterns = [
    path("auth/login/", views.LoginView.as_view(), name="login"),
    path("auth/refresh/", TokenRefreshView.as_view(), name="refresh"),
    path("auth/yo/", views.YoView.as_view(), name="yo"),
    path("resumen-dia/", views.ResumenDiaView.as_view(), name="resumen-dia"),
    path("", include(router.urls)),
]
