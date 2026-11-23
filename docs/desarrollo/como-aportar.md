# Cómo aportar

## Entorno

Requisitos: Python 3.10 o superior (Django 5.2) y git.

```bash
git clone https://github.com/cristiandevar/AgendApp---BackEnd.git
cd AgendApp---BackEnd
python -m venv .venv
.venv\Scripts\activate            # Windows  (Linux/macOS: source .venv/bin/activate)
pip install -r requirements.txt
python manage.py migrate
python manage.py seed_agenda --demo
python manage.py runserver 0.0.0.0:8000
```

`0.0.0.0` hace que el servidor escuche en la red Wi-Fi, para probar desde el celular. La app de debug
apunta a la IP de la PC (ver el README del FrontEnd).

### Datos de ejemplo (`seed_agenda`)

Es **idempotente** (se puede correr varias veces). Carga:

- Usuarios: `encargado`/`encargado123` (Marta Gómez), `ana`/`ana12345`, `luis`/`luis12345`, dados de alta el lunes de la semana pasada.
- Parámetros por defecto, feriados nacionales de fecha fija del año actual y el siguiente.
- 8 productos con códigos `AGENDAPP-0001` a `AGENDAPP-0008` (para probar el escáner).
- Tarifas (Ana $2.500, Luis $2.200) y horarios (Ana 08–12 y 16–20 de lunes a viernes; Luis 09–17 de lunes a sábado).
- Con `--demo`: fichajes y retiros de Ana en tres días anteriores y un adelanto.

Para empezar de cero: borrar `db.sqlite3` y volver a correr `migrate` y `seed_agenda`.

## Tests

```bash
python manage.py test agenda
```

Están en `agenda/tests.py`, agrupados por tema:

| Clase | Qué prueba |
|---|---|
| `CalculosTests` | Tramos, ganado, redondeo, feriados, tarifas, saldo |
| `ReglasTests` | Secuencia, tolerancia, motivo, plazo, máximo diario |
| `ApiTests` | Login, permisos por rol, endpoints del catálogo |
| `ServiciosTests` | Registrar/anular fichajes y retiros, auditoría |
| `NotificacionesApiTests` | Avisos al encargado |
| `HistorialProtegidoTests` | Tarifas y feriados que no se pueden tocar |
| `LiquidacionesTests` · `LiquidacionesApiTests` | Períodos, adelantos, pagos parciales, anulación, diferencias |
| `HojaDelDiaTests` | `resumen-dia` |
| `CodigoBarraTests` | Código de barras de productos |

Todas heredan de `Base`, que arma empleado, encargado, parámetros y horario. **Toda regla nueva lleva su
test**, y un bug corregido lleva el test que lo reproduce.

## Dónde poner cada cosa

- ¿Valida algo de un solo registro? → `clean()` del modelo.
- ¿Cruza registros pero no guarda nada? → `reglas.py`.
- ¿Es una cuenta? → `calculos.py`, sin efectos secundarios.
- ¿Guarda, audita o notifica? → `servicios.py` o `liquidaciones.py`, dentro de `@transaction.atomic`.
- La vista o el admin **solo** validan la forma y llaman a lo anterior.
- Los errores se lanzan como `ValidationError("mensaje para el usuario")`, en castellano rioplatense
  ("podés", "cargá") y diciendo qué hacer. La API los devuelve como `{"detalle": [...]}`.

## Migraciones

```bash
python manage.py makemigrations agenda
python manage.py migrate
```

- La migración va en el **mismo commit** que el cambio del modelo y con nombre descriptivo (`--name`).
- No se editan migraciones ya publicadas en `main`: se agrega una nueva.
- El label de la app sigue siendo `agenda` (renombrarlo rompería las migraciones).

## Reglas replicadas en la app

La libreta calcula sin conexión con una copia en Kotlin de `calculos.py` y `reglas.py`
(`app/src/main/java/com/agendapp/dominio/` del FrontEnd), con los mismos casos de test. Si cambiás una
regla marcada con 📱 en [Reglas de negocio](reglas-de-negocio.md):

1. Cambiala y testeala acá.
2. Replicala en `dominio/` del FrontEnd con el mismo caso de test.
3. Mencioná los dos cambios en los PR de cada repo.

## Forma de trabajo

- El trabajo se organiza en **fases** y **entregas** definidas en [`PLAN.md`](../../PLAN.md). No se avanza
  de fase con errores pendientes.
- **Ramas**: `AAAAMMDD_descripcion` a partir de `main`; por ejemplo `20261116_fase_3_libreta` o
  `20261115_plan_de_fases`.
- **Commits** en castellano, describiendo qué cambia para el usuario: `Fase 3a: código de barras en productos`.
  Un commit por entrega probada, con el detalle en el cuerpo.
- Se commitea recién cuando **las pruebas dan lo esperado**.
- **Un PR por fase**, hacia `main`, con el resumen de lo hecho y cómo probarlo. Al cerrar la fase se
  actualiza `PLAN.md` y se copia al repositorio.
- No se versionan `db.sqlite3`, entornos virtuales ni secretos (ver `.gitignore`).

## Checklist antes de un PR

- [ ] `python manage.py test agenda` pasa.
- [ ] Si cambió un modelo: hay migración y `seed_agenda` sigue funcionando.
- [ ] Si cambió una regla 📱: está replicada en la app con su test.
- [ ] Los mensajes de error se entienden sin conocer el código.
- [ ] La documentación de `docs/` refleja el cambio (API, reglas, guía del encargado).
