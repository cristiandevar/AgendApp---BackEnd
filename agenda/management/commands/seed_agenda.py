"""
Carga datos iniciales de ejemplo. Se puede correr varias veces sin duplicar nada.

    python manage.py seed_agenda          -> usuarios, parámetros, feriados, productos, tarifas y horarios
    python manage.py seed_agenda --demo   -> además fichajes, retiros (con sus notificaciones) y un adelanto
"""
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from agenda import liquidaciones, servicios
from agenda.models import (
    Feriado,
    Fichaje,
    HorarioAsignado,
    Pago,
    Parametro,
    Producto,
    TarifaHora,
    Usuario,
)

USUARIOS = [
    # username, password, nombre, apellido, rol
    ("encargado", "encargado123", "Marta", "Gómez", Usuario.Rol.ENCARGADO),
    ("ana", "ana12345", "Ana", "Pérez", Usuario.Rol.EMPLEADO),
    ("luis", "luis12345", "Luis", "Fernández", Usuario.Rol.EMPLEADO),
]

# Feriados nacionales de fecha fija. Los trasladables (Carnaval, Semana Santa, etc.)
# los carga el encargado cada año.
FERIADOS_FIJOS = [
    ((1, 1), "Año Nuevo"),
    ((3, 24), "Día Nacional de la Memoria por la Verdad y la Justicia"),
    ((4, 2), "Día del Veterano y de los Caídos en Malvinas"),
    ((5, 1), "Día del Trabajador"),
    ((5, 25), "Día de la Revolución de Mayo"),
    ((6, 20), "Paso a la Inmortalidad del Gral. Manuel Belgrano"),
    ((7, 9), "Día de la Independencia"),
    ((12, 8), "Inmaculada Concepción de María"),
    ((12, 25), "Navidad"),
]

PRODUCTOS = [
    # nombre, precio de costo, máximo diario por empleado
    ("Agua mineral 500 ml", "600.00", 2),
    ("Gaseosa 500 ml", "1100.00", 1),
    ("Café", "900.00", 2),
    ("Medialuna", "400.00", 3),
    ("Alfajor", "700.00", 2),
    ("Sándwich de miga (x2)", "1500.00", 1),
    ("Empanada", "1200.00", 2),
    ("Galletitas paquete", "1000.00", 1),
]

TARIFAS = {"ana": "2500.00", "luis": "2200.00"}

HORARIOS = {
    # username: (días de la semana 0=lunes, [(inicio, fin), ...])
    "ana": (range(0, 5), [(time(8, 0), time(12, 0)), (time(16, 0), time(20, 0))]),
    "luis": (range(0, 6), [(time(9, 0), time(17, 0))]),
}


class Command(BaseCommand):
    help = "Carga datos iniciales de ejemplo para AgendApp (idempotente)."

    def add_arguments(self, parser):
        parser.add_argument("--demo", action="store_true", help="Agrega fichajes, retiros y un pago de ejemplo.")

    @transaction.atomic
    def handle(self, *args, **opciones):
        hoy = timezone.localdate()
        # Los usuarios de ejemplo figuran dados de alta el lunes de la semana pasada
        # (es la fecha desde la que arranca su primera liquidación).
        lunes = hoy - timedelta(days=hoy.weekday()) - timedelta(days=7)
        alta = datetime.combine(lunes, time(0, 0), tzinfo=timezone.get_current_timezone())

        usuarios = {}
        for username, password, nombre, apellido, rol in USUARIOS:
            usuario, creado = Usuario.objects.get_or_create(
                username=username,
                defaults={"first_name": nombre, "last_name": apellido, "rol": rol, "date_joined": alta},
            )
            if creado:
                usuario.set_password(password)
                usuario.save()
            usuarios[username] = usuario
        self.stdout.write(f"Usuarios: {', '.join(usuarios)}")

        for clave, valor in Parametro.DEFAULTS.items():
            Parametro.objects.get_or_create(clave=clave, defaults={"valor": valor})
        self.stdout.write("Parámetros: tolerancia 15 min, anulación 10 min, feriado x2")

        for anio in (hoy.year, hoy.year + 1):
            for (mes, dia), descripcion in FERIADOS_FIJOS:
                Feriado.objects.get_or_create(fecha=date(anio, mes, dia), defaults={"descripcion": descripcion})
        self.stdout.write(f"Feriados fijos de {hoy.year} y {hoy.year + 1}")

        for nombre, precio, maximo in PRODUCTOS:
            Producto.objects.get_or_create(
                nombre=nombre, defaults={"precio_costo": Decimal(precio), "max_diario": maximo}
            )
        self.stdout.write(f"Productos: {len(PRODUCTOS)}")

        inicio_tarifas = date(hoy.year, 1, 1)
        for username, monto in TARIFAS.items():
            TarifaHora.objects.get_or_create(
                empleado=usuarios[username], vigente_desde=inicio_tarifas, defaults={"monto": Decimal(monto)}
            )
        self.stdout.write("Tarifas por hora: Ana $2500, Luis $2200")

        # Horarios desde el lunes de la semana pasada hasta el domingo de la semana que viene.
        creados = 0
        for offset in range(21):
            dia = lunes + timedelta(days=offset)
            for username, (dias_semana, tramos) in HORARIOS.items():
                if dia.weekday() not in dias_semana:
                    continue
                for inicio, fin in tramos:
                    _, creado = HorarioAsignado.objects.get_or_create(
                        empleado=usuarios[username], fecha=dia, hora_inicio=inicio, defaults={"hora_fin": fin}
                    )
                    creados += creado
        self.stdout.write(f"Horarios asignados nuevos: {creados}")

        if opciones["demo"]:
            self._demo(usuarios, hoy)

        self.stdout.write(self.style.SUCCESS("Listo."))

    def _demo(self, usuarios, hoy):
        """Tres días hábiles anteriores a hoy para Ana, con un retraso y un adelanto (sin liquidar)."""
        ana, encargado = usuarios["ana"], usuarios["encargado"]
        dias = []
        dia = hoy - timedelta(days=1)
        while len(dias) < 3:
            if dia.weekday() < 5:
                dias.append(dia)
            dia -= timedelta(days=1)
        dias.reverse()

        marcas_por_dia = [
            [("ENTRADA", time(8, 5), ""), ("SALIDA", time(12, 0), ""), ("ENTRADA", time(16, 0), ""), ("SALIDA", time(20, 10), "")],
            [("ENTRADA", time(8, 40), "Se cortó el colectivo"), ("SALIDA", time(12, 0), ""), ("ENTRADA", time(16, 0), ""), ("SALIDA", time(20, 0), "")],
            [("ENTRADA", time(8, 0), ""), ("SALIDA", time(12, 30), "Me pidieron quedarme a recibir mercadería")],
        ]
        retiros_por_dia = [
            [("Café", 2, time(8, 30)), ("Medialuna", 3, time(10, 15))],
            [("Sándwich de miga (x2)", 1, time(11, 0)), ("Gaseosa 500 ml", 1, time(17, 45))],
            [("Empanada", 2, time(12, 0))],
        ]

        tz = timezone.get_current_timezone()
        for dia, marcas, retiros in zip(dias, marcas_por_dia, retiros_por_dia):
            if Fichaje.objects.filter(empleado=ana, fecha=dia).exists():
                continue
            for tipo, hora, motivo in marcas:
                servicios.registrar_fichaje(
                    ana, fecha=dia, hora=hora, tipo=tipo, motivo=motivo,
                    registrado_en=datetime.combine(dia, hora, tzinfo=tz),
                )
            for nombre, cantidad, hora in retiros:
                servicios.registrar_retiro(
                    ana, fecha=dia, producto=Producto.objects.get(nombre=nombre), cantidad=cantidad,
                    hora=hora, registrado_en=datetime.combine(dia, hora, tzinfo=tz),
                )

        if not Pago.objects.filter(empleado=ana).exists():
            liquidaciones.registrar_adelanto(
                ana, fecha=dias[1], hora=time(20, 5), monto=Decimal("30000.00"),
                observacion="Adelanto en efectivo", registrado_por=encargado,
            )
        self.stdout.write(f"Demo: fichajes y retiros de Ana para {', '.join(d.strftime('%d/%m') for d in dias)}")
