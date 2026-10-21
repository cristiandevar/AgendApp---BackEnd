"""
Liquidaciones por período contiguo.

- Cada liquidación empieza el día siguiente al `hasta` de la última vigente. La primera
  empieza en la fecha de alta del empleado (o en su primer movimiento, si hay alguno
  anterior, para que ningún día quede sin liquidar).
- El encargado elige solo el `hasta` (el sistema sugiere uno según la modalidad del
  empleado) y el monto pagado, que puede ser menor al total: lo que falta queda como
  saldo y es el saldo anterior de la próxima liquidación.

Cuenta de una liquidación:

    saldo anterior = lo que quedó pendiente de las liquidaciones vigentes previas
                     (+ diferencias que hayan llegado después por sincronización)
    total a pagar  = saldo anterior + ganado - retiros - adelantos pendientes
    saldo resultante = total a pagar - monto pagado

- Los adelantos (pagos entregados sin liquidar) quedan pendientes hasta la próxima
  liquidación, que los descuenta y los asocia a ella.
- Anular: solo la última vigente, con motivo. Sus pagos (el propio y los adelantos que
  había aplicado) vuelven a quedar pendientes: el dinero se entregó, así que al volver
  a liquidar el período se descuenta.
- Diferencia: si después de liquidar llegan movimientos del período por
  sincronización, el ganado - retiros actual ya no coincide con el congelado. Esa
  diferencia aparece en el saldo anterior de la liquidación siguiente.
"""
import calendar
from datetime import date, timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Min, Sum
from django.utils import timezone

from . import calculos
from .models import Fichaje, Liquidacion, Pago, Retiro, Usuario

CERO = Decimal("0.00")
CENTAVOS = Decimal("0.01")


def _ddmm(fecha):
    return fecha.strftime("%d/%m/%Y")


def _suma(qs):
    return qs.aggregate(t=Sum("monto"))["t"] or CERO


def ultima_vigente(empleado):
    return (
        Liquidacion.objects.filter(empleado=empleado, estado=Liquidacion.Estado.VIGENTE)
        .order_by("-hasta")
        .first()
    )


def proximo_desde(empleado):
    ultima = ultima_vigente(empleado)
    if ultima:
        return ultima.hasta + timedelta(days=1)
    primeros = [empleado.fecha_alta]
    for Modelo in (Fichaje, Retiro, Pago):
        primero = Modelo.objects.filter(empleado=empleado, anulado=False).aggregate(m=Min("fecha"))["m"]
        if primero:
            primeros.append(primero)
    return min(primeros)


def hasta_sugerido(modalidad, desde, hoy=None):
    """Fin del período según el acuerdo de pago del empleado, sin pasar de hoy."""
    hoy = hoy or timezone.localdate()
    M = Usuario.Modalidad
    if modalidad == M.DIARIA:
        fin = desde
    elif modalidad == M.SEMANAL:
        fin = desde + timedelta(days=6)
    elif modalidad == M.QUINCENAL:
        ultimo_dia = calendar.monthrange(desde.year, desde.month)[1]
        fin = desde.replace(day=15) if desde.day <= 15 else desde.replace(day=ultimo_dia)
    elif modalidad == M.MENSUAL:
        fin = desde.replace(day=calendar.monthrange(desde.year, desde.month)[1])
    else:  # TRIMESTRAL
        mes_fin = ((desde.month - 1) // 3 + 1) * 3
        fin = date(desde.year, mes_fin, calendar.monthrange(desde.year, mes_fin)[1])
    return min(fin, hoy)


def _neto_hasta(empleado, hasta):
    """Ganado - retiros de todos los días hasta `hasta` inclusive."""
    return sum((d["ganado"] - d["retiros"] for d in calculos.datos_por_dia(empleado, hasta).values()), CERO)


def saldo_anterior(empleado, desde):
    aplicados = _suma(
        Pago.objects.filter(empleado=empleado, anulado=False, liquidacion__estado=Liquidacion.Estado.VIGENTE)
    )
    return (_neto_hasta(empleado, desde - timedelta(days=1)) - aplicados).quantize(CENTAVOS)


def adelantos_pendientes(empleado):
    return Pago.objects.filter(empleado=empleado, anulado=False, liquidacion__isnull=True)


def previsualizar(empleado, hasta=None, hoy=None):
    """Lo que el encargado ve antes de confirmar: período, totales y detalle por día."""
    hoy = hoy or timezone.localdate()
    desde = proximo_desde(empleado)
    if desde > hoy:
        raise ValidationError(
            f"{empleado.nombre_completo} ya está liquidado hasta el {_ddmm(desde - timedelta(days=1))}."
        )
    hasta = hasta or hasta_sugerido(empleado.modalidad_liquidacion, desde, hoy)
    if hasta < desde:
        raise ValidationError(
            f"La fecha hasta no puede ser anterior al {_ddmm(desde)} (día siguiente a la última liquidación)."
        )
    if hasta > hoy:
        raise ValidationError("No se puede liquidar días que todavía no ocurrieron.")

    periodo = calculos.totales_periodo(empleado, desde, hasta)
    anterior = saldo_anterior(empleado, desde)
    adelantos = _suma(adelantos_pendientes(empleado)).quantize(CENTAVOS)
    return {
        "empleado": empleado.pk,
        "modalidad": empleado.modalidad_liquidacion,
        "desde": desde,
        "hasta": hasta,
        "saldo_anterior": anterior,
        "minutos_trabajados": periodo["minutos_trabajados"],
        "horas_trabajadas": periodo["horas_trabajadas"],
        "ganado": periodo["ganado"],
        "retiros": periodo["retiros"],
        "adelantos": adelantos,
        "total_a_pagar": (anterior + periodo["ganado"] - periodo["retiros"] - adelantos).quantize(CENTAVOS),
        "dias_con_turno_abierto": periodo["dias_con_turno_abierto"],
        "dias": periodo["dias"],
    }


@transaction.atomic
def liquidar(empleado, *, monto_pagado, hasta=None, registrado_por, fecha_pago=None, hora_pago=None,
             observacion="", hoy=None):
    hoy = hoy or timezone.localdate()
    # Bloqueo para que dos liquidaciones simultáneas del mismo empleado no se superpongan.
    Usuario.objects.select_for_update().get(pk=empleado.pk)

    datos = previsualizar(empleado, hasta, hoy)
    if datos["dias_con_turno_abierto"]:
        dias = ", ".join(_ddmm(d) for d in datos["dias_con_turno_abierto"])
        raise ValidationError(
            f"Hay turnos abiertos (entrada sin salida) el {dias}: completá la salida antes de liquidar."
        )
    monto_pagado = Decimal(str(monto_pagado))
    if monto_pagado < 0:
        raise ValidationError("El monto pagado no puede ser negativo.")
    fecha_pago = fecha_pago or hoy
    if monto_pagado > 0 and not (datos["desde"] <= fecha_pago <= hoy):
        raise ValidationError(f"La fecha del pago debe estar entre el {_ddmm(datos['desde'])} y hoy.")

    liquidacion = Liquidacion.objects.create(
        empleado=empleado,
        desde=datos["desde"],
        hasta=datos["hasta"],
        modalidad=empleado.modalidad_liquidacion,
        saldo_anterior=datos["saldo_anterior"],
        minutos_trabajados=datos["minutos_trabajados"],
        ganado=datos["ganado"],
        retiros=datos["retiros"],
        adelantos=datos["adelantos"],
        total_a_pagar=datos["total_a_pagar"],
        monto_pagado=monto_pagado,
        saldo_resultante=datos["total_a_pagar"] - monto_pagado,
        observacion=observacion,
        registrado_por=registrado_por,
    )
    adelantos_pendientes(empleado).update(liquidacion=liquidacion)
    if monto_pagado > 0:
        Pago.objects.create(
            empleado=empleado, tipo=Pago.Tipo.LIQUIDACION, fecha=fecha_pago,
            hora=hora_pago or timezone.localtime().time().replace(second=0, microsecond=0),
            monto=monto_pagado, liquidacion=liquidacion, liquidacion_origen=liquidacion,
            observacion=observacion, registrado_por=registrado_por,
        )
    return liquidacion


@transaction.atomic
def anular(liquidacion, usuario, motivo):
    if not (motivo or "").strip():
        raise ValidationError("El motivo de la anulación es obligatorio.")
    if liquidacion.estado == Liquidacion.Estado.ANULADA:
        raise ValidationError("La liquidación ya está anulada.")
    ultima = ultima_vigente(liquidacion.empleado)
    if ultima.pk != liquidacion.pk:
        raise ValidationError(
            f"Solo se puede anular la última liquidación vigente (del {_ddmm(ultima.desde)} al "
            f"{_ddmm(ultima.hasta)}). Anulá primero las posteriores."
        )
    liquidacion.estado = Liquidacion.Estado.ANULADA
    liquidacion.anulada_por = usuario
    liquidacion.anulada_en = timezone.now()
    liquidacion.motivo_anulacion = motivo.strip()
    liquidacion.save()
    # El dinero ya se entregó: sus pagos quedan pendientes de aplicar en la próxima liquidación.
    liquidacion.pagos.update(liquidacion=None)
    return liquidacion


def diferencia(liquidacion):
    """
    Ganado - retiros del período hoy, menos lo congelado al liquidar.
    Distinto de cero = llegaron movimientos del período después de liquidar.
    """
    periodo = calculos.totales_periodo(liquidacion.empleado, liquidacion.desde, liquidacion.hasta)
    actual = periodo["ganado"] - periodo["retiros"]
    return (actual - (liquidacion.ganado - liquidacion.retiros)).quantize(CENTAVOS)


def detalle(liquidacion):
    """Detalle por día del período con su estado de pago actual."""
    estados = calculos.estado_pago_por_dia(liquidacion.empleado)
    dias = calculos.totales_periodo(liquidacion.empleado, liquidacion.desde, liquidacion.hasta)["dias"]
    for dia in dias:
        estado = estados.get(dia["fecha"])
        dia["estado_pago"] = estado["estado"] if estado else calculos.EstadoPago.SIN_MONTO
        dia["pendiente"] = estado["pendiente"] if estado else CERO
    return dias


def validar_pago_suelto(empleado, fecha, hoy=None):
    """Un adelanto se registra con fecha de hoy o anterior, en un día no liquidado."""
    from . import reglas

    hoy = hoy or timezone.localdate()
    if fecha > hoy:
        raise ValidationError("No se puede registrar un pago con fecha futura.")
    reglas.validar_dia_no_liquidado(empleado, fecha)


@transaction.atomic
def registrar_adelanto(empleado, *, fecha, monto, registrado_por, hora=None, observacion="", hoy=None):
    monto = Decimal(str(monto))
    if monto <= 0:
        raise ValidationError("El monto debe ser mayor a cero.")
    validar_pago_suelto(empleado, fecha, hoy)
    return Pago.objects.create(
        empleado=empleado, tipo=Pago.Tipo.ADELANTO, fecha=fecha,
        hora=hora or timezone.localtime().time().replace(second=0, microsecond=0),
        monto=monto, observacion=observacion, registrado_por=registrado_por,
    )


@transaction.atomic
def anular_pago(pago, usuario, motivo):
    """Para corregir un pago mal cargado. Si ya está aplicado en una liquidación vigente, primero hay que anularla."""
    from . import reglas

    if not (motivo or "").strip():
        raise ValidationError("El motivo de la anulación es obligatorio.")
    if pago.anulado:
        raise ValidationError("El pago ya está anulado.")
    if pago.liquidacion_id and pago.liquidacion.estado == Liquidacion.Estado.VIGENTE:
        raise ValidationError(
            f"El pago está aplicado en la liquidación del {_ddmm(pago.liquidacion.desde)} al "
            f"{_ddmm(pago.liquidacion.hasta)}. Para corregirlo, primero anulá esa liquidación."
        )
    reglas.validar_dia_no_liquidado(pago.empleado, pago.fecha)
    pago.anulado = True
    pago.anulado_por = usuario
    pago.anulado_en = timezone.now()
    pago.motivo_anulacion = motivo.strip()
    pago.save()
    return pago
