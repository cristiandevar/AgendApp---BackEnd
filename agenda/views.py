from datetime import date

from django.core.exceptions import ValidationError as DjangoValidationError
from django.shortcuts import get_object_or_404
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.views import TokenObtainPairView

from . import calculos, liquidaciones
from .models import Feriado, HorarioAsignado, Liquidacion, Notificacion, Pago, Parametro, Producto, TarifaHora, Usuario
from .permisos import EncargadoEditaTodosLeen, EsEncargado
from .serializers import (
    FeriadoSerializer,
    HorarioAsignadoSerializer,
    LiquidacionSerializer,
    LiquidarSerializer,
    LoginSerializer,
    MotivoSerializer,
    NotificacionSerializer,
    PagoSerializer,
    ParametroSerializer,
    ProductoSerializer,
    TarifaHoraSerializer,
    UsuarioSerializer,
)


def _fecha_param(request, nombre, obligatorio=False):
    valor = request.query_params.get(nombre)
    if not valor:
        if obligatorio:
            raise ValidationError({"detalle": f"Falta el parámetro '{nombre}' (formato AAAA-MM-DD)."})
        return None
    try:
        return date.fromisoformat(valor)
    except ValueError:
        raise ValidationError({"detalle": f"Fecha inválida en '{nombre}': {valor}. Formato esperado AAAA-MM-DD."})


class FiltroFechasMixin:
    """Agrega filtros ?desde= y ?hasta= sobre el campo fecha."""

    campo_fecha = "fecha"

    def filtrar_fechas(self, qs):
        desde = _fecha_param(self.request, "desde")
        hasta = _fecha_param(self.request, "hasta")
        if desde:
            qs = qs.filter(**{f"{self.campo_fecha}__gte": desde})
        if hasta:
            qs = qs.filter(**{f"{self.campo_fecha}__lte": hasta})
        return qs


class DatosDelEmpleadoMixin:
    """El encargado ve todo (y puede filtrar con ?empleado=); el empleado solo ve lo suyo."""

    def filtrar_empleado(self, qs):
        usuario = self.request.user
        if not usuario.es_encargado:
            return qs.filter(empleado=usuario)
        empleado = self.request.query_params.get("empleado")
        return qs.filter(empleado_id=empleado) if empleado else qs


# ---------- Autenticación ----------

class LoginView(TokenObtainPairView):
    serializer_class = LoginSerializer
    permission_classes = [AllowAny]


class YoView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        datos = UsuarioSerializer(request.user).data
        if request.user.es_encargado:
            datos["rol"] = Usuario.Rol.ENCARGADO
        return Response(datos)


# ---------- Backoffice: usuarios ----------

class UsuarioViewSet(viewsets.ModelViewSet):
    serializer_class = UsuarioSerializer
    permission_classes = [EsEncargado]

    def get_queryset(self):
        qs = Usuario.objects.all()
        rol = self.request.query_params.get("rol")
        if rol:
            qs = qs.filter(rol=rol)
        if self.request.query_params.get("activos") == "1":
            qs = qs.filter(is_active=True)
        return qs

    def destroy(self, request, *args, **kwargs):
        # Un usuario con fichajes/retiros no se puede borrar: se desactiva.
        usuario = self.get_object()
        if usuario == request.user:
            return Response({"detalle": "No podés desactivar tu propio usuario."}, status=status.HTTP_409_CONFLICT)
        usuario.is_active = False
        usuario.save(update_fields=["is_active"])
        return Response(status=status.HTTP_204_NO_CONTENT)


# ---------- Catálogo y configuración ----------

class ParametroViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, mixins.UpdateModelMixin, viewsets.GenericViewSet):
    serializer_class = ParametroSerializer
    permission_classes = [EncargadoEditaTodosLeen]
    lookup_field = "clave"

    def get_queryset(self):
        for clave, valor in Parametro.DEFAULTS.items():
            Parametro.objects.get_or_create(clave=clave, defaults={"valor": valor})
        return Parametro.objects.all()


class EliminacionControladaMixin:
    """Antes de eliminar consulta Model.validar_eliminable(); si no se puede, responde 409 con el motivo."""

    def destroy(self, request, *args, **kwargs):
        instancia = self.get_object()
        try:
            instancia.validar_eliminable()
        except DjangoValidationError as e:
            return Response({"detalle": " ".join(e.messages)}, status=status.HTTP_409_CONFLICT)
        instancia.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class FeriadoViewSet(EliminacionControladaMixin, FiltroFechasMixin, viewsets.ModelViewSet):
    serializer_class = FeriadoSerializer
    permission_classes = [EncargadoEditaTodosLeen]

    def get_queryset(self):
        return self.filtrar_fechas(Feriado.objects.all())


class ProductoViewSet(viewsets.ModelViewSet):
    serializer_class = ProductoSerializer
    permission_classes = [EncargadoEditaTodosLeen]

    def get_queryset(self):
        qs = Producto.objects.all()
        if self.request.query_params.get("activos") == "1":
            qs = qs.filter(activo=True)
        buscar = self.request.query_params.get("buscar")
        if buscar:
            qs = qs.filter(nombre__icontains=buscar)
        return qs

    def destroy(self, request, *args, **kwargs):
        # Baja lógica: los retiros históricos siguen apuntando al producto.
        producto = self.get_object()
        producto.activo = False
        producto.save(update_fields=["activo", "actualizado"])
        return Response(status=status.HTTP_204_NO_CONTENT)


class TarifaHoraViewSet(EliminacionControladaMixin, DatosDelEmpleadoMixin, viewsets.ModelViewSet):
    serializer_class = TarifaHoraSerializer
    permission_classes = [EncargadoEditaTodosLeen]

    def get_queryset(self):
        return self.filtrar_empleado(TarifaHora.objects.select_related("empleado"))


class HorarioAsignadoViewSet(DatosDelEmpleadoMixin, FiltroFechasMixin, viewsets.ModelViewSet):
    serializer_class = HorarioAsignadoSerializer
    permission_classes = [EncargadoEditaTodosLeen]

    def get_queryset(self):
        qs = HorarioAsignado.objects.select_related("empleado")
        return self.filtrar_fechas(self.filtrar_empleado(qs))


# ---------- Cálculo ----------

class ResumenDiaView(APIView):
    """GET /api/resumen-dia/?fecha=AAAA-MM-DD[&empleado=<id>] -> la cuenta de la hoja de ese día."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        fecha = _fecha_param(request, "fecha", obligatorio=True)
        if request.user.es_encargado and request.query_params.get("empleado"):
            empleado = get_object_or_404(Usuario, pk=request.query_params["empleado"])
        else:
            empleado = request.user
        return Response(calculos.resumen_dia(empleado, fecha))


# ---------- Notificaciones del encargado ----------

class NotificacionViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    """
    GET  /api/notificaciones/[?no_leidas=1][&desde=<fecha-hora ISO>]
    GET  /api/notificaciones/cantidad_no_leidas/
    POST /api/notificaciones/<id>/marcar_leida/
    POST /api/notificaciones/marcar_todas_leidas/
    """

    serializer_class = NotificacionSerializer
    permission_classes = [EsEncargado]

    def get_queryset(self):
        qs = Notificacion.objects.filter(destinatario=self.request.user).select_related("empleado")
        if self.request.query_params.get("no_leidas") == "1":
            qs = qs.filter(leida=False)
        desde = self.request.query_params.get("desde")
        if desde:
            qs = qs.filter(creada_en__gt=desde)
        return qs

    @action(detail=False, methods=["get"])
    def cantidad_no_leidas(self, request):
        return Response({"cantidad": self.get_queryset().filter(leida=False).count()})

    @action(detail=True, methods=["post"])
    def marcar_leida(self, request, pk=None):
        notificacion = self.get_object()
        notificacion.leida = True
        notificacion.save(update_fields=["leida"])
        return Response(self.get_serializer(notificacion).data)

    @action(detail=False, methods=["post"])
    def marcar_todas_leidas(self, request):
        cantidad = self.get_queryset().filter(leida=False).update(leida=True)
        return Response({"marcadas": cantidad})


# ---------- Liquidaciones y pagos ----------

def _error_negocio(e):
    return Response({"detalle": e.messages}, status=status.HTTP_400_BAD_REQUEST)


class SoloEncargadoEscribeMixin:
    def check_permissions(self, request):
        super().check_permissions(request)
        if self.action not in ("list", "retrieve") and not request.user.es_encargado:
            self.permission_denied(request, message="Solo el encargado puede realizar esta acción.")


class LiquidacionViewSet(SoloEncargadoEscribeMixin, DatosDelEmpleadoMixin, viewsets.ReadOnlyModelViewSet):
    """
    GET  /api/liquidaciones/[?empleado=&estado=VIGENTE]   (el empleado ve solo las suyas)
    GET  /api/liquidaciones/<id>/                          (+ detalle por día con estado de pago)
    GET  /api/liquidaciones/previsualizar/?empleado=<id>[&hasta=AAAA-MM-DD]
    POST /api/liquidaciones/  {empleado, hasta?, monto_pagado, fecha_pago?, hora_pago?, observacion?}
    POST /api/liquidaciones/<id>/anular/  {motivo}
    """

    serializer_class = LiquidacionSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        qs = Liquidacion.objects.select_related("empleado").prefetch_related("pagos")
        estado = self.request.query_params.get("estado")
        if estado:
            qs = qs.filter(estado=estado)
        return self.filtrar_empleado(qs)

    def retrieve(self, request, *args, **kwargs):
        liquidacion = self.get_object()
        datos = self.get_serializer(liquidacion).data
        datos["dias"] = liquidaciones.detalle(liquidacion)
        return Response(datos)

    @action(detail=False, methods=["get"])
    def previsualizar(self, request):
        empleado = get_object_or_404(Usuario, pk=request.query_params.get("empleado"))
        try:
            return Response(liquidaciones.previsualizar(empleado, _fecha_param(request, "hasta")))
        except DjangoValidationError as e:
            return _error_negocio(e)

    def create(self, request):
        entrada = LiquidarSerializer(data=request.data)
        entrada.is_valid(raise_exception=True)
        d = entrada.validated_data
        try:
            liquidacion = liquidaciones.liquidar(
                d["empleado"], hasta=d.get("hasta"), monto_pagado=d["monto_pagado"], registrado_por=request.user,
                fecha_pago=d.get("fecha_pago"), hora_pago=d.get("hora_pago"), observacion=d.get("observacion", ""),
            )
        except DjangoValidationError as e:
            return _error_negocio(e)
        return Response(self.get_serializer(liquidacion).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"])
    def anular(self, request, pk=None):
        entrada = MotivoSerializer(data=request.data)
        entrada.is_valid(raise_exception=True)
        try:
            liquidacion = liquidaciones.anular(self.get_object(), request.user, entrada.validated_data["motivo"])
        except DjangoValidationError as e:
            return _error_negocio(e)
        return Response(self.get_serializer(liquidacion).data)


class PagoViewSet(SoloEncargadoEscribeMixin, DatosDelEmpleadoMixin, FiltroFechasMixin, viewsets.ReadOnlyModelViewSet):
    """
    GET  /api/pagos/[?empleado=&desde=&hasta=&pendientes=1]  (el empleado ve solo los suyos)
    POST /api/pagos/  {empleado, fecha, hora?, monto, observacion?}  -> registra un adelanto
    POST /api/pagos/<id>/anular/  {motivo}
    """

    serializer_class = PagoSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        qs = Pago.objects.select_related("empleado")
        if self.request.query_params.get("pendientes") == "1":
            qs = qs.filter(anulado=False, liquidacion__isnull=True)
        return self.filtrar_fechas(self.filtrar_empleado(qs))

    def create(self, request):
        entrada = self.get_serializer(data=request.data)
        entrada.is_valid(raise_exception=True)
        d = entrada.validated_data
        try:
            pago = liquidaciones.registrar_adelanto(
                d["empleado"], fecha=d["fecha"], monto=d["monto"], registrado_por=request.user,
                hora=d.get("hora"), observacion=d.get("observacion", ""),
            )
        except DjangoValidationError as e:
            return _error_negocio(e)
        return Response(self.get_serializer(pago).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"])
    def anular(self, request, pk=None):
        entrada = MotivoSerializer(data=request.data)
        entrada.is_valid(raise_exception=True)
        try:
            pago = liquidaciones.anular_pago(self.get_object(), request.user, entrada.validated_data["motivo"])
        except DjangoValidationError as e:
            return _error_negocio(e)
        return Response(self.get_serializer(pago).data)
