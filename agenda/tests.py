from datetime import date, datetime, time, timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from . import calculos, liquidaciones, reglas, servicios
from .models import AuditoriaFichaje, AuditoriaRetiro, Liquidacion, Notificacion, Feriado, Fichaje, HorarioAsignado, Pago, Parametro, Producto, Retiro, TarifaHora, Usuario

TZ = timezone.get_current_timezone()
DIA1 = date(2026, 10, 5)  # lunes
DIA2 = date(2026, 10, 6)


def fichar(empleado, fecha, tipo, hh, mm, anulado=False):
    return Fichaje.objects.create(
        empleado=empleado, fecha=fecha, tipo=tipo, hora=time(hh, mm), anulado=anulado,
        registrado_en=datetime.combine(fecha, time(hh, mm), tzinfo=TZ),
    )


def retirar(empleado, fecha, producto, cantidad, hora=time(10, 0)):
    return Retiro.objects.create(
        empleado=empleado, fecha=fecha, producto=producto, cantidad=cantidad, hora=hora,
        precio_costo=producto.precio_costo, registrado_en=timezone.now(),
    )


class Base(TestCase):
    def setUp(self):
        self.encargado = Usuario.objects.create_user("jefe", password="x" * 8, rol=Usuario.Rol.ENCARGADO)
        self.ana = Usuario.objects.create_user("ana", password="x" * 8)
        self.luis = Usuario.objects.create_user("luis", password="x" * 8)
        TarifaHora.objects.create(empleado=self.ana, monto=Decimal("2000"), vigente_desde=date(2026, 1, 1))
        self.cafe = Producto.objects.create(nombre="Café", precio_costo=Decimal("800"), max_diario=2)
        self.sandwich = Producto.objects.create(nombre="Sándwich", precio_costo=Decimal("1600"), max_diario=0)


class CalculosTests(Base):
    def test_ejemplo_del_diseno(self):
        # Día 1: 08:00-12:00 y 13:00-17:30 = 8,5 h x $2000 = $17000; retiros $20000 -> saldo -3000
        for tipo, hh, mm in [("ENTRADA", 8, 0), ("SALIDA", 12, 0), ("ENTRADA", 13, 0), ("SALIDA", 17, 30)]:
            fichar(self.ana, DIA1, tipo, hh, mm)
        retirar(self.ana, DIA1, self.sandwich, 12)  # 19200
        retirar(self.ana, DIA1, self.cafe, 1)       # 800
        r1 = calculos.resumen_dia(self.ana, DIA1)
        self.assertEqual(r1["horas_trabajadas"], "8:30")
        self.assertEqual(r1["ganado"], Decimal("17000.00"))
        self.assertEqual(r1["retiros_total"], Decimal("20000.00"))
        self.assertEqual(r1["saldo_a_la_fecha"], Decimal("-3000.00"))

        # Día 2: arrastra -3000, gana 17000, retira 2000, cobra 10000 -> saldo 2000
        for tipo, hh, mm in [("ENTRADA", 8, 0), ("SALIDA", 12, 0), ("ENTRADA", 13, 0), ("SALIDA", 17, 30)]:
            fichar(self.ana, DIA2, tipo, hh, mm)
        retirar(self.ana, DIA2, self.cafe, 2)
        retirar(self.ana, DIA2, self.medialuna_400(), 1)
        Pago.objects.create(empleado=self.ana, fecha=DIA2, hora=time(18, 0), monto=Decimal("10000"),
                            registrado_por=self.encargado)
        r2 = calculos.resumen_dia(self.ana, DIA2)
        self.assertEqual(r2["saldo_anterior"], Decimal("-3000.00"))
        self.assertEqual(r2["retiros_total"], Decimal("2000.00"))
        self.assertEqual(r2["pagos_total"], Decimal("10000.00"))
        self.assertEqual(r2["saldo_a_la_fecha"], Decimal("2000.00"))

    def medialuna_400(self):
        return Producto.objects.create(nombre="Medialuna", precio_costo=Decimal("400"))

    def test_turno_abierto_y_anulados_no_suman(self):
        fichar(self.ana, DIA1, "ENTRADA", 8, 0)
        fichar(self.ana, DIA1, "SALIDA", 10, 0)
        fichar(self.ana, DIA1, "SALIDA", 9, 0, anulado=True)
        fichar(self.ana, DIA1, "ENTRADA", 11, 0)  # sin salida todavía
        r = calculos.resumen_dia(self.ana, DIA1)
        self.assertEqual(r["minutos_trabajados"], 120)
        self.assertTrue(r["turno_abierto"])

    def test_feriado_paga_doble(self):
        Feriado.objects.create(fecha=DIA1, descripcion="Feriado de prueba")
        fichar(self.ana, DIA1, "ENTRADA", 9, 0)
        fichar(self.ana, DIA1, "SALIDA", 13, 0)
        r = calculos.resumen_dia(self.ana, DIA1)
        self.assertTrue(r["es_feriado"])
        self.assertEqual(r["ganado"], Decimal("16000.00"))  # 4 h x 2000 x 2

    def test_multiplicador_feriado_configurable(self):
        Parametro.objects.create(clave=Parametro.Clave.MULTIPLICADOR_FERIADO, valor=Decimal("1.5"))
        Feriado.objects.create(fecha=DIA1, descripcion="x")
        fichar(self.ana, DIA1, "ENTRADA", 9, 0)
        fichar(self.ana, DIA1, "SALIDA", 13, 0)
        self.assertEqual(calculos.resumen_dia(self.ana, DIA1)["ganado"], Decimal("12000.00"))

    def test_tarifa_segun_fecha(self):
        TarifaHora.objects.create(empleado=self.ana, monto=Decimal("3000"), vigente_desde=DIA2)
        for dia in (DIA1, DIA2):
            fichar(self.ana, dia, "ENTRADA", 9, 0)
            fichar(self.ana, dia, "SALIDA", 10, 0)
        self.assertEqual(calculos.resumen_dia(self.ana, DIA1)["ganado"], Decimal("2000.00"))
        self.assertEqual(calculos.resumen_dia(self.ana, DIA2)["ganado"], Decimal("3000.00"))

    def test_minutos_sueltos(self):
        fichar(self.ana, DIA1, "ENTRADA", 9, 0)
        fichar(self.ana, DIA1, "SALIDA", 9, 20)  # 20 min = 1/3 h
        self.assertEqual(calculos.resumen_dia(self.ana, DIA1)["ganado"], Decimal("666.67"))


class ReglasTests(Base):
    def setUp(self):
        super().setUp()
        HorarioAsignado.objects.create(empleado=self.ana, fecha=DIA1, hora_inicio=time(8, 0), hora_fin=time(12, 0))
        HorarioAsignado.objects.create(empleado=self.ana, fecha=DIA1, hora_inicio=time(16, 0), hora_fin=time(20, 0))

    def test_tolerancia(self):
        self.assertFalse(reglas.evaluar_tolerancia(self.ana, DIA1, "ENTRADA", time(8, 15))[0])
        self.assertTrue(reglas.evaluar_tolerancia(self.ana, DIA1, "ENTRADA", time(8, 16))[0])
        self.assertFalse(reglas.evaluar_tolerancia(self.ana, DIA1, "ENTRADA", time(15, 50))[0])  # turno tarde
        self.assertFalse(reglas.evaluar_tolerancia(self.ana, DIA1, "SALIDA", time(20, 10))[0])
        self.assertTrue(reglas.evaluar_tolerancia(self.ana, DIA1, "SALIDA", time(12, 30))[0])

    def test_sin_horario_asignado_es_fuera_de_tolerancia(self):
        self.assertTrue(reglas.evaluar_tolerancia(self.ana, DIA2, "ENTRADA", time(8, 0))[0])

    def test_motivo_obligatorio(self):
        with self.assertRaises(ValidationError):
            reglas.validar_motivo(True, "  ")
        reglas.validar_motivo(True, "Llegué tarde por el colectivo")
        reglas.validar_motivo(False, "")

    def test_secuencia(self):
        reglas.validar_secuencia([(time(8, 0), "ENTRADA"), (time(12, 0), "SALIDA"), (time(16, 0), "ENTRADA")])
        with self.assertRaises(ValidationError):
            reglas.validar_secuencia([(time(8, 0), "SALIDA")])
        with self.assertRaises(ValidationError):
            reglas.validar_secuencia([(time(8, 0), "ENTRADA"), (time(9, 0), "ENTRADA")])

    def test_maximo_diario(self):
        retirar(self.ana, DIA1, self.cafe, 1)
        reglas.validar_maximo_diario(self.ana, DIA1, self.cafe, 1)
        with self.assertRaises(ValidationError):
            reglas.validar_maximo_diario(self.ana, DIA1, self.cafe, 2)
        reglas.validar_maximo_diario(self.luis, DIA1, self.cafe, 2)  # el límite es por empleado
        reglas.validar_maximo_diario(self.ana, DIA1, self.sandwich, 50)  # 0 = sin límite

    def test_plazo_de_anulacion(self):
        f = fichar(self.ana, DIA1, "ENTRADA", 8, 0)
        self.assertTrue(reglas.dentro_del_plazo(f, f.registrado_en + timedelta(minutes=10)))
        self.assertFalse(reglas.dentro_del_plazo(f, f.registrado_en + timedelta(minutes=11)))

    def test_horario_no_cruza_medianoche_ni_se_superpone(self):
        with self.assertRaises(ValidationError):
            HorarioAsignado(empleado=self.ana, fecha=DIA2, hora_inicio=time(22, 0), hora_fin=time(2, 0)).clean()
        with self.assertRaises(ValidationError):
            HorarioAsignado(empleado=self.ana, fecha=DIA1, hora_inicio=time(11, 0), hora_fin=time(13, 0)).clean()


class ApiTests(Base):
    def cliente(self, username):
        c = APIClient()
        r = c.post("/api/auth/login/", {"username": username, "password": "x" * 8}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        c.credentials(HTTP_AUTHORIZATION=f"Bearer {r.json()['access']}")
        return c, r.json()

    def test_login_devuelve_rol(self):
        _, datos = self.cliente("jefe")
        self.assertEqual(datos["usuario"]["rol"], "ENCARGADO")
        _, datos = self.cliente("ana")
        self.assertEqual(datos["usuario"]["rol"], "EMPLEADO")

    def test_sin_login_rechaza(self):
        self.assertEqual(APIClient().get("/api/productos/").status_code, 401)

    def test_productos_permisos_y_baja_logica(self):
        ana, _ = self.cliente("ana")
        jefe, _ = self.cliente("jefe")
        self.assertEqual(ana.get("/api/productos/").status_code, 200)
        nuevo = {"nombre": "Agua", "precio_costo": "500.00", "max_diario": 2}
        self.assertEqual(ana.post("/api/productos/", nuevo, format="json").status_code, 403)
        r = jefe.post("/api/productos/", nuevo, format="json")
        self.assertEqual(r.status_code, 201)
        self.assertEqual(jefe.delete(f"/api/productos/{r.json()['id']}/").status_code, 204)
        self.assertFalse(Producto.objects.get(nombre="Agua").activo)
        nombres = [p["nombre"] for p in ana.get("/api/productos/?activos=1").json()]
        self.assertNotIn("Agua", nombres)

    def test_empleado_solo_ve_sus_horarios(self):
        HorarioAsignado.objects.create(empleado=self.ana, fecha=DIA1, hora_inicio=time(8, 0), hora_fin=time(12, 0))
        HorarioAsignado.objects.create(empleado=self.luis, fecha=DIA1, hora_inicio=time(9, 0), hora_fin=time(17, 0))
        ana, _ = self.cliente("ana")
        jefe, _ = self.cliente("jefe")
        self.assertEqual(len(ana.get("/api/horarios/").json()), 1)
        self.assertEqual(len(jefe.get("/api/horarios/").json()), 2)
        self.assertEqual(len(jefe.get(f"/api/horarios/?empleado={self.luis.pk}").json()), 1)

    def test_horario_invalido_por_api(self):
        jefe, _ = self.cliente("jefe")
        r = jefe.post("/api/horarios/", {"empleado": self.ana.pk, "fecha": "2026-10-07",
                                          "hora_inicio": "22:00", "hora_fin": "02:00"}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("detalle", r.json())

    def test_parametros(self):
        ana, _ = self.cliente("ana")
        jefe, _ = self.cliente("jefe")
        self.assertEqual(len(ana.get("/api/parametros/").json()), 3)
        self.assertEqual(ana.patch("/api/parametros/tolerancia_minutos/", {"valor": "20"}, format="json").status_code, 403)
        r = jefe.patch("/api/parametros/tolerancia_minutos/", {"valor": "20"}, format="json")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(Parametro.obtener(Parametro.Clave.TOLERANCIA_MINUTOS), Decimal("20"))

    def test_usuarios_solo_encargado(self):
        ana, _ = self.cliente("ana")
        jefe, _ = self.cliente("jefe")
        self.assertEqual(ana.get("/api/usuarios/").status_code, 403)
        r = jefe.post("/api/usuarios/", {"username": "pedro", "first_name": "Pedro", "password": "pedro12345",
                                          "rol": "EMPLEADO"}, format="json")
        self.assertEqual(r.status_code, 201)
        self.assertNotIn("password", r.json())
        self.assertTrue(Usuario.objects.get(username="pedro").check_password("pedro12345"))

    def test_resumen_dia(self):
        fichar(self.ana, DIA1, "ENTRADA", 9, 0)
        fichar(self.ana, DIA1, "SALIDA", 13, 0)
        ana, _ = self.cliente("ana")
        jefe, _ = self.cliente("jefe")
        r = ana.get("/api/resumen-dia/?fecha=2026-10-05")
        self.assertEqual(r.json()["ganado"], 8000.0)
        # El empleado no puede consultar a otro: el parámetro se ignora y ve lo suyo.
        r = ana.get(f"/api/resumen-dia/?fecha=2026-10-05&empleado={self.luis.pk}")
        self.assertEqual(r.json()["empleado"], self.ana.pk)
        r = jefe.get(f"/api/resumen-dia/?fecha=2026-10-05&empleado={self.ana.pk}")
        self.assertEqual(r.json()["ganado"], 8000.0)
        self.assertEqual(ana.get("/api/resumen-dia/").status_code, 400)


class ServiciosTests(Base):
    """Operaciones del empleado: plazo de 10 min, auditoría y notificaciones al encargado."""

    def setUp(self):
        super().setUp()
        HorarioAsignado.objects.create(empleado=self.ana, fecha=DIA1, hora_inicio=time(8, 0), hora_fin=time(12, 0))
        self.t0 = datetime.combine(DIA1, time(8, 0), tzinfo=TZ)

    def test_fichaje_en_horario_notifica(self):
        servicios.registrar_fichaje(self.ana, fecha=DIA1, hora=time(8, 5), tipo="ENTRADA", registrado_en=self.t0)
        n = Notificacion.objects.get()
        self.assertEqual(n.destinatario, self.encargado)
        self.assertEqual(n.tipo, "ENTRADA")
        self.assertFalse(n.destacada)
        self.assertIn("ingresó a las 08:05", n.mensaje)

    def test_fichaje_fuera_de_horario_exige_motivo_y_se_destaca(self):
        with self.assertRaises(ValidationError):
            servicios.registrar_fichaje(self.ana, fecha=DIA1, hora=time(8, 40), tipo="ENTRADA")
        self.assertEqual(Fichaje.objects.count(), 0)
        self.assertEqual(Notificacion.objects.count(), 0)
        servicios.registrar_fichaje(self.ana, fecha=DIA1, hora=time(8, 40), tipo="ENTRADA", motivo="Paro de colectivos")
        n = Notificacion.objects.get()
        self.assertTrue(n.destacada)
        self.assertIn("esperado 08:00", n.mensaje)
        self.assertIn("Paro de colectivos", n.mensaje)

    def test_fichaje_secuencia_invalida(self):
        with self.assertRaises(ValidationError):
            servicios.registrar_fichaje(self.ana, fecha=DIA1, hora=time(8, 0), tipo="SALIDA", motivo="x")

    def test_anular_fichaje_dentro_y_fuera_de_plazo(self):
        f = servicios.registrar_fichaje(self.ana, fecha=DIA1, hora=time(8, 0), tipo="ENTRADA", registrado_en=self.t0)
        with self.assertRaises(ValidationError):
            servicios.anular_fichaje_empleado(f, self.ana, ahora=self.t0 + timedelta(minutes=11))
        with self.assertRaises(ValidationError):
            servicios.anular_fichaje_empleado(f, self.luis, ahora=self.t0)  # no es suyo
        servicios.anular_fichaje_empleado(f, self.ana, ahora=self.t0 + timedelta(minutes=9))
        f.refresh_from_db()
        self.assertTrue(f.anulado)
        a = AuditoriaFichaje.objects.get()
        self.assertEqual((a.accion, a.usuario, a.motivo), ("ANULAR", self.ana, ""))  # sin justificación
        self.assertTrue(Notificacion.objects.filter(tipo="FICHAJE_ANULADO").exists())
        with self.assertRaises(ValidationError):
            servicios.anular_fichaje_empleado(f, self.ana, ahora=self.t0)  # ya anulado

    def test_retiro_congela_precio_y_notifica(self):
        r = servicios.registrar_retiro(self.ana, fecha=DIA1, producto=self.cafe, cantidad=2, registrado_en=self.t0)
        self.cafe.precio_costo = Decimal("999")
        self.cafe.save()
        r.refresh_from_db()
        self.assertEqual(r.subtotal, Decimal("1600.00"))
        self.assertIn("retiró 2 x Café ($1.600,00)", Notificacion.objects.get().mensaje)
        with self.assertRaises(ValidationError):  # máximo diario 2
            servicios.registrar_retiro(self.ana, fecha=DIA1, producto=self.cafe, cantidad=1)

    def test_modificar_retiro_dentro_del_plazo(self):
        r = servicios.registrar_retiro(self.ana, fecha=DIA1, producto=self.cafe, cantidad=2, registrado_en=self.t0)
        servicios.modificar_retiro_empleado(r, self.ana, cantidad=1, ahora=self.t0 + timedelta(minutes=5))
        servicios.modificar_retiro_empleado(r, self.ana, producto=self.sandwich, ahora=self.t0 + timedelta(minutes=6))
        r.refresh_from_db()
        self.assertEqual((r.producto, r.cantidad, r.precio_costo), (self.sandwich, 1, Decimal("1600")))
        auditorias = AuditoriaRetiro.objects.order_by("fecha_hora")
        self.assertEqual([a.accion for a in auditorias], ["MODIFICAR", "MODIFICAR"])
        self.assertEqual(auditorias[0].datos_anteriores["cantidad"], 2)
        self.assertEqual(auditorias[0].motivo, "")
        self.assertIn("2 x Café ($1.600,00) → 1 x Café ($800,00)",
                      Notificacion.objects.filter(tipo="RETIRO_MODIFICADO").order_by("creada_en").first().mensaje)

    def test_modificar_o_anular_retiro_fuera_de_plazo(self):
        r = servicios.registrar_retiro(self.ana, fecha=DIA1, producto=self.cafe, cantidad=1, registrado_en=self.t0)
        tarde = self.t0 + timedelta(minutes=11)
        with self.assertRaises(ValidationError):
            servicios.modificar_retiro_empleado(r, self.ana, cantidad=2, ahora=tarde)
        with self.assertRaises(ValidationError):
            servicios.anular_retiro_empleado(r, self.ana, ahora=tarde)
        servicios.anular_retiro_empleado(r, self.ana, ahora=self.t0 + timedelta(minutes=10))
        r.refresh_from_db()
        self.assertTrue(r.anulado)
        self.assertEqual(calculos.resumen_dia(self.ana, DIA1)["retiros_total"], Decimal("0.00"))

    def test_modificar_retiro_respeta_maximo(self):
        r = servicios.registrar_retiro(self.ana, fecha=DIA1, producto=self.cafe, cantidad=1, registrado_en=self.t0)
        servicios.modificar_retiro_empleado(r, self.ana, cantidad=2, ahora=self.t0)  # se excluye a sí mismo
        with self.assertRaises(ValidationError):
            servicios.modificar_retiro_empleado(r, self.ana, cantidad=3, ahora=self.t0)

    def test_notificaciones_solo_para_encargados_activos(self):
        otro = Usuario.objects.create_user("jefa2", password="x" * 8, rol=Usuario.Rol.ENCARGADO)
        Usuario.objects.create_user("baja", password="x" * 8, rol=Usuario.Rol.ENCARGADO, is_active=False)
        servicios.registrar_fichaje(self.ana, fecha=DIA1, hora=time(8, 0), tipo="ENTRADA")
        self.assertEqual(set(Notificacion.objects.values_list("destinatario", flat=True)), {self.encargado.pk, otro.pk})


class NotificacionesApiTests(Base):
    def cliente(self, username):
        return ApiTests.cliente(self, username)

    def test_api_notificaciones(self):
        servicios.registrar_fichaje(self.ana, fecha=DIA1, hora=time(8, 0), tipo="ENTRADA", motivo="Sin horario")
        servicios.registrar_retiro(self.ana, fecha=DIA1, producto=self.cafe, cantidad=1)
        ana, _ = self.cliente("ana")
        jefe, _ = self.cliente("jefe")
        self.assertEqual(ana.get("/api/notificaciones/").status_code, 403)
        lista = jefe.get("/api/notificaciones/").json()
        self.assertEqual([n["tipo"] for n in lista], ["RETIRO", "ENTRADA"])  # la más reciente primero
        self.assertEqual(jefe.get("/api/notificaciones/cantidad_no_leidas/").json()["cantidad"], 2)
        r = jefe.post(f"/api/notificaciones/{lista[0]['id']}/marcar_leida/")
        self.assertTrue(r.json()["leida"])
        self.assertEqual(len(jefe.get("/api/notificaciones/?no_leidas=1").json()), 1)
        self.assertEqual(jefe.post("/api/notificaciones/marcar_todas_leidas/").json()["marcadas"], 1)


class HistorialProtegidoTests(Base):
    """Tarifas y feriados que ya rigieron no se tocan, para no alterar cálculos pasados."""

    def setUp(self):
        super().setUp()
        self.hoy = timezone.localdate()
        self.ayer = self.hoy - timedelta(days=1)
        self.manana = self.hoy + timedelta(days=1)
        self.jefe, _ = ApiTests.cliente(self, "jefe")
        self.tarifa_vieja = TarifaHora.objects.get(empleado=self.ana)  # vigente desde 01/01/2026

    def test_tarifa_que_ya_rige_no_se_modifica_ni_elimina(self):
        with self.assertRaises(ValidationError):
            self.tarifa_vieja.validar_eliminable()
        self.tarifa_vieja.monto = Decimal("9999")
        with self.assertRaises(ValidationError):
            self.tarifa_vieja.clean()
        url = f"/api/tarifas/{self.tarifa_vieja.pk}/"
        r = self.jefe.patch(url, {"monto": "9999"}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("cargá una tarifa nueva", str(r.json()["detalle"]))
        r = self.jefe.delete(url)
        self.assertEqual(r.status_code, 409)
        self.assertEqual(TarifaHora.objects.get(pk=self.tarifa_vieja.pk).monto, Decimal("2000"))

    def test_tarifa_nueva_no_puede_ser_retroactiva(self):
        r = self.jefe.post("/api/tarifas/", {"empleado": self.ana.pk, "monto": "3000",
                                              "vigente_desde": self.ayer.isoformat()}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("anterior a hoy", str(r.json()["detalle"]))

    def test_tarifa_nueva_debe_ser_posterior_al_ultimo_fichaje(self):
        fichar(self.ana, self.hoy, "ENTRADA", 8, 0)
        r = self.jefe.post("/api/tarifas/", {"empleado": self.ana.pk, "monto": "3000",
                                              "vigente_desde": self.hoy.isoformat()}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("desde el día siguiente", str(r.json()["detalle"]))
        r = self.jefe.post("/api/tarifas/", {"empleado": self.ana.pk, "monto": "3000",
                                              "vigente_desde": self.manana.isoformat()}, format="json")
        self.assertEqual(r.status_code, 201)

    def test_tarifa_futura_se_puede_corregir_y_eliminar(self):
        r = self.jefe.post("/api/tarifas/", {"empleado": self.ana.pk, "monto": "300",
                                              "vigente_desde": self.manana.isoformat()}, format="json")
        url = f"/api/tarifas/{r.json()['id']}/"
        self.assertTrue(r.json()["es_modificable"])
        self.assertEqual(self.jefe.patch(url, {"monto": "3000"}, format="json").status_code, 200)
        r = self.jefe.patch(url, {"empleado": self.luis.pk}, format="json")
        self.assertEqual(r.status_code, 400)  # no se cambia el empleado
        self.assertEqual(self.jefe.delete(url).status_code, 204)

    def test_empleado_sin_fichajes_recibe_su_primera_tarifa_desde_hoy(self):
        r = self.jefe.post("/api/tarifas/", {"empleado": self.luis.pk, "monto": "2200",
                                              "vigente_desde": self.hoy.isoformat()}, format="json")
        self.assertEqual(r.status_code, 201)

    def test_listado_indica_si_es_modificable(self):
        datos = self.jefe.get(f"/api/tarifas/?empleado={self.ana.pk}").json()
        self.assertFalse(datos[0]["es_modificable"])

    def test_feriado_pasado_no_se_toca(self):
        pasado = Feriado.objects.create(fecha=self.ayer, descripcion="Ayer")
        r = self.jefe.patch(f"/api/feriados/{pasado.pk}/", {"descripcion": "x"}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertEqual(self.jefe.delete(f"/api/feriados/{pasado.pk}/").status_code, 409)
        r = self.jefe.post("/api/feriados/", {"fecha": (self.ayer - timedelta(days=1)).isoformat(),
                                               "descripcion": "Retroactivo"}, format="json")
        self.assertEqual(r.status_code, 400)

    def test_feriado_de_hoy_o_futuro_se_gestiona(self):
        r = self.jefe.post("/api/feriados/", {"fecha": self.hoy.isoformat(), "descripcion": "Hoy"}, format="json")
        self.assertEqual(r.status_code, 201)
        self.assertEqual(r.json()["multiplicador"], 2.0)
        url = f"/api/feriados/{r.json()['id']}/"
        self.assertEqual(self.jefe.patch(url, {"multiplicador": "1.5"}, format="json").status_code, 200)
        self.assertEqual(self.jefe.delete(url).status_code, 204)

    def test_cambiar_parametro_no_altera_feriados_ya_cargados(self):
        Feriado.objects.create(fecha=DIA1, descripcion="Feriado viejo")  # toma x2
        fichar(self.ana, DIA1, "ENTRADA", 9, 0)
        fichar(self.ana, DIA1, "SALIDA", 13, 0)
        r = self.jefe.patch("/api/parametros/multiplicador_feriado/", {"valor": "1.5"}, format="json")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(calculos.resumen_dia(self.ana, DIA1)["ganado"], Decimal("16000.00"))  # sigue x2
        nuevo = Feriado.objects.create(fecha=self.manana, descripcion="Nuevo")
        self.assertEqual(nuevo.multiplicador, Decimal("1.5"))


HOY = date(2026, 10, 20)
D5, D6, D15, D16 = date(2026, 10, 5), date(2026, 10, 6), date(2026, 10, 15), date(2026, 10, 16)


class LiquidacionesTests(Base):
    """Liquidaciones por período contiguo, adelantos, pagos parciales, anulación y bloqueo."""

    def setUp(self):
        super().setUp()
        # 05/10 y 06/10: 8 h cada día a $2000 = $32000. Retiro de $1600 el 05/10. Adelanto de $5000 el 06/10.
        for dia in (D5, D6):
            fichar(self.ana, dia, "ENTRADA", 8, 0)
            fichar(self.ana, dia, "SALIDA", 16, 0)
        retirar(self.ana, D5, self.sandwich, 1)
        liquidaciones.registrar_adelanto(self.ana, fecha=D6, monto=5000, registrado_por=self.encargado,
                                         hora=time(12, 0), hoy=HOY)
        self.ana.modalidad_liquidacion = Usuario.Modalidad.QUINCENAL
        self.ana.save()

    def liquidar(self, **kw):
        kw.setdefault("hoy", HOY)
        kw.setdefault("registrado_por", self.encargado)
        return liquidaciones.liquidar(self.ana, **kw)

    def test_quincena_con_adelanto_y_pago_parcial(self):
        p = liquidaciones.previsualizar(self.ana, hoy=HOY)
        self.assertEqual((p["desde"], p["hasta"]), (D5, D15))  # primer movimiento -> fin de quincena
        self.assertEqual(p["ganado"], Decimal("32000.00"))
        self.assertEqual(p["retiros"], Decimal("1600.00"))
        self.assertEqual(p["adelantos"], Decimal("5000.00"))
        self.assertEqual(p["total_a_pagar"], Decimal("25400.00"))

        liq = self.liquidar(hasta=None, monto_pagado=20000, fecha_pago=D16, hora_pago=time(9, 0))
        self.assertEqual(liq.saldo_resultante, Decimal("5400.00"))
        self.assertEqual(liq.pagos.count(), 2)  # el adelanto quedó aplicado + el pago propio
        propio = liq.pagos.get(tipo=Pago.Tipo.LIQUIDACION)
        self.assertEqual((propio.fecha, propio.monto, propio.liquidacion_origen), (D16, Decimal("20000"), liq))

        siguiente = liquidaciones.previsualizar(self.ana, hoy=HOY)
        self.assertEqual(siguiente["desde"], D16)
        self.assertEqual(siguiente["saldo_anterior"], Decimal("5400.00"))  # lo que quedó pendiente
        self.assertEqual(siguiente["adelantos"], Decimal("0.00"))

        estados = calculos.estado_pago_por_dia(self.ana, HOY)
        self.assertEqual(estados[D5]["estado"], "PAGADO")
        self.assertEqual((estados[D6]["estado"], estados[D6]["pendiente"]), ("PARCIAL", Decimal("5400.00")))

        hoja = calculos.resumen_dia(self.ana, D16)
        self.assertEqual(hoja["saldo_anterior"], Decimal("25400.00"))
        self.assertEqual(hoja["saldo_a_la_fecha"], Decimal("5400.00"))
        self.assertIn("liquidación del 05/10 al 15/10", hoja["movimientos"][0]["descripcion"])
        self.assertEqual(calculos.resumen_dia(self.ana, D5)["liquidacion"]["id"], liq.pk)

    def test_periodos_contiguos(self):
        self.ana.modalidad_liquidacion = Usuario.Modalidad.DIARIA
        self.ana.save()
        primera = self.liquidar(monto_pagado=0)
        self.assertEqual((primera.desde, primera.hasta), (D5, D5))
        segunda = self.liquidar(monto_pagado=0)
        self.assertEqual((segunda.desde, segunda.hasta), (D6, D6))
        with self.assertRaises(ValidationError):  # solo la última se puede anular
            liquidaciones.anular(primera, self.encargado, "error")
        with self.assertRaises(ValidationError):  # no se liquida el futuro
            self.liquidar(hasta=HOY + timedelta(days=1), monto_pagado=0)
        self.liquidar(hasta=HOY, monto_pagado=0)
        with self.assertRaises(ValidationError):  # ya está todo liquidado
            liquidaciones.previsualizar(self.ana, hoy=HOY)

    def test_anular_y_volver_a_liquidar_no_paga_dos_veces(self):
        liq = self.liquidar(monto_pagado=20000, fecha_pago=D16)
        with self.assertRaises(ValidationError):
            liquidaciones.anular(liq, self.encargado, "  ")  # motivo obligatorio
        liquidaciones.anular(liq, self.encargado, "Faltó cargar una salida")
        liq.refresh_from_db()
        self.assertEqual((liq.estado, liq.motivo_anulacion), ("ANULADA", "Faltó cargar una salida"))
        self.assertEqual(Pago.objects.filter(liquidacion__isnull=True, anulado=False).count(), 2)

        p = liquidaciones.previsualizar(self.ana, hoy=HOY)
        self.assertEqual(p["desde"], D5)
        self.assertEqual(p["adelantos"], Decimal("25000.00"))  # el adelanto + lo ya pagado
        self.assertEqual(p["total_a_pagar"], Decimal("5400.00"))
        hoja = calculos.resumen_dia(self.ana, D16)
        self.assertIn("anulada", hoja["movimientos"][0]["descripcion"])

    def test_dias_liquidados_bloqueados_para_el_encargado(self):
        liq = self.liquidar(monto_pagado=20000, fecha_pago=D16)
        with self.assertRaises(ValidationError):
            reglas.validar_dia_no_liquidado(self.ana, D6)
        reglas.validar_dia_no_liquidado(self.ana, D16)  # fuera del período: libre
        with self.assertRaises(ValidationError):
            liquidaciones.registrar_adelanto(self.ana, fecha=D6, monto=1, registrado_por=self.encargado, hoy=HOY)
        with self.assertRaises(ValidationError):  # pago aplicado en liquidación vigente
            liquidaciones.anular_pago(liq.pagos.get(tipo=Pago.Tipo.ADELANTO), self.encargado, "error")
        with self.assertRaises(ValidationError):  # fecha futura
            liquidaciones.registrar_adelanto(self.ana, fecha=HOY + timedelta(days=1), monto=1,
                                             registrado_por=self.encargado, hoy=HOY)

    def test_sync_tardio_se_acepta_y_genera_diferencia(self):
        liq = self.liquidar(monto_pagado=25400, fecha_pago=D16)
        self.assertEqual(liquidaciones.diferencia(liq), Decimal("0.00"))
        # Llega del celular un retiro del 06/10 que estaba sin sincronizar: se acepta.
        servicios.registrar_retiro(self.ana, fecha=D6, producto=self.cafe, cantidad=1, hora=time(13, 0))
        self.assertEqual(liquidaciones.diferencia(liq), Decimal("-800.00"))
        siguiente = liquidaciones.previsualizar(self.ana, hoy=HOY)
        self.assertEqual(siguiente["saldo_anterior"], Decimal("-800.00"))  # pasa a la próxima

    def test_turno_abierto_impide_liquidar(self):
        fichar(self.ana, D15, "ENTRADA", 8, 0)
        with self.assertRaises(ValidationError):
            self.liquidar(monto_pagado=0)

    def test_monto_y_fecha_de_pago(self):
        with self.assertRaises(ValidationError):
            self.liquidar(monto_pagado=-1)
        with self.assertRaises(ValidationError):  # pago anterior al período
            self.liquidar(monto_pagado=100, fecha_pago=date(2026, 10, 1))

    def test_total_negativo_queda_como_deuda(self):
        retirar(self.ana, D6, self.sandwich, 30)  # $48000 en retiros
        liq = self.liquidar(monto_pagado=0)
        self.assertLess(liq.total_a_pagar, 0)
        self.assertEqual(liq.pagos.filter(tipo=Pago.Tipo.LIQUIDACION).count(), 0)
        self.assertEqual(liquidaciones.previsualizar(self.ana, hoy=HOY)["saldo_anterior"], liq.saldo_resultante)

    def test_hasta_sugerido_por_modalidad(self):
        M, f = Usuario.Modalidad, liquidaciones.hasta_sugerido
        hoy = date(2027, 1, 1)
        self.assertEqual(f(M.DIARIA, date(2026, 10, 7), hoy), date(2026, 10, 7))
        self.assertEqual(f(M.SEMANAL, date(2026, 10, 7), hoy), date(2026, 10, 13))
        self.assertEqual(f(M.QUINCENAL, date(2026, 10, 1), hoy), date(2026, 10, 15))
        self.assertEqual(f(M.QUINCENAL, date(2026, 10, 16), hoy), date(2026, 10, 31))
        self.assertEqual(f(M.MENSUAL, date(2026, 2, 1), hoy), date(2026, 2, 28))
        self.assertEqual(f(M.TRIMESTRAL, date(2026, 8, 1), hoy), date(2026, 9, 30))
        self.assertEqual(f(M.MENSUAL, date(2026, 10, 1), date(2026, 10, 20)), date(2026, 10, 20))  # tope: hoy

    def test_primera_liquidacion_desde_fecha_de_alta(self):
        nuevo = Usuario.objects.create_user("nuevo", password="x" * 8)
        p = liquidaciones.previsualizar(nuevo)
        self.assertEqual(p["desde"], nuevo.fecha_alta)


class HojaDelDiaTests(Base):
    def test_movimientos_ordenados_por_su_hora_y_no_por_el_timestamp(self):
        fichar(self.ana, DIA1, "ENTRADA", 8, 0)
        fichar(self.ana, DIA1, "SALIDA", 12, 0)
        anulado = fichar(self.ana, DIA1, "ENTRADA", 7, 50, anulado=True)
        # El retiro se cargó a la noche (timestamp tardío) pero ocurrió a las 10:15.
        servicios.registrar_retiro(self.ana, fecha=DIA1, producto=self.cafe, cantidad=1, hora=time(10, 15),
                                   registrado_en=datetime.combine(DIA1, time(23, 0), tzinfo=TZ))
        liquidaciones.registrar_adelanto(self.ana, fecha=DIA1, hora=time(20, 30), monto=1000,
                                         registrado_por=self.encargado)
        movs = calculos.resumen_dia(self.ana, DIA1)["movimientos"]
        self.assertEqual([(m["hora"], m["tipo"]) for m in movs],
                         [("07:50", "ENTRADA"), ("08:00", "ENTRADA"), ("10:15", "RETIRO"), ("12:00", "SALIDA"),
                          ("20:30", "PAGO")])
        self.assertTrue(movs[0]["anulado"])
        self.assertEqual(movs[2]["monto"], Decimal("-800.00"))
        self.assertEqual(movs[4]["descripcion"], "Monto recibido (adelanto)")

    def test_hora_del_retiro_por_defecto_es_la_del_registro(self):
        r = servicios.registrar_retiro(self.ana, fecha=DIA1, producto=self.cafe, cantidad=1,
                                       registrado_en=datetime.combine(DIA1, time(9, 41, 33), tzinfo=TZ))
        self.assertEqual(r.hora, time(9, 41))


class LiquidacionesApiTests(Base):
    def setUp(self):
        super().setUp()
        for dia in (D5, D6):
            fichar(self.ana, dia, "ENTRADA", 8, 0)
            fichar(self.ana, dia, "SALIDA", 16, 0)
        self.jefe, _ = ApiTests.cliente(self, "jefe")
        self.cli_ana, _ = ApiTests.cliente(self, "ana")

    def test_flujo_completo(self):
        r = self.jefe.post("/api/pagos/", {"empleado": self.ana.pk, "fecha": D6.isoformat(), "hora": "12:00",
                                            "monto": "5000"}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(r.json()["tipo"], "ADELANTO")

        r = self.jefe.get(f"/api/liquidaciones/previsualizar/?empleado={self.ana.pk}&hasta={D6.isoformat()}")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()["total_a_pagar"], 27000.0)

        self.assertEqual(self.cli_ana.post("/api/liquidaciones/", {}, format="json").status_code, 403)
        r = self.jefe.post("/api/liquidaciones/", {"empleado": self.ana.pk, "hasta": D6.isoformat(),
                                                    "monto_pagado": "27000"}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        liq = r.json()
        self.assertEqual((liq["desde"], liq["saldo_resultante"], len(liq["pagos"])), ("2026-10-05", 0.0, 2))

        detalle = self.jefe.get(f"/api/liquidaciones/{liq['id']}/").json()
        self.assertEqual([d["estado_pago"] for d in detalle["dias"]], ["PAGADO", "PAGADO"])
        self.assertEqual(len(self.cli_ana.get("/api/liquidaciones/").json()), 1)  # el empleado ve la suya

        r = self.jefe.post(f"/api/liquidaciones/{liq['id']}/anular/", {"motivo": ""}, format="json")
        self.assertEqual(r.status_code, 400)
        r = self.jefe.post(f"/api/liquidaciones/{liq['id']}/anular/", {"motivo": "Error de horas"}, format="json")
        self.assertEqual((r.status_code, r.json()["estado"]), (200, "ANULADA"))
        self.assertEqual(len(self.jefe.get(f"/api/pagos/?empleado={self.ana.pk}&pendientes=1").json()), 2)

    def test_errores_de_negocio_vuelven_como_detalle(self):
        r = self.jefe.post("/api/liquidaciones/", {"empleado": self.ana.pk, "hasta": "2026-10-01",
                                                    "monto_pagado": "0"}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("no puede ser anterior", str(r.json()["detalle"]))

    def test_anular_adelanto(self):
        r = self.jefe.post("/api/pagos/", {"empleado": self.ana.pk, "fecha": D6.isoformat(), "monto": "100"},
                           format="json")
        url = f"/api/pagos/{r.json()['id']}/anular/"
        self.assertEqual(self.cli_ana.post(url, {"motivo": "x"}, format="json").status_code, 403)
        r = self.jefe.post(url, {"motivo": "Cargado dos veces"}, format="json")
        self.assertTrue(r.json()["anulado"])
