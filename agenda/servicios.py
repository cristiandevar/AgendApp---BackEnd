"""
Operaciones del empleado sobre su agenda: fichar, anular fichajes y registrar,
modificar o anular retiros. Cada operación valida las reglas, deja rastro en la
auditoría cuando corresponde y genera la notificación para el encargado.

Las va a usar la sincronización (Fase 4). El parámetro `ahora` es el momento en
que el empleado hizo la acción en su celular, que puede ser anterior al momento
en que llega al servidor si estaba sin conexión.
"""
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from . import reglas
from .models import AuditoriaFichaje, AuditoriaRetiro, Fichaje, Notificacion, Retiro, Usuario


def formato_pesos(monto):
    entero, _, decimales = f"{monto:,.2f}".partition(".")
    return f"${entero.replace(',', '.')},{decimales}"


def _notificar(tipo, empleado, fecha, referencia_id, mensaje, destacada=False):
    encargados = Usuario.objects.filter(Q(rol=Usuario.Rol.ENCARGADO) | Q(is_superuser=True), is_active=True).exclude(
        pk=empleado.pk
    )
    Notificacion.objects.bulk_create(
        Notificacion(
            destinatario=encargado, empleado=empleado, tipo=tipo, mensaje=mensaje[:300],
            fecha=fecha, referencia_id=referencia_id, destacada=destacada,
        )
        for encargado in encargados
    )


def _fecha_txt(fecha):
    return fecha.strftime("%d/%m")


def _controlar_titular(registro, usuario):
    if registro.empleado_id != usuario.pk:
        raise ValidationError("Solo podés modificar tus propios registros.")


def _controlar_plazo(registro, ahora, que):
    if registro.anulado:
        raise ValidationError(f"El {que} ya está anulado.")
    if not reglas.dentro_del_plazo(registro, ahora):
        raise ValidationError(
            f"Pasó el plazo para cambiar este {que}. Pedile al encargado que lo corrija."
        )


# ---------- Fichajes ----------

@transaction.atomic
def registrar_fichaje(empleado, *, fecha, hora, tipo, motivo="", registrado_en=None, id=None):
    activos = Fichaje.objects.filter(empleado=empleado, fecha=fecha, anulado=False)
    reglas.validar_secuencia([(f.hora, f.tipo) for f in activos] + [(hora, tipo)])
    fuera, referencia = reglas.evaluar_tolerancia(empleado, fecha, tipo, hora)
    reglas.validar_motivo(fuera, motivo)

    datos = dict(
        empleado=empleado, fecha=fecha, hora=hora, tipo=tipo, motivo=(motivo or "").strip(),
        fuera_de_tolerancia=fuera, registrado_en=registrado_en or timezone.now(),
    )
    if id:
        datos["id"] = id
    fichaje = Fichaje.objects.create(**datos)

    accion = "ingresó" if tipo == Fichaje.Tipo.ENTRADA else "se retiró"
    mensaje = f"{empleado.nombre_completo} {accion} a las {hora:%H:%M} ({_fecha_txt(fecha)})"
    if fuera:
        esperado = f"esperado {referencia:%H:%M}" if referencia else "sin horario asignado"
        mensaje += f". Fuera de horario ({esperado}): {fichaje.motivo}"
    _notificar(
        Notificacion.Tipo.ENTRADA if tipo == Fichaje.Tipo.ENTRADA else Notificacion.Tipo.SALIDA,
        empleado, fecha, fichaje.pk, mensaje, destacada=fuera,
    )
    return fichaje


@transaction.atomic
def anular_fichaje_empleado(fichaje, usuario, ahora=None):
    ahora = ahora or timezone.now()
    _controlar_titular(fichaje, usuario)
    _controlar_plazo(fichaje, ahora, "fichaje")

    anterior = reglas.datos_fichaje(fichaje)
    fichaje.anulado = True
    fichaje.anulado_en = ahora
    fichaje.save(update_fields=["anulado", "anulado_en", "actualizado"])
    AuditoriaFichaje.objects.create(
        fichaje=fichaje, accion=AuditoriaFichaje.Accion.ANULAR, usuario=usuario,
        datos_anteriores=anterior, datos_nuevos=reglas.datos_fichaje(fichaje),
    )
    _notificar(
        Notificacion.Tipo.FICHAJE_ANULADO, fichaje.empleado, fichaje.fecha, fichaje.pk,
        f"{usuario.nombre_completo} anuló su {fichaje.get_tipo_display().lower()} de las "
        f"{fichaje.hora:%H:%M} ({_fecha_txt(fichaje.fecha)})",
    )
    return fichaje


# ---------- Retiros ----------

def _texto_retiro(retiro):
    return f"{retiro.cantidad} x {retiro.producto.nombre} ({formato_pesos(retiro.subtotal)})"


@transaction.atomic
def registrar_retiro(empleado, *, fecha, producto, cantidad, hora=None, registrado_en=None, id=None):
    """`hora`: la del celular al registrar; si no viene, se toma de `registrado_en` (hora local)."""
    if not producto.activo:
        raise ValidationError({"producto": f"{producto.nombre} ya no está disponible."})
    reglas.validar_maximo_diario(empleado, fecha, producto, cantidad)
    registrado_en = registrado_en or timezone.now()
    hora = hora or timezone.localtime(registrado_en).time().replace(second=0, microsecond=0)
    datos = dict(
        empleado=empleado, fecha=fecha, hora=hora, producto=producto, cantidad=cantidad,
        precio_costo=producto.precio_costo, registrado_en=registrado_en,
    )
    if id:
        datos["id"] = id
    retiro = Retiro.objects.create(**datos)
    _notificar(
        Notificacion.Tipo.RETIRO, empleado, fecha, retiro.pk,
        f"{empleado.nombre_completo} retiró {_texto_retiro(retiro)} a las {hora:%H:%M} ({_fecha_txt(fecha)})",
    )
    return retiro


@transaction.atomic
def modificar_retiro_empleado(retiro, usuario, *, producto=None, cantidad=None, ahora=None):
    ahora = ahora or timezone.now()
    _controlar_titular(retiro, usuario)
    _controlar_plazo(retiro, ahora, "retiro")

    producto = producto or retiro.producto
    cantidad = cantidad or retiro.cantidad
    if producto.pk == retiro.producto_id and cantidad == retiro.cantidad:
        return retiro
    if producto.pk != retiro.producto_id and not producto.activo:
        raise ValidationError({"producto": f"{producto.nombre} ya no está disponible."})
    reglas.validar_maximo_diario(retiro.empleado, retiro.fecha, producto, cantidad, excluir_id=retiro.pk)

    anterior = reglas.datos_retiro(retiro)
    texto_anterior = _texto_retiro(retiro)
    if producto.pk != retiro.producto_id:
        retiro.producto = producto
        retiro.precio_costo = producto.precio_costo
    retiro.cantidad = cantidad
    retiro.save()
    AuditoriaRetiro.objects.create(
        retiro=retiro, accion=AuditoriaRetiro.Accion.MODIFICAR, usuario=usuario,
        datos_anteriores=anterior, datos_nuevos=reglas.datos_retiro(retiro),
    )
    _notificar(
        Notificacion.Tipo.RETIRO_MODIFICADO, retiro.empleado, retiro.fecha, retiro.pk,
        f"{usuario.nombre_completo} modificó un retiro: {texto_anterior} → {_texto_retiro(retiro)} "
        f"({_fecha_txt(retiro.fecha)})",
    )
    return retiro


@transaction.atomic
def anular_retiro_empleado(retiro, usuario, ahora=None):
    ahora = ahora or timezone.now()
    _controlar_titular(retiro, usuario)
    _controlar_plazo(retiro, ahora, "retiro")

    anterior = reglas.datos_retiro(retiro)
    retiro.anulado = True
    retiro.anulado_en = ahora
    retiro.save(update_fields=["anulado", "anulado_en", "actualizado"])
    AuditoriaRetiro.objects.create(
        retiro=retiro, accion=AuditoriaRetiro.Accion.ANULAR, usuario=usuario,
        datos_anteriores=anterior, datos_nuevos=reglas.datos_retiro(retiro),
    )
    _notificar(
        Notificacion.Tipo.RETIRO_ANULADO, retiro.empleado, retiro.fecha, retiro.pk,
        f"{usuario.nombre_completo} anuló el retiro de {_texto_retiro(retiro)} ({_fecha_txt(retiro.fecha)})",
    )
    return retiro
