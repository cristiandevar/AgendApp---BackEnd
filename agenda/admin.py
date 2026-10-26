from django import forms
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from django.utils.html import format_html_join
from django.utils.safestring import mark_safe

from . import liquidaciones, reglas
from .models import (
    AuditoriaFichaje,
    AuditoriaRetiro,
    Notificacion,
    Feriado,
    Fichaje,
    HorarioAsignado,
    Liquidacion,
    Pago,
    Parametro,
    Producto,
    Retiro,
    TarifaHora,
    Usuario,
)

admin.site.site_header = "AgendApp - BackEnd"
admin.site.site_title = "AgendApp - BackEnd"
admin.site.index_title = "Administración"


@admin.register(Usuario)
class UsuarioAdmin(UserAdmin):
    list_display = ("username", "first_name", "last_name", "rol", "modalidad_liquidacion", "is_active")
    list_filter = ("rol", "modalidad_liquidacion", "is_active")
    fieldsets = UserAdmin.fieldsets + (("AgendApp", {"fields": ("rol", "modalidad_liquidacion")}),)
    add_fieldsets = UserAdmin.add_fieldsets + (
        ("AgendApp", {"fields": ("first_name", "last_name", "rol", "modalidad_liquidacion")}),
    )


@admin.register(Parametro)
class ParametroAdmin(admin.ModelAdmin):
    list_display = ("clave", "valor", "actualizado")


class HistorialProtegidoAdmin(admin.ModelAdmin):
    """
    Para tarifas y feriados: lo que ya rigió se ve en solo lectura y no se puede
    eliminar (ni siquiera con la acción masiva), para no alterar cálculos pasados.
    """

    def get_actions(self, request):
        acciones = super().get_actions(request)
        acciones.pop("delete_selected", None)
        return acciones

    def has_change_permission(self, request, obj=None):
        return super().has_change_permission(request, obj) and (obj is None or obj.es_modificable)

    def has_delete_permission(self, request, obj=None):
        return super().has_delete_permission(request, obj) and (obj is None or obj.es_modificable)


@admin.register(Feriado)
class FeriadoAdmin(HistorialProtegidoAdmin):
    list_display = ("fecha", "descripcion", "multiplicador")
    date_hierarchy = "fecha"


@admin.register(Producto)
class ProductoAdmin(admin.ModelAdmin):
    list_display = ("nombre", "precio_costo", "max_diario", "activo")
    list_filter = ("activo",)
    list_editable = ("precio_costo", "max_diario", "activo")
    search_fields = ("nombre",)


@admin.register(TarifaHora)
class TarifaHoraAdmin(HistorialProtegidoAdmin):
    list_display = ("empleado", "monto", "vigente_desde", "es_modificable")
    list_filter = ("empleado",)

    @admin.display(boolean=True, description="Modificable")
    def es_modificable(self, obj):
        return obj.es_modificable

    def get_readonly_fields(self, request, obj=None):
        return ("empleado",) if obj else ()


@admin.register(HorarioAsignado)
class HorarioAsignadoAdmin(admin.ModelAdmin):
    list_display = ("empleado", "fecha", "hora_inicio", "hora_fin")
    list_filter = ("empleado",)
    date_hierarchy = "fecha"


class AuditoriaInlineBase(admin.TabularInline):
    extra = 0
    can_delete = False
    readonly_fields = ("fecha_hora", "accion", "usuario", "datos_anteriores", "datos_nuevos", "motivo")

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False


class AuditoriaInline(AuditoriaInlineBase):
    model = AuditoriaFichaje


class AuditoriaRetiroInline(AuditoriaInlineBase):
    model = AuditoriaRetiro


class SoloLecturaAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class DiaNoLiquidadoMixin:
    """El encargado no carga ni corrige movimientos de días liquidados (hay que anular la liquidación)."""

    def validar_dia_no_liquidado(self, datos):
        fechas = [(datos.get("empleado"), datos.get("fecha"))]
        if self.instance.pk:
            fechas.append((self.instance.empleado, self.instance.fecha))
        for empleado, fecha in fechas:
            if empleado and fecha:
                reglas.validar_dia_no_liquidado(empleado, fecha)


class FichajeAdminForm(DiaNoLiquidadoMixin, forms.ModelForm):
    motivo_correccion = forms.CharField(
        label="Motivo de la corrección",
        widget=forms.Textarea(attrs={"rows": 2}),
        help_text="Obligatorio: queda registrado en la auditoría.",
    )

    class Meta:
        model = Fichaje
        fields = ("empleado", "fecha", "hora", "tipo", "motivo", "anulado")

    def clean(self):
        datos = super().clean()
        empleado, fecha, hora, tipo = (datos.get(k) for k in ("empleado", "fecha", "hora", "tipo"))
        if not all([empleado, fecha, hora, tipo]):
            return datos
        self.validar_dia_no_liquidado(datos)
        if not datos.get("anulado"):
            otros = Fichaje.objects.filter(empleado=empleado, fecha=fecha, anulado=False).exclude(pk=self.instance.pk)
            marcas = [(f.hora, f.tipo) for f in otros] + [(hora, tipo)]
            try:
                reglas.validar_secuencia(marcas)
            except ValidationError as e:
                raise ValidationError(e.messages)
        return datos


@admin.register(Fichaje)
class FichajeAdmin(admin.ModelAdmin):
    form = FichajeAdminForm
    list_display = ("empleado", "fecha", "hora", "tipo", "fuera_de_tolerancia", "anulado", "origen", "corregido")
    list_filter = ("empleado", "tipo", "anulado", "corregido", "fuera_de_tolerancia")
    date_hierarchy = "fecha"
    readonly_fields = ("fuera_de_tolerancia", "origen", "corregido", "registrado_en", "recibido_en", "anulado_en")
    inlines = [AuditoriaInline]

    def has_delete_permission(self, request, obj=None):
        # Los fichajes no se borran: se anulan, para que quede rastro en la auditoría.
        return False

    @transaction.atomic
    def save_model(self, request, obj, form, change):
        anterior = None
        if change:
            anterior = reglas.datos_fichaje(Fichaje.objects.get(pk=obj.pk))
        else:
            obj.origen = Fichaje.Origen.ENCARGADO
            obj.registrado_en = timezone.now()

        obj.fuera_de_tolerancia, _ = reglas.evaluar_tolerancia(obj.empleado, obj.fecha, obj.tipo, obj.hora)
        obj.corregido = True
        if obj.anulado and not obj.anulado_en:
            obj.anulado_en = timezone.now()
        if not obj.anulado:
            obj.anulado_en = None
        super().save_model(request, obj, form, change)

        if not change:
            accion = AuditoriaFichaje.Accion.CREAR
        elif obj.anulado and not anterior["anulado"]:
            accion = AuditoriaFichaje.Accion.ANULAR
        else:
            accion = AuditoriaFichaje.Accion.MODIFICAR
        AuditoriaFichaje.objects.create(
            fichaje=obj,
            accion=accion,
            usuario=request.user,
            datos_anteriores=anterior,
            datos_nuevos=reglas.datos_fichaje(obj),
            motivo=form.cleaned_data["motivo_correccion"],
        )


@admin.register(AuditoriaFichaje)
class AuditoriaFichajeAdmin(SoloLecturaAdmin):
    list_display = ("fecha_hora", "accion", "usuario", "fichaje", "motivo")
    list_filter = ("accion", "usuario")


@admin.register(AuditoriaRetiro)
class AuditoriaRetiroAdmin(SoloLecturaAdmin):
    list_display = ("fecha_hora", "accion", "usuario", "retiro", "motivo")
    list_filter = ("accion", "usuario")


class RetiroAdminForm(DiaNoLiquidadoMixin, forms.ModelForm):
    motivo_correccion = forms.CharField(
        label="Motivo de la corrección",
        widget=forms.Textarea(attrs={"rows": 2}),
        help_text="Obligatorio: queda registrado en la auditoría.",
    )

    class Meta:
        model = Retiro
        fields = ("empleado", "fecha", "hora", "producto", "cantidad", "anulado")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.instance.pk:
            self.fields["hora"].initial = timezone.localtime().strftime("%H:%M")

    def clean(self):
        datos = super().clean()
        self.validar_dia_no_liquidado(datos)
        if all(datos.get(k) for k in ("empleado", "fecha", "producto", "cantidad")) and not datos.get("anulado"):
            reglas.validar_maximo_diario(
                datos["empleado"], datos["fecha"], datos["producto"], datos["cantidad"], excluir_id=self.instance.pk
            )
        return datos


@admin.register(Retiro)
class RetiroAdmin(admin.ModelAdmin):
    form = RetiroAdminForm
    list_display = ("empleado", "fecha", "hora", "producto", "cantidad", "precio_costo", "subtotal", "anulado", "origen", "corregido")
    list_filter = ("empleado", "anulado", "corregido")
    date_hierarchy = "fecha"
    readonly_fields = ("precio_costo", "origen", "corregido", "registrado_en", "recibido_en", "anulado_en")
    inlines = [AuditoriaRetiroInline]

    def has_delete_permission(self, request, obj=None):
        # Los retiros no se borran: se anulan, para que quede rastro en la auditoría.
        return False

    @transaction.atomic
    def save_model(self, request, obj, form, change):
        anterior = None
        if change:
            original = Retiro.objects.select_related("producto").get(pk=obj.pk)
            anterior = reglas.datos_retiro(original)
            if original.producto_id != obj.producto_id:
                obj.precio_costo = obj.producto.precio_costo
        else:
            obj.origen = Fichaje.Origen.ENCARGADO
            obj.precio_costo = obj.producto.precio_costo
            obj.registrado_en = timezone.now()
        obj.corregido = True
        if obj.anulado and not obj.anulado_en:
            obj.anulado_en = timezone.now()
        if not obj.anulado:
            obj.anulado_en = None
        super().save_model(request, obj, form, change)

        if not change:
            accion = AuditoriaRetiro.Accion.CREAR
        elif obj.anulado and not anterior["anulado"]:
            accion = AuditoriaRetiro.Accion.ANULAR
        else:
            accion = AuditoriaRetiro.Accion.MODIFICAR
        AuditoriaRetiro.objects.create(
            retiro=obj,
            accion=accion,
            usuario=request.user,
            datos_anteriores=anterior,
            datos_nuevos=reglas.datos_retiro(obj),
            motivo=form.cleaned_data["motivo_correccion"],
        )


class PagoAdminForm(forms.ModelForm):
    """Alta: registra un adelanto. Edición: solo permite anularlo, con motivo."""

    motivo = forms.CharField(
        label="Motivo de la anulación", required=False, widget=forms.Textarea(attrs={"rows": 2})
    )
    anular = forms.BooleanField(label="Anular este pago", required=False)

    class Meta:
        model = Pago
        fields = ("empleado", "fecha", "hora", "monto", "observacion")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.instance.pk:
            self.fields["fecha"].initial = timezone.localdate()
            self.fields["hora"].initial = timezone.localtime().strftime("%H:%M")
            del self.fields["anular"], self.fields["motivo"]

    def clean(self):
        datos = super().clean()
        if self.instance.pk:
            if datos.get("anular"):
                if not (datos.get("motivo") or "").strip():
                    raise ValidationError("El motivo de la anulación es obligatorio.")
                if self.instance.liquidacion_id and self.instance.liquidacion.estado == Liquidacion.Estado.VIGENTE:
                    raise ValidationError(
                        "El pago está aplicado en una liquidación vigente: primero anulá esa liquidación."
                    )
                reglas.validar_dia_no_liquidado(self.instance.empleado, self.instance.fecha)
        elif datos.get("empleado") and datos.get("fecha"):
            liquidaciones.validar_pago_suelto(datos["empleado"], datos["fecha"])
        return datos


@admin.register(Pago)
class PagoAdmin(admin.ModelAdmin):
    form = PagoAdminForm
    list_display = ("empleado", "fecha", "hora", "tipo", "monto", "liquidacion", "anulado", "registrado_por")
    list_filter = ("empleado", "tipo", "anulado")
    date_hierarchy = "fecha"

    def get_readonly_fields(self, request, obj=None):
        if obj is None:
            return ()
        return ("empleado", "tipo", "fecha", "hora", "monto", "observacion", "liquidacion", "liquidacion_origen",
                "anulado", "anulado_por", "anulado_en", "motivo_anulacion", "registrado_por", "creado_en")

    def get_fields(self, request, obj=None):
        if obj is None:
            return ("empleado", "fecha", "hora", "monto", "observacion")
        campos = list(self.get_readonly_fields(request, obj))
        if not obj.anulado:
            campos += ["anular", "motivo"]
        return campos

    def has_delete_permission(self, request, obj=None):
        return False

    def save_model(self, request, obj, form, change):
        if not change:
            obj.tipo = Pago.Tipo.ADELANTO
            obj.registrado_por = request.user
            super().save_model(request, obj, form, change)
        elif form.cleaned_data.get("anular"):
            liquidaciones.anular_pago(obj, request.user, form.cleaned_data["motivo"])


class LiquidacionAltaForm(forms.ModelForm):
    """Alta: el desde lo fija el sistema; el encargado indica hasta y monto pagado."""

    hasta = forms.DateField(
        required=False, label="Hasta",
        help_text="Vacío = el sugerido según la modalidad del empleado (sin pasar de hoy).",
    )
    monto_pagado = forms.DecimalField(min_value=0, decimal_places=2, label="Monto pagado")
    fecha_pago = forms.DateField(required=False, label="Fecha del pago", help_text="Vacío = hoy.")
    hora_pago = forms.TimeField(required=False, label="Hora del pago", help_text="Vacío = ahora.")

    class Meta:
        model = Liquidacion
        fields = ("empleado", "observacion")

    def clean(self):
        datos = super().clean()
        if datos.get("empleado"):
            # Se valida corriendo la liquidación y descartándola; se guarda de verdad en save_model.
            try:
                with transaction.atomic():
                    liquidaciones.liquidar(
                        datos["empleado"], hasta=datos.get("hasta"), monto_pagado=datos.get("monto_pagado") or 0,
                        registrado_por=self.usuario, fecha_pago=datos.get("fecha_pago"),
                        hora_pago=datos.get("hora_pago"), observacion=datos.get("observacion", ""),
                    )
                    transaction.set_rollback(True)
            except ValidationError as e:
                raise ValidationError(e.messages)
        return datos


class LiquidacionAnularForm(forms.ModelForm):
    anular = forms.BooleanField(label="Anular esta liquidación", required=False)
    motivo = forms.CharField(
        label="Motivo de la anulación", required=False, widget=forms.Textarea(attrs={"rows": 2})
    )

    class Meta:
        model = Liquidacion
        fields = ()

    def clean(self):
        datos = super().clean()
        if datos.get("anular"):
            if not (datos.get("motivo") or "").strip():
                raise ValidationError("El motivo de la anulación es obligatorio.")
            ultima = liquidaciones.ultima_vigente(self.instance.empleado)
            if not ultima or ultima.pk != self.instance.pk:
                raise ValidationError("Solo se puede anular la última liquidación vigente del empleado.")
        return datos


@admin.register(Liquidacion)
class LiquidacionAdmin(admin.ModelAdmin):
    list_display = ("empleado", "desde", "hasta", "total_a_pagar", "monto_pagado", "saldo_resultante",
                    "estado", "diferencia")
    list_filter = ("empleado", "estado")
    date_hierarchy = "desde"
    CAMPOS = ("empleado", "desde", "hasta", "modalidad", "saldo_anterior", "minutos_trabajados", "ganado",
              "retiros", "adelantos", "total_a_pagar", "monto_pagado", "saldo_resultante", "diferencia",
              "observacion", "estado", "registrado_por", "creada_en", "anulada_por", "anulada_en",
              "motivo_anulacion", "pagos_aplicados")

    @admin.display(description="Pagos aplicados")
    def pagos_aplicados(self, obj):
        pagos = obj.pagos.order_by("fecha", "hora")
        if not pagos:
            return "-"
        return format_html_join(
            mark_safe("<br>"), "{} {} {} - ${}{}",
            ((p.get_tipo_display(), p.fecha.strftime("%d/%m/%Y"), p.hora.strftime("%H:%M"), p.monto,
              " (anulado)" if p.anulado else "") for p in pagos),
        )

    @admin.display(description="Diferencia por sincronización")
    def diferencia(self, obj):
        return liquidaciones.diferencia(obj)

    def get_form(self, request, obj=None, **kwargs):
        kwargs["form"] = LiquidacionAnularForm if obj else LiquidacionAltaForm
        form = super().get_form(request, obj, **kwargs)
        form.usuario = request.user
        return form

    def get_readonly_fields(self, request, obj=None):
        return self.CAMPOS if obj else ()

    def get_fields(self, request, obj=None):
        if obj is None:
            return ("empleado", "hasta", "monto_pagado", "fecha_pago", "hora_pago", "observacion")
        return self.CAMPOS + (("anular", "motivo") if obj.estado == Liquidacion.Estado.VIGENTE else ())

    def has_delete_permission(self, request, obj=None):
        return False

    def save_model(self, request, obj, form, change):
        if not change:
            d = form.cleaned_data
            nueva = liquidaciones.liquidar(
                d["empleado"], hasta=d.get("hasta"), monto_pagado=d.get("monto_pagado") or 0,
                registrado_por=request.user, fecha_pago=d.get("fecha_pago"), hora_pago=d.get("hora_pago"),
                observacion=d.get("observacion", ""),
            )
            obj.pk = nueva.pk
            obj._state.adding = False
            obj.refresh_from_db()
        elif form.cleaned_data.get("anular"):
            liquidaciones.anular(obj, request.user, form.cleaned_data["motivo"])


@admin.register(Notificacion)
class NotificacionAdmin(admin.ModelAdmin):
    list_display = ("creada_en", "destinatario", "tipo", "mensaje", "destacada", "leida")
    list_filter = ("tipo", "destacada", "leida", "empleado")
    list_editable = ("leida",)
    readonly_fields = ("destinatario", "empleado", "tipo", "mensaje", "fecha", "referencia_id", "destacada", "creada_en")

    def has_add_permission(self, request):
        return False

    def get_queryset(self, request):
        return super().get_queryset(request).filter(destinatario=request.user)
