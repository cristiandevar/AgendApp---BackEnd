"""
Cálculos de AgendApp: horas trabajadas, monto ganado, retiros, pagos y saldo.

    Saldo a la fecha = Saldo anterior + Ganado - Productos retirados - Monto recibido

Un saldo positivo es dinero que el local le debe al empleado; negativo, lo que el
empleado debe (retiró más de lo que ganó). El saldo se arrastra día a día, como una
cuenta corriente: por eso las liquidaciones pueden cubrir cualquier período.
Los movimientos anulados no suman.
"""
from collections import defaultdict
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

from .models import Feriado, Fichaje, Liquidacion, Pago, Retiro, TarifaHora

CENTAVOS = Decimal("0.01")
CERO = Decimal("0.00")


def _a_minutos(hora):
    return hora.hour * 60 + hora.minute


def armar_tramos(fichajes):
    """
    Arma los tramos (entrada, salida) a partir de los fichajes NO anulados de un día.
    Devuelve (tramos, turno_abierto). Un turno abierto (entrada sin salida) no suma horas.
    """
    activos = sorted((f for f in fichajes if not f.anulado), key=lambda f: f.hora)
    tramos = []
    entrada = None
    for f in activos:
        if f.tipo == Fichaje.Tipo.ENTRADA:
            entrada = f.hora
        elif entrada is not None:
            tramos.append((entrada, f.hora))
            entrada = None
    return tramos, entrada is not None


def minutos_de_tramos(tramos):
    return sum(max(_a_minutos(s) - _a_minutos(e), 0) for e, s in tramos)


def formato_horas(minutos):
    return f"{minutos // 60}:{minutos % 60:02d}"


def calcular_ganado(minutos, tarifa, multiplicador):
    return (Decimal(minutos) / Decimal(60) * tarifa * multiplicador).quantize(CENTAVOS, ROUND_HALF_UP)


def _q(valor):
    return valor.quantize(CENTAVOS)


class _Contexto:
    """Carga en memoria lo necesario para calcular muchos días sin consultas repetidas."""

    def __init__(self, empleado, hasta):
        self.tarifas = list(
            TarifaHora.objects.filter(empleado=empleado, vigente_desde__lte=hasta).order_by("vigente_desde")
        )
        self.feriados = {f.fecha: f for f in Feriado.objects.filter(fecha__lte=hasta)}

    def multiplicador(self, fecha):
        feriado = self.feriados.get(fecha)
        return feriado.multiplicador if feriado else Decimal("1")

    def tarifa(self, fecha):
        vigente = CERO
        for t in self.tarifas:
            if t.vigente_desde <= fecha:
                vigente = t.monto
            else:
                break
        return vigente


def _dia_vacio():
    return {"minutos": 0, "ganado": CERO, "retiros": CERO, "pagos": CERO, "turno_abierto": False}


def datos_por_dia(empleado, hasta, desde=None):
    """
    {fecha: {minutos, ganado, retiros, pagos, turno_abierto}} de cada día con movimientos
    (no anulados) hasta `hasta` inclusive (y desde `desde` si se indica).
    """
    contexto = _Contexto(empleado, hasta)
    filtro = {"empleado": empleado, "fecha__lte": hasta, "anulado": False}
    if desde:
        filtro["fecha__gte"] = desde
    dias = defaultdict(_dia_vacio)

    fichajes = defaultdict(list)
    for f in Fichaje.objects.filter(**filtro):
        fichajes[f.fecha].append(f)
    for fecha, lista in fichajes.items():
        tramos, abierto = armar_tramos(lista)
        minutos = minutos_de_tramos(tramos)
        dias[fecha]["minutos"] = minutos
        dias[fecha]["turno_abierto"] = abierto
        dias[fecha]["ganado"] = calcular_ganado(minutos, contexto.tarifa(fecha), contexto.multiplicador(fecha))

    for r in Retiro.objects.filter(**filtro).only("fecha", "cantidad", "precio_costo"):
        dias[r.fecha]["retiros"] += r.subtotal
    for p in Pago.objects.filter(**filtro).only("fecha", "monto"):
        dias[p.fecha]["pagos"] += p.monto
    return dict(dias)


def saldo_hasta(empleado, hasta):
    """Saldo acumulado al cierre del día `hasta` (inclusive)."""
    total = CERO
    for d in datos_por_dia(empleado, hasta).values():
        total += d["ganado"] - d["retiros"] - d["pagos"]
    return _q(total)


def totales_periodo(empleado, desde, hasta):
    """Horas, ganado y retiros de un período, con el detalle por día."""
    dias = datos_por_dia(empleado, hasta, desde=desde)
    minutos = sum(d["minutos"] for d in dias.values())
    return {
        "desde": desde,
        "hasta": hasta,
        "minutos_trabajados": minutos,
        "horas_trabajadas": formato_horas(minutos),
        "ganado": _q(sum((d["ganado"] for d in dias.values()), CERO)),
        "retiros": _q(sum((d["retiros"] for d in dias.values()), CERO)),
        "dias_con_turno_abierto": sorted(f for f, d in dias.items() if d["turno_abierto"]),
        "dias": [
            {
                "fecha": fecha,
                "horas_trabajadas": formato_horas(d["minutos"]),
                "ganado": _q(d["ganado"]),
                "retiros": _q(d["retiros"]),
                "neto": _q(d["ganado"] - d["retiros"]),
            }
            for fecha, d in sorted(dias.items())
        ],
    }


class EstadoPago:
    PAGADO = "PAGADO"        # no queda nada pendiente de ese día (pagado o compensado)
    PARCIAL = "PARCIAL"
    PENDIENTE = "PENDIENTE"
    SIN_MONTO = "SIN_MONTO"  # ese día no generó nada a cobrar (no trabajó o retiró más de lo que ganó)


def estado_pago_por_dia(empleado, hasta=None):
    """
    Estado de pago de cada día, calculado (no guardado): todo lo pagado al empleado se
    aplica a los días más viejos primero. Así, una corrección o un sync tardío se
    reflejan solos. Devuelve {fecha: {"estado", "neto", "pendiente"}}.
    """
    from django.db.models import Sum
    from django.utils import timezone

    hasta = hasta or timezone.localdate()
    dias = datos_por_dia(empleado, hasta)
    total_pagado = (
        Pago.objects.filter(empleado=empleado, anulado=False).aggregate(t=Sum("monto"))["t"] or CERO
    )
    resultado = {}
    acumulado = CERO
    for fecha in sorted(dias):
        d = dias[fecha]
        neto = d["ganado"] - d["retiros"]
        anterior = acumulado
        acumulado += neto
        if neto <= 0:
            estado, pendiente = EstadoPago.SIN_MONTO, CERO
        elif acumulado <= total_pagado:
            estado, pendiente = EstadoPago.PAGADO, CERO
        elif anterior >= total_pagado:
            estado, pendiente = EstadoPago.PENDIENTE, neto
        else:
            estado, pendiente = EstadoPago.PARCIAL, acumulado - total_pagado
        resultado[fecha] = {"estado": estado, "neto": _q(neto), "pendiente": _q(pendiente)}
    return resultado


_ORDEN_TIPO = {"ENTRADA": 0, "RETIRO": 1, "SALIDA": 2, "PAGO": 3}


def movimientos_del_dia(empleado, fecha):
    """
    Lo que fue pasando en el día, en orden por la hora de cada movimiento (no por el
    timestamp técnico). Incluye los anulados marcados, para mostrarlos tachados.
    """
    movimientos = []
    for f in Fichaje.objects.filter(empleado=empleado, fecha=fecha):
        movimientos.append({
            "id": f.pk, "tipo": f.tipo, "hora": f.hora.strftime("%H:%M"),
            "descripcion": f.get_tipo_display(), "monto": None, "anulado": f.anulado,
            "corregido": f.corregido, "fuera_de_tolerancia": f.fuera_de_tolerancia, "motivo": f.motivo,
        })
    for r in Retiro.objects.filter(empleado=empleado, fecha=fecha).select_related("producto"):
        movimientos.append({
            "id": r.pk, "tipo": "RETIRO", "hora": r.hora.strftime("%H:%M"),
            "descripcion": f"{r.cantidad} x {r.producto.nombre}", "cantidad": r.cantidad,
            "precio_costo": r.precio_costo, "monto": _q(-r.subtotal), "anulado": r.anulado,
            "corregido": r.corregido,
        })
    for p in Pago.objects.filter(empleado=empleado, fecha=fecha).select_related("liquidacion_origen"):
        origen = p.liquidacion_origen
        if p.tipo == Pago.Tipo.LIQUIDACION and origen:
            anulada = " - anulada" if origen.estado == Liquidacion.Estado.ANULADA else ""
            descripcion = f"Monto recibido (liquidación del {origen.desde:%d/%m} al {origen.hasta:%d/%m}{anulada})"
        else:
            descripcion = "Monto recibido (adelanto)"
        movimientos.append({
            "id": p.pk, "tipo": "PAGO", "hora": p.hora.strftime("%H:%M"), "descripcion": descripcion,
            "monto": _q(-p.monto), "anulado": p.anulado, "observacion": p.observacion,
        })
    movimientos.sort(key=lambda m: (m["hora"], _ORDEN_TIPO[m["tipo"]]))
    return movimientos


def resumen_dia(empleado, fecha: date):
    """Todo lo que muestra la hoja de un día de la libreta."""
    contexto = _Contexto(empleado, fecha)
    saldo_anterior = saldo_hasta(empleado, fecha - timedelta(days=1))

    fichajes = list(Fichaje.objects.filter(empleado=empleado, fecha=fecha))
    tramos, turno_abierto = armar_tramos(fichajes)
    minutos = minutos_de_tramos(tramos)
    tarifa = contexto.tarifa(fecha)
    feriado = contexto.feriados.get(fecha)
    multiplicador = contexto.multiplicador(fecha)
    ganado = calcular_ganado(minutos, tarifa, multiplicador)

    retiros = Retiro.objects.filter(empleado=empleado, fecha=fecha, anulado=False)
    retiros_total = sum((r.subtotal for r in retiros), CERO)
    pagos_total = sum((p.monto for p in Pago.objects.filter(empleado=empleado, fecha=fecha, anulado=False)), CERO)

    liquidacion = Liquidacion.objects.filter(
        empleado=empleado, estado=Liquidacion.Estado.VIGENTE, desde__lte=fecha, hasta__gte=fecha
    ).first()
    estado = estado_pago_por_dia(empleado, fecha).get(fecha)

    return {
        "empleado": empleado.pk,
        "fecha": fecha,
        "es_feriado": feriado is not None,
        "feriado": feriado.descripcion if feriado else None,
        "multiplicador": multiplicador,
        "tarifa_hora": tarifa,
        "tramos": [{"entrada": e.strftime("%H:%M"), "salida": s.strftime("%H:%M")} for e, s in tramos],
        "turno_abierto": turno_abierto,
        "minutos_trabajados": minutos,
        "horas_trabajadas": formato_horas(minutos),
        "saldo_anterior": saldo_anterior,
        "movimientos": movimientos_del_dia(empleado, fecha),
        "ganado": ganado,
        "retiros_total": _q(retiros_total),
        "pagos_total": _q(pagos_total),
        "saldo_dia": _q(ganado - retiros_total),
        "saldo_a_la_fecha": _q(saldo_anterior + ganado - retiros_total - pagos_total),
        "liquidacion": (
            {"id": liquidacion.pk, "desde": liquidacion.desde, "hasta": liquidacion.hasta} if liquidacion else None
        ),
        "estado_pago": estado["estado"] if estado else EstadoPago.SIN_MONTO,
        "pendiente_del_dia": estado["pendiente"] if estado else CERO,
    }
