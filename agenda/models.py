"""
Modelos de AgendApp.

Las entidades que se crean en el celular sin conexión (Fichaje, Retiro) usan UUID
como clave primaria, para que el dispositivo pueda generar el id y al sincronizar
no haya choques. El resto también usa UUID por uniformidad.
"""
import uuid
from decimal import Decimal

from django.contrib.auth.models import AbstractUser
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone


class Usuario(AbstractUser):
    class Rol(models.TextChoices):
        ENCARGADO = "ENCARGADO", "Encargado"
        EMPLEADO = "EMPLEADO", "Empleado"

    class Modalidad(models.TextChoices):
        DIARIA = "DIARIA", "Diaria"
        SEMANAL = "SEMANAL", "Semanal"
        QUINCENAL = "QUINCENAL", "Quincenal"
        MENSUAL = "MENSUAL", "Mensual"
        TRIMESTRAL = "TRIMESTRAL", "Trimestral"

    rol = models.CharField(max_length=10, choices=Rol.choices, default=Rol.EMPLEADO)
    modalidad_liquidacion = models.CharField(
        max_length=10, choices=Modalidad.choices, default=Modalidad.DIARIA,
        help_text="Acuerdo de pago: define el período que se sugiere al liquidar.",
    )

    class Meta:
        verbose_name = "usuario"
        verbose_name_plural = "usuarios"
        ordering = ["first_name", "last_name", "username"]

    @property
    def es_encargado(self):
        return self.rol == self.Rol.ENCARGADO or self.is_superuser

    @property
    def nombre_completo(self):
        return self.get_full_name() or self.username

    @property
    def fecha_alta(self):
        return timezone.localdate(self.date_joined)

    def save(self, *args, **kwargs):
        # El encargado es el dueño del sistema: accede al Django Admin con todos los permisos.
        if self.rol == self.Rol.ENCARGADO:
            self.is_staff = True
            self.is_superuser = True
        super().save(*args, **kwargs)

    def __str__(self):
        return self.nombre_completo


class Parametro(models.Model):
    """Valores configurables por el encargado."""

    class Clave(models.TextChoices):
        TOLERANCIA_MINUTOS = "tolerancia_minutos", "Tolerancia de entrada/salida (minutos)"
        ANULACION_FICHAJE_MINUTOS = "anulacion_fichaje_minutos", "Plazo del empleado para anular fichajes y modificar/anular retiros (minutos)"
        MULTIPLICADOR_FERIADO = "multiplicador_feriado", "Multiplicador por defecto para feriados nuevos"

    DEFAULTS = {
        Clave.TOLERANCIA_MINUTOS: Decimal("15"),
        Clave.ANULACION_FICHAJE_MINUTOS: Decimal("10"),
        Clave.MULTIPLICADOR_FERIADO: Decimal("2"),
    }

    clave = models.CharField(max_length=40, choices=Clave.choices, unique=True)
    valor = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(0)])
    actualizado = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "parámetro"
        verbose_name_plural = "parámetros"
        ordering = ["clave"]

    @classmethod
    def obtener(cls, clave):
        fila = cls.objects.filter(clave=clave).first()
        return fila.valor if fila else cls.DEFAULTS[clave]

    def __str__(self):
        return f"{self.get_clave_display()}: {self.valor}"


def _ddmm(fecha):
    return fecha.strftime("%d/%m/%Y")


class Feriado(models.Model):
    """
    Día feriado. Guarda su propio multiplicador (tomado del parámetro al cargarlo),
    así un cambio futuro del parámetro no altera lo que se pagó en feriados pasados.
    Un feriado de fecha pasada no se puede modificar ni eliminar.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    fecha = models.DateField(unique=True)
    descripcion = models.CharField(max_length=120)
    multiplicador = models.DecimalField(
        max_digits=5, decimal_places=2, blank=True, validators=[MinValueValidator(1)],
        help_text="Si se deja vacío, toma el multiplicador por defecto de los parámetros.",
    )
    actualizado = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["fecha"]

    def save(self, *args, **kwargs):
        if self.multiplicador is None:
            self.multiplicador = Parametro.obtener(Parametro.Clave.MULTIPLICADOR_FERIADO)
        super().save(*args, **kwargs)

    def _original(self):
        return Feriado.objects.filter(pk=self.pk).first() if self.pk else None

    @staticmethod
    def _controlar_fecha(fecha):
        if fecha and fecha < timezone.localdate():
            raise ValidationError(
                f"El feriado del {_ddmm(fecha)} ya pasó: no se puede cargar, modificar ni eliminar "
                "porque cambiaría lo que se pagó ese día."
            )

    def clean(self):
        original = self._original()
        if original and (original.fecha, original.descripcion, original.multiplicador) == (
            self.fecha, self.descripcion, self.multiplicador
        ):
            return
        if original:
            self._controlar_fecha(original.fecha)
        self._controlar_fecha(self.fecha)

    def validar_eliminable(self):
        self._controlar_fecha(self.fecha)

    @property
    def es_modificable(self):
        return self.fecha >= timezone.localdate()

    def __str__(self):
        return f"{self.fecha:%d/%m/%Y} - {self.descripcion}"


class Producto(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    nombre = models.CharField(max_length=120, unique=True)
    precio_costo = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(0)])
    max_diario = models.PositiveIntegerField(
        default=0, help_text="Cantidad máxima que cada empleado puede retirar por día. 0 = sin límite."
    )
    activo = models.BooleanField(default=True)
    actualizado = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["nombre"]

    def __str__(self):
        return self.nombre


class TarifaHora(models.Model):
    """
    Monto por hora de un empleado, vigente desde una fecha. Es un historial que no se
    reescribe: para cambiar el monto se carga una tarifa nueva.

    - La fecha de vigencia de una tarifa nueva debe ser de hoy en adelante y posterior
      al último fichaje del empleado.
    - Solo se puede modificar o eliminar una tarifa que todavía no empezó a regir
      (mismas condiciones).
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    empleado = models.ForeignKey(Usuario, on_delete=models.PROTECT, related_name="tarifas")
    monto = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(0)])
    vigente_desde = models.DateField()
    actualizado = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "tarifa por hora"
        verbose_name_plural = "tarifas por hora"
        ordering = ["empleado", "-vigente_desde"]
        constraints = [
            models.UniqueConstraint(fields=["empleado", "vigente_desde"], name="tarifa_unica_por_fecha"),
        ]

    def _original(self):
        return TarifaHora.objects.filter(pk=self.pk).first() if self.pk else None

    def _ultimo_fichaje_desde(self, empleado_id, fecha):
        return (
            Fichaje.objects.filter(empleado_id=empleado_id, fecha__gte=fecha, anulado=False)
            .order_by("-fecha")
            .values_list("fecha", flat=True)
            .first()
        )

    def _controlar_fecha(self, empleado_id, fecha, existente):
        if fecha < timezone.localdate():
            if existente:
                raise ValidationError(
                    f"La tarifa vigente desde el {_ddmm(fecha)} ya empezó a regir: no se puede modificar "
                    "ni eliminar. Para cambiar el monto cargá una tarifa nueva."
                )
            raise ValidationError("La fecha de vigencia no puede ser anterior a hoy.")
        ultimo = self._ultimo_fichaje_desde(empleado_id, fecha)
        if ultimo:
            raise ValidationError(
                f"El empleado ya tiene fichajes hasta el {_ddmm(ultimo)}: la tarifa debe regir "
                "desde el día siguiente o después."
            )

    def clean(self):
        if not (self.empleado_id and self.vigente_desde):
            return
        original = self._original()
        if original:
            if original.empleado_id != self.empleado_id:
                raise ValidationError("No se puede cambiar el empleado de una tarifa.")
            if (original.monto, original.vigente_desde) == (self.monto, self.vigente_desde):
                return
            self._controlar_fecha(original.empleado_id, original.vigente_desde, existente=True)
        self._controlar_fecha(self.empleado_id, self.vigente_desde, existente=bool(original))

    def validar_eliminable(self):
        self._controlar_fecha(self.empleado_id, self.vigente_desde, existente=True)

    @property
    def es_modificable(self):
        try:
            self.validar_eliminable()
            return True
        except ValidationError:
            return False

    def __str__(self):
        return f"{self.empleado} - ${self.monto} desde {self.vigente_desde:%d/%m/%Y}"


class HorarioAsignado(models.Model):
    """Horario esperado. Puede haber más de un tramo por día (ej. mañana y tarde)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    empleado = models.ForeignKey(Usuario, on_delete=models.CASCADE, related_name="horarios")
    fecha = models.DateField()
    hora_inicio = models.TimeField()
    hora_fin = models.TimeField()
    actualizado = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "horario asignado"
        verbose_name_plural = "horarios asignados"
        ordering = ["fecha", "hora_inicio"]

    def clean(self):
        if self.hora_inicio and self.hora_fin and self.hora_inicio >= self.hora_fin:
            raise ValidationError("La hora de inicio debe ser anterior a la hora de fin (no se permiten turnos que crucen la medianoche).")
        if self.empleado_id and self.fecha and self.hora_inicio and self.hora_fin:
            superpuestos = HorarioAsignado.objects.filter(
                empleado_id=self.empleado_id,
                fecha=self.fecha,
                hora_inicio__lt=self.hora_fin,
                hora_fin__gt=self.hora_inicio,
            ).exclude(pk=self.pk)
            if superpuestos.exists():
                raise ValidationError("El horario se superpone con otro horario asignado ese día.")

    def __str__(self):
        return f"{self.empleado} {self.fecha:%d/%m/%Y} {self.hora_inicio:%H:%M}-{self.hora_fin:%H:%M}"


class Fichaje(models.Model):
    """Una marca de entrada o de salida. Los tramos trabajados se arman de a pares."""

    class Tipo(models.TextChoices):
        ENTRADA = "ENTRADA", "Entrada"
        SALIDA = "SALIDA", "Salida"

    class Origen(models.TextChoices):
        EMPLEADO = "EMPLEADO", "Empleado (desde su celular)"
        ENCARGADO = "ENCARGADO", "Encargado (backoffice)"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    empleado = models.ForeignKey(Usuario, on_delete=models.PROTECT, related_name="fichajes")
    fecha = models.DateField()
    hora = models.TimeField()
    tipo = models.CharField(max_length=7, choices=Tipo.choices)
    fuera_de_tolerancia = models.BooleanField(default=False)
    motivo = models.TextField(blank=True, help_text="Obligatorio si la marca está fuera de la tolerancia.")
    anulado = models.BooleanField(default=False)
    anulado_en = models.DateTimeField(null=True, blank=True)
    origen = models.CharField(max_length=9, choices=Origen.choices, default=Origen.EMPLEADO)
    corregido = models.BooleanField(default=False, help_text="Fue creado o modificado por el encargado.")
    registrado_en = models.DateTimeField(help_text="Momento en que se registró en el dispositivo.")
    recibido_en = models.DateTimeField(auto_now_add=True, help_text="Momento en que llegó al servidor.")
    actualizado = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["fecha", "hora"]
        indexes = [models.Index(fields=["empleado", "fecha"])]

    def __str__(self):
        estado = " (anulado)" if self.anulado else ""
        return f"{self.empleado} {self.fecha:%d/%m/%Y} {self.get_tipo_display()} {self.hora:%H:%M}{estado}"


class Accion(models.TextChoices):
    CREAR = "CREAR", "Alta"
    MODIFICAR = "MODIFICAR", "Modificación"
    ANULAR = "ANULAR", "Anulación"


class AuditoriaBase(models.Model):
    """Registro de cambios. El motivo es obligatorio solo cuando el cambio lo hace el encargado."""

    Accion = Accion

    accion = models.CharField(max_length=9, choices=Accion.choices)
    usuario = models.ForeignKey(Usuario, on_delete=models.PROTECT, related_name="+")
    fecha_hora = models.DateTimeField(auto_now_add=True)
    datos_anteriores = models.JSONField(null=True, blank=True)
    datos_nuevos = models.JSONField(null=True, blank=True)
    motivo = models.TextField(blank=True)

    class Meta:
        abstract = True
        ordering = ["-fecha_hora"]


class AuditoriaFichaje(AuditoriaBase):
    fichaje = models.ForeignKey(Fichaje, on_delete=models.PROTECT, related_name="auditoria")

    class Meta(AuditoriaBase.Meta):
        verbose_name = "auditoría de fichaje"
        verbose_name_plural = "auditoría de fichajes"

    def __str__(self):
        return f"{self.get_accion_display()} por {self.usuario} - {self.fichaje}"


class Retiro(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    empleado = models.ForeignKey(Usuario, on_delete=models.PROTECT, related_name="retiros")
    fecha = models.DateField()
    hora = models.TimeField(help_text="Hora del retiro: ordena la hoja del día (no es el timestamp técnico).")
    producto = models.ForeignKey(Producto, on_delete=models.PROTECT, related_name="retiros")
    cantidad = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    precio_costo = models.DecimalField(
        max_digits=12, decimal_places=2, help_text="Precio de costo congelado al momento del retiro."
    )
    anulado = models.BooleanField(default=False)
    anulado_en = models.DateTimeField(null=True, blank=True)
    origen = models.CharField(max_length=9, choices=Fichaje.Origen.choices, default=Fichaje.Origen.EMPLEADO)
    corregido = models.BooleanField(default=False, help_text="Fue creado o modificado por el encargado.")
    registrado_en = models.DateTimeField(help_text="Momento en que se registró en el dispositivo.")
    recibido_en = models.DateTimeField(auto_now_add=True)
    actualizado = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["fecha", "hora"]
        indexes = [models.Index(fields=["empleado", "fecha"])]

    @property
    def subtotal(self):
        return (self.precio_costo or Decimal("0")) * (self.cantidad or 0)

    def __str__(self):
        return f"{self.empleado} {self.fecha:%d/%m/%Y} {self.cantidad} x {self.producto}"


class AuditoriaRetiro(AuditoriaBase):
    retiro = models.ForeignKey(Retiro, on_delete=models.PROTECT, related_name="auditoria")

    class Meta(AuditoriaBase.Meta):
        verbose_name = "auditoría de retiro"
        verbose_name_plural = "auditoría de retiros"

    def __str__(self):
        return f"{self.get_accion_display()} por {self.usuario} - {self.retiro}"


class Liquidacion(models.Model):
    """
    Liquidación de un período (desde-hasta) de un empleado. Los períodos son contiguos:
    cada una empieza el día siguiente a la anterior (la primera, en la fecha de alta).
    Guarda los totales congelados como comprobante. Mientras está vigente, los días del
    período quedan bloqueados para correcciones del encargado; para corregir hay que
    anularla (con motivo). Lo que sincronicen después los celulares se acepta igual y
    aparece como diferencia.
    """

    class Estado(models.TextChoices):
        VIGENTE = "VIGENTE", "Vigente"
        ANULADA = "ANULADA", "Anulada"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    empleado = models.ForeignKey(Usuario, on_delete=models.PROTECT, related_name="liquidaciones")
    desde = models.DateField()
    hasta = models.DateField()
    modalidad = models.CharField(max_length=10, choices=Usuario.Modalidad.choices)
    # Totales congelados al liquidar
    saldo_anterior = models.DecimalField(max_digits=14, decimal_places=2)
    minutos_trabajados = models.PositiveIntegerField()
    ganado = models.DecimalField(max_digits=14, decimal_places=2)
    retiros = models.DecimalField(max_digits=14, decimal_places=2)
    adelantos = models.DecimalField(
        max_digits=14, decimal_places=2, help_text="Adelantos entregados que se descuentan en esta liquidación."
    )
    total_a_pagar = models.DecimalField(
        max_digits=14, decimal_places=2, help_text="Saldo anterior + ganado - retiros - adelantos."
    )
    monto_pagado = models.DecimalField(max_digits=14, decimal_places=2)
    saldo_resultante = models.DecimalField(max_digits=14, decimal_places=2)
    observacion = models.CharField(max_length=200, blank=True)
    estado = models.CharField(max_length=7, choices=Estado.choices, default=Estado.VIGENTE)
    registrado_por = models.ForeignKey(Usuario, on_delete=models.PROTECT, related_name="+")
    creada_en = models.DateTimeField(auto_now_add=True)
    anulada_por = models.ForeignKey(Usuario, on_delete=models.PROTECT, related_name="+", null=True, blank=True)
    anulada_en = models.DateTimeField(null=True, blank=True)
    motivo_anulacion = models.TextField(blank=True)

    class Meta:
        verbose_name = "liquidación"
        verbose_name_plural = "liquidaciones"
        ordering = ["empleado", "-desde"]
        indexes = [models.Index(fields=["empleado", "estado", "hasta"])]

    def __str__(self):
        estado = " (anulada)" if self.estado == self.Estado.ANULADA else ""
        return f"{self.empleado} {self.desde:%d/%m/%Y} al {self.hasta:%d/%m/%Y}{estado}"


class Pago(models.Model):
    """
    Monto recibido por el empleado. Solo lo registra el encargado.
    - LIQUIDACION: el pago que se hace al liquidar un período.
    - ADELANTO: dinero entregado sin liquidar; queda pendiente de aplicar y la próxima
      liquidación lo descuenta (y lo asocia a ella).
    `liquidacion` = la liquidación vigente en la que quedó aplicado (vacío = pendiente).
    """

    class Tipo(models.TextChoices):
        LIQUIDACION = "LIQUIDACION", "Pago de liquidación"
        ADELANTO = "ADELANTO", "Adelanto"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tipo = models.CharField(max_length=11, choices=Tipo.choices, default=Tipo.ADELANTO)
    empleado = models.ForeignKey(Usuario, on_delete=models.PROTECT, related_name="pagos")
    fecha = models.DateField()
    hora = models.TimeField(help_text="Hora del pago: ordena la hoja del día (no es el timestamp técnico).")
    monto = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(Decimal("0.01"))])
    observacion = models.CharField(max_length=200, blank=True)
    liquidacion = models.ForeignKey(
        Liquidacion, on_delete=models.PROTECT, related_name="pagos", null=True, blank=True,
        help_text="Liquidación vigente en la que quedó aplicado. Vacío = pendiente de aplicar.",
    )
    liquidacion_origen = models.ForeignKey(
        Liquidacion, on_delete=models.PROTECT, related_name="+", null=True, blank=True,
        help_text="Liquidación que generó este pago (se conserva aunque esa liquidación se anule).",
    )
    anulado = models.BooleanField(default=False)
    anulado_por = models.ForeignKey(Usuario, on_delete=models.PROTECT, related_name="+", null=True, blank=True)
    anulado_en = models.DateTimeField(null=True, blank=True)
    motivo_anulacion = models.TextField(blank=True)
    registrado_por = models.ForeignKey(Usuario, on_delete=models.PROTECT, related_name="+")
    creado_en = models.DateTimeField(auto_now_add=True)
    actualizado = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "pago"
        verbose_name_plural = "pagos"
        ordering = ["fecha", "hora"]

    def __str__(self):
        estado = " (anulado)" if self.anulado else ""
        return f"{self.get_tipo_display()} {self.empleado} {self.fecha:%d/%m/%Y} ${self.monto}{estado}"


class Notificacion(models.Model):
    """Aviso al encargado de lo que registran los empleados (fichajes y retiros)."""

    class Tipo(models.TextChoices):
        ENTRADA = "ENTRADA", "Entrada registrada"
        SALIDA = "SALIDA", "Salida registrada"
        RETIRO = "RETIRO", "Producto retirado"
        FICHAJE_ANULADO = "FICHAJE_ANULADO", "Fichaje anulado"
        RETIRO_MODIFICADO = "RETIRO_MODIFICADO", "Retiro modificado"
        RETIRO_ANULADO = "RETIRO_ANULADO", "Retiro anulado"

    destinatario = models.ForeignKey(Usuario, on_delete=models.CASCADE, related_name="notificaciones")
    empleado = models.ForeignKey(Usuario, on_delete=models.CASCADE, related_name="+")
    tipo = models.CharField(max_length=20, choices=Tipo.choices)
    mensaje = models.CharField(max_length=300)
    fecha = models.DateField(help_text="Día de la agenda al que corresponde el evento.")
    referencia_id = models.UUIDField(help_text="Id del fichaje o retiro relacionado.")
    destacada = models.BooleanField(default=False, help_text="Fuera de horario: requiere atención.")
    leida = models.BooleanField(default=False)
    creada_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "notificación"
        verbose_name_plural = "notificaciones"
        ordering = ["-creada_en"]
        indexes = [models.Index(fields=["destinatario", "leida"])]

    def __str__(self):
        return self.mensaje
