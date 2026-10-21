from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer

from .models import Feriado, HorarioAsignado, Liquidacion, Notificacion, Pago, Parametro, Producto, TarifaHora, Usuario


class UsuarioSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, required=False, min_length=8)
    nombre_completo = serializers.CharField(read_only=True)
    fecha_alta = serializers.DateField(read_only=True)

    class Meta:
        model = Usuario
        fields = ("id", "username", "first_name", "last_name", "nombre_completo", "rol", "modalidad_liquidacion",
                  "fecha_alta", "is_active", "password")

    def validate(self, datos):
        if self.instance is None and not datos.get("password"):
            raise serializers.ValidationError({"password": "La contraseña es obligatoria al crear un usuario."})
        return datos

    def create(self, datos):
        password = datos.pop("password")
        usuario = Usuario(**datos)
        usuario.set_password(password)
        usuario.save()
        return usuario

    def update(self, usuario, datos):
        password = datos.pop("password", None)
        for campo, valor in datos.items():
            setattr(usuario, campo, valor)
        if password:
            usuario.set_password(password)
        usuario.save()
        return usuario


class LoginSerializer(TokenObtainPairSerializer):
    """Login: además de los tokens devuelve los datos del usuario (rol incluido)."""

    @classmethod
    def get_token(cls, user):
        token = super().get_token(user)
        token["rol"] = Usuario.Rol.ENCARGADO if user.es_encargado else user.rol
        return token

    def validate(self, attrs):
        datos = super().validate(attrs)
        datos["usuario"] = UsuarioSerializer(self.user).data
        if self.user.es_encargado:
            datos["usuario"]["rol"] = Usuario.Rol.ENCARGADO
        return datos


class ParametroSerializer(serializers.ModelSerializer):
    descripcion = serializers.CharField(source="get_clave_display", read_only=True)

    class Meta:
        model = Parametro
        fields = ("clave", "descripcion", "valor", "actualizado")
        read_only_fields = ("clave", "actualizado")


class ValidarConModeloMixin:
    """
    Corre las reglas de negocio definidas en Model.clean() (DRF no lo hace solo),
    armando la instancia con los datos actuales + los recibidos (sirve para PATCH).
    Los errores vuelven como {"detalle": "..."}.
    """

    campos_modelo = ()

    def validate(self, datos):
        datos = super().validate(datos)
        Modelo = self.Meta.model
        actuales = {c: getattr(self.instance, c) for c in self.campos_modelo} if self.instance else {}
        instancia = Modelo(**{**actuales, **datos})
        if self.instance is not None:
            instancia.pk = self.instance.pk
        try:
            instancia.clean()
        except DjangoValidationError as e:
            raise serializers.ValidationError({"detalle": " ".join(e.messages)})
        return datos


class FeriadoSerializer(ValidarConModeloMixin, serializers.ModelSerializer):
    campos_modelo = ("fecha", "descripcion", "multiplicador")
    multiplicador = serializers.DecimalField(max_digits=5, decimal_places=2, min_value=1, required=False)
    es_modificable = serializers.BooleanField(read_only=True)

    class Meta:
        model = Feriado
        fields = ("id", "fecha", "descripcion", "multiplicador", "es_modificable", "actualizado")


class ProductoSerializer(serializers.ModelSerializer):
    class Meta:
        model = Producto
        fields = ("id", "nombre", "precio_costo", "max_diario", "activo", "actualizado")


class TarifaHoraSerializer(ValidarConModeloMixin, serializers.ModelSerializer):
    campos_modelo = ("empleado", "monto", "vigente_desde")
    empleado_nombre = serializers.CharField(source="empleado.nombre_completo", read_only=True)
    es_modificable = serializers.BooleanField(read_only=True)

    class Meta:
        model = TarifaHora
        fields = ("id", "empleado", "empleado_nombre", "monto", "vigente_desde", "es_modificable", "actualizado")
        validators = [
            serializers.UniqueTogetherValidator(
                queryset=TarifaHora.objects.all(),
                fields=("empleado", "vigente_desde"),
                message="Ese empleado ya tiene una tarifa que empieza en esa fecha.",
            )
        ]


class HorarioAsignadoSerializer(ValidarConModeloMixin, serializers.ModelSerializer):
    campos_modelo = ("empleado", "fecha", "hora_inicio", "hora_fin")
    empleado_nombre = serializers.CharField(source="empleado.nombre_completo", read_only=True)

    class Meta:
        model = HorarioAsignado
        fields = ("id", "empleado", "empleado_nombre", "fecha", "hora_inicio", "hora_fin", "actualizado")


class NotificacionSerializer(serializers.ModelSerializer):
    empleado_nombre = serializers.CharField(source="empleado.nombre_completo", read_only=True)
    tipo_descripcion = serializers.CharField(source="get_tipo_display", read_only=True)

    class Meta:
        model = Notificacion
        fields = (
            "id", "tipo", "tipo_descripcion", "mensaje", "empleado", "empleado_nombre", "fecha",
            "referencia_id", "destacada", "leida", "creada_en",
        )
        read_only_fields = fields


class PagoSerializer(serializers.ModelSerializer):
    empleado_nombre = serializers.CharField(source="empleado.nombre_completo", read_only=True)
    tipo_descripcion = serializers.CharField(source="get_tipo_display", read_only=True)
    hora = serializers.TimeField(required=False, format="%H:%M")

    class Meta:
        model = Pago
        fields = (
            "id", "empleado", "empleado_nombre", "tipo", "tipo_descripcion", "fecha", "hora", "monto", "observacion",
            "liquidacion", "liquidacion_origen", "anulado", "anulado_en", "motivo_anulacion", "registrado_por",
            "creado_en",
        )
        read_only_fields = (
            "tipo", "liquidacion", "liquidacion_origen", "anulado", "anulado_en", "motivo_anulacion",
            "registrado_por", "creado_en",
        )


class LiquidacionSerializer(serializers.ModelSerializer):
    empleado_nombre = serializers.CharField(source="empleado.nombre_completo", read_only=True)
    horas_trabajadas = serializers.SerializerMethodField()
    diferencia = serializers.SerializerMethodField()
    pagos = PagoSerializer(many=True, read_only=True)

    class Meta:
        model = Liquidacion
        fields = (
            "id", "empleado", "empleado_nombre", "desde", "hasta", "modalidad", "saldo_anterior",
            "minutos_trabajados", "horas_trabajadas", "ganado", "retiros", "adelantos", "total_a_pagar",
            "monto_pagado", "saldo_resultante", "diferencia", "observacion", "estado", "registrado_por",
            "creada_en", "anulada_por", "anulada_en", "motivo_anulacion", "pagos",
        )
        read_only_fields = fields

    def get_horas_trabajadas(self, obj):
        from .calculos import formato_horas

        return formato_horas(obj.minutos_trabajados)

    def get_diferencia(self, obj):
        from .liquidaciones import diferencia

        return diferencia(obj)


class LiquidarSerializer(serializers.Serializer):
    empleado = serializers.PrimaryKeyRelatedField(queryset=Usuario.objects.all())
    hasta = serializers.DateField(required=False)
    monto_pagado = serializers.DecimalField(max_digits=14, decimal_places=2, min_value=0)
    fecha_pago = serializers.DateField(required=False)
    hora_pago = serializers.TimeField(required=False)
    observacion = serializers.CharField(required=False, allow_blank=True, max_length=200, default="")


class MotivoSerializer(serializers.Serializer):
    motivo = serializers.CharField()
