"""
Reglas de negocio de AgendApp (validaciones).

Se mantienen sin dependencias de la API para poder usarlas desde el Django Admin,
la API y más adelante la sincronización. La app Android replica estas mismas reglas
para funcionar sin conexión.
"""
from datetime import timedelta

from django.core.exceptions import ValidationError
from django.db.models import Sum
from django.utils import timezone

from .models import Fichaje, HorarioAsignado, Liquidacion, Parametro, Retiro


def _minutos(hora):
    return hora.hour * 60 + hora.minute


def validar_secuencia(marcas):
    """
    marcas: lista de (hora, tipo) de los fichajes NO anulados de un día.
    Ordenadas por hora deben alternar ENTRADA, SALIDA, ENTRADA, SALIDA...
    empezando por ENTRADA y sin horas repetidas. La última puede ser una
    ENTRADA (turno todavía abierto).
    """
    ordenadas = sorted(marcas, key=lambda m: m[0])
    for i, (hora, tipo) in enumerate(ordenadas):
        esperado = Fichaje.Tipo.ENTRADA if i % 2 == 0 else Fichaje.Tipo.SALIDA
        if tipo != esperado:
            raise ValidationError(
                f"Secuencia inválida a las {hora:%H:%M}: se esperaba una "
                f"{'entrada' if esperado == Fichaje.Tipo.ENTRADA else 'salida'}."
            )
        if i > 0 and hora == ordenadas[i - 1][0]:
            raise ValidationError(f"Hay dos fichajes a la misma hora ({hora:%H:%M}).")


def evaluar_tolerancia(empleado, fecha, tipo, hora):
    """
    Compara la marca con el horario asignado del día.
    Devuelve (fuera_de_tolerancia, hora_de_referencia).

    - ENTRADA se compara con el inicio de horario más cercano; SALIDA con el fin más cercano.
    - Si ese día no tiene horario asignado, la marca se considera fuera de horario.
    """
    tolerancia = int(Parametro.obtener(Parametro.Clave.TOLERANCIA_MINUTOS))
    horarios = HorarioAsignado.objects.filter(empleado=empleado, fecha=fecha)
    if tipo == Fichaje.Tipo.ENTRADA:
        referencias = [h.hora_inicio for h in horarios]
    else:
        referencias = [h.hora_fin for h in horarios]
    if not referencias:
        return True, None
    referencia = min(referencias, key=lambda r: abs(_minutos(r) - _minutos(hora)))
    fuera = abs(_minutos(referencia) - _minutos(hora)) > tolerancia
    return fuera, referencia


def validar_motivo(fuera_de_tolerancia, motivo):
    if fuera_de_tolerancia and not (motivo or "").strip():
        raise ValidationError(
            {"motivo": "La marca está fuera del horario asignado (más allá de la tolerancia): el motivo es obligatorio."}
        )


def dentro_del_plazo(registro, ahora=None):
    """
    El empleado puede anular un fichaje, o modificar/anular un retiro, solo dentro
    del plazo configurado (10 min por defecto) desde que lo registró.
    Pasado ese plazo, solo el encargado puede cambiarlo (con motivo).
    """
    ahora = ahora or timezone.now()
    plazo = int(Parametro.obtener(Parametro.Clave.ANULACION_FICHAJE_MINUTOS))
    return not registro.anulado and ahora - registro.registrado_en <= timedelta(minutes=plazo)


def validar_maximo_diario(empleado, fecha, producto, cantidad, excluir_id=None):
    """Controla que el empleado no supere la cantidad máxima diaria del producto."""
    if not producto.max_diario:
        return
    ya_retirado = (
        Retiro.objects.filter(empleado=empleado, fecha=fecha, producto=producto, anulado=False)
        .exclude(pk=excluir_id)
        .aggregate(total=Sum("cantidad"))["total"]
        or 0
    )
    if ya_retirado + cantidad > producto.max_diario:
        disponible = max(producto.max_diario - ya_retirado, 0)
        raise ValidationError(
            {"cantidad": f"Supera el máximo diario de {producto.nombre} ({producto.max_diario}). "
                         f"Ya retiró {ya_retirado} hoy; puede retirar hasta {disponible} más."}
        )


def datos_fichaje(fichaje):
    """Foto serializable de un fichaje, para la auditoría."""
    return {
        "fecha": fichaje.fecha.isoformat() if fichaje.fecha else None,
        "hora": fichaje.hora.strftime("%H:%M") if fichaje.hora else None,
        "tipo": fichaje.tipo,
        "motivo": fichaje.motivo,
        "anulado": fichaje.anulado,
    }


def datos_retiro(retiro):
    """Foto serializable de un retiro, para la auditoría."""
    return {
        "fecha": retiro.fecha.isoformat() if retiro.fecha else None,
        "hora": retiro.hora.strftime("%H:%M") if retiro.hora else None,
        "producto": retiro.producto.nombre if retiro.producto_id else None,
        "cantidad": retiro.cantidad,
        "precio_costo": str(retiro.precio_costo) if retiro.precio_costo is not None else None,
        "anulado": retiro.anulado,
    }


def liquidacion_vigente_en(empleado, fecha):
    """La liquidación vigente que cubre esa fecha, o None."""
    empleado_id = getattr(empleado, "pk", empleado)
    return Liquidacion.objects.filter(
        empleado_id=empleado_id, estado=Liquidacion.Estado.VIGENTE, desde__lte=fecha, hasta__gte=fecha
    ).first()


def validar_dia_no_liquidado(empleado, *fechas):
    """
    El encargado no puede cargar, corregir ni anular movimientos de un día liquidado:
    primero tiene que anular la liquidación. (Lo que llega por sincronización del
    celular del empleado sí se acepta, porque ya ocurrió.)
    """
    for fecha in fechas:
        if not fecha:
            continue
        liquidacion = liquidacion_vigente_en(empleado, fecha)
        if liquidacion:
            raise ValidationError(
                f"El {fecha:%d/%m/%Y} está liquidado (liquidación del {liquidacion.desde:%d/%m/%Y} al "
                f"{liquidacion.hasta:%d/%m/%Y}). Para corregirlo, primero anulá esa liquidación."
            )
