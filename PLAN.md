# AgendApp — Plan de desarrollo por fases

Documento vivo para seguir el avance del proyecto. Se actualiza **al cerrar cada fase** (o cuando cambia una decisión): marcar el estado, tildar las tareas, anotar lo nuevo que hay que conservar y sumar una línea al registro de cambios del final.

**Dónde vive:** el original es `AgendApp\PLAN.md` (raíz del proyecto, compartida por BackEnd y FrontEnd). Al cerrar cada fase se copia, actualizado, a la raíz del repositorio o los repositorios que esa fase modificó, y va en el commit de cierre.

**Estados:** ✅ terminada · 🔄 en curso · ⏳ pendiente · ⛔ bloqueada

| Fase | Nombre | Estado |
|---|---|---|
| 0 | Definiciones | ✅ |
| 1 | Backend base | ✅ |
| 2 | App Android base | ⏳ |
| 3 | Libreta del empleado | ⏳ |
| 4 | Sincronización | ⏳ |
| 5 | Backoffice móvil del encargado | ⏳ |
| 6 | Reportes | ⏳ |
| 7 | Cierre y puesta en producción | ⏳ |

---

## 1. Datos del proyecto

| | |
|---|---|
| Carpeta | `C:\Personal\Trabajo - Mami\AgendApp` |
| BackEnd | `AgendApp\AgendApp - BackEnd` — Django 5.2 + Django REST Framework + JWT (simplejwt) — repo: https://github.com/cristiandevar/AgendApp---BackEnd.git |
| FrontEnd | `AgendApp\AgendApp - FrontEnd` — Kotlin + Jetpack Compose + Material 3 + Room — repo: https://github.com/cristiandevar/AgendApp---FrontEnd.git |
| Paquete Android | `com.agendapp` |
| Base de datos | SQLite en desarrollo · PostgreSQL en producción (nube) |
| Usuarios | Encargado (backoffice) y Empleado (libreta), cada uno con su propio celular |
| Conectividad | Offline-first: el empleado trabaja sin internet y sincroniza cuando hay red; el encargado trabaja con conexión |

---

## 2. Forma de trabajo (se conserva)

1. **Paso a paso:** no se arranca una fase nueva hasta que la actual esté probada y **sin bugs pendientes**.
2. Al terminar una fase, el usuario la prueba y, sin bugs pendientes, se versiona (ver "Versionado") y recién ahí se continúa.
3. Cada cambio se prueba primero en un entorno aparte (tests + pruebas de punta a punta) y después se copia a la carpeta del proyecto.
4. Toda regla de negocio nueva o modificada lleva **tests** y se documenta en el `README.md`.
5. Los cambios de base de datos van siempre en **migraciones nuevas**: no se reescriben las que ya están aplicadas.
6. Las decisiones que dependen del negocio se consultan antes de implementarlas; las técnicas se proponen con su justificación.

### Versionado (al cerrar cada fase)
- Un **commit por fase terminada** en cada repositorio que la fase modificó, en una rama con el formato del proyecto: `AAAAMMDD_descripcion` (por ejemplo `20261115_fase_2_app_base`), seguido de **push** y Pull Request a `main`.
- El mensaje del commit resume lo realizado en la fase y referencia este plan.
- Junto con el commit se actualiza este `PLAN.md` y se copia al repositorio.
- Los archivos del proyecto tienen saltos de línea de Windows (CRLF) y el repositorio guarda LF. Al operar git desde fuera de Windows se usa `core.autocrlf=input` para no generar cambios falsos.
- El push lo hace Claude cuando GitHub está vinculado a su cuenta (claude.ai → Configuración → Conectores); si no, deja el commit hecho y el usuario ejecuta `git push` desde su PC.

---

## 3. Qué se debe conservar (decisiones y reglas vigentes)

Estas reglas ya están implementadas y testeadas en el backend. La app Android las tiene que **replicar igual** (offline) y ninguna fase futura las debe romper sin una decisión explícita.

### Arquitectura
- **El servidor es la fuente de la verdad.** El celular calcula para funcionar sin conexión, pero al sincronizar manda lo que dice el servidor.
- Fichajes, retiros y el resto de las entidades usan **UUID** como clave: el celular genera el id y reenviar lo mismo no duplica.
- Las operaciones del empleado (fichar, anular, retirar, modificar) pasan por **`agenda/servicios.py`**, que valida, audita y notifica. La sincronización debe usar esos mismos servicios.
- Las liquidaciones pasan por **`agenda/liquidaciones.py`**; los cálculos de horas, saldo y estado de pago, por **`agenda/calculos.py`**; las validaciones, por **`agenda/reglas.py`**.
- El nombre interno de la app Django es **`agenda`** (tablas `agenda_*` y migraciones). No se renombra; el nombre visible es **AgendApp**.
- Variables de entorno de producción: `AGENDAPP_SECRET_KEY`, `AGENDAPP_DEBUG`, `AGENDAPP_ALLOWED_HOSTS`.
- Errores de reglas de negocio en la API: `{"detalle": [...]}` (400) o `{"detalle": "..."}` (409 al eliminar).

### Horas y pago
- Se paga la **hora real trabajada**; el horario asignado es solo una referencia.
- Puede haber varios tramos por día (entrar y salir más de una vez). **No hay turnos que crucen la medianoche.**
- **Tolerancia** de 15 min (parámetro). Una marca fuera de tolerancia, o en un día sin horario asignado, exige **motivo obligatorio**.
- **Tarifa por hora individual**, con historial que no se reescribe: una tarifa que ya rige no se modifica ni se elimina; una nueva rige de hoy en adelante y después del último fichaje del empleado.
- **Feriados:** se paga la hora × el multiplicador **propio del feriado** (×2 por defecto). Solo se gestionan feriados de hoy en adelante.

### Movimientos
- Cada movimiento (fichaje, retiro, pago) tiene su propia **fecha + hora**, que es la que ordena la hoja. No es el timestamp técnico (`registrado_en`, `recibido_en`, `creado_en`).
- **Nada se borra:** fichajes, retiros y pagos se anulan.
- **Plazo del empleado: 10 min** (parámetro). Dentro del plazo puede **anular** un fichaje (no modificarlo) y **modificar o anular** un retiro, **sin justificación**. Pasado el plazo, solo corrige el encargado, **con motivo**.
- **Auditoría** de toda alta del encargado y de toda modificación o anulación, con valores de antes y de después.
- **Retiros:** máximo diario por producto y por empleado; el precio de costo queda **congelado** al momento del retiro.
- **Notificaciones al encargado** por cada entrada, salida y retiro, y por cada anulación o modificación del empleado; las marcas fuera de horario llegan **destacadas**.

### Saldo y liquidaciones
- `Saldo a la fecha = Saldo anterior + Ganado - Retiros - Monto recibido`, arrastrado día a día.
- Modalidad por empleado: diaria, semanal, quincenal, mensual o trimestral (sugiere el período).
- **Períodos contiguos:** cada liquidación empieza el día siguiente a la anterior; la primera, en la fecha de alta del empleado (o en su primer movimiento si hay uno anterior). El "hasta" no puede ser futuro.
- `Total a pagar = Saldo anterior + Ganado - Retiros - Adelantos`; el pago puede ser parcial y el resto pasa a la próxima.
- **Adelantos:** pagos sin liquidar; la próxima liquidación los descuenta.
- **Estado de pago por día** (pagado, parcial, pendiente, sin monto): se **calcula**, aplicando lo pagado a los días más viejos primero.
- **Días liquidados bloqueados** para el encargado: para corregir, primero anula la última liquidación vigente (motivo obligatorio). Los pagos de una liquidación anulada se conservan y se descuentan al reliquidar.
- **Sincronización tardía:** lo que llega del celular para un día liquidado se acepta y aparece como **diferencia**, que pasa a la próxima liquidación.
- No se liquida con un turno abierto dentro del período.

### Interfaz
- **Empleado:** libreta **vertical, de una sola hoja, rayada**. Deslizar a la izquierda → días siguientes; a la derecha → días anteriores. Calendario para saltar a una fecha.
- **Encargado:** backoffice móvil con un estilo similar al de la app de gestión de productos (menú lateral, listas y formularios).

---

## 4. Fases

### Fase 0 — Definiciones ✅
Decisiones de negocio y de arquitectura acordadas: están volcadas en la sección 3.

---

### Fase 1 — Backend base ✅
**Cerrada el 14/10/2026 y versionada.**

**Se realizó:**
- [x] Proyecto Django `config` + app `agenda`, con usuario propio (`Usuario`) con rol, modalidad de liquidación y fecha de alta.
- [x] Modelos: Parámetro, Feriado, Producto, TarifaHora, HorarioAsignado, Fichaje, Retiro, Pago, Liquidación, AuditoriaFichaje, AuditoriaRetiro, Notificación.
- [x] Migraciones `0001` a `0004`.
- [x] Reglas (`reglas.py`), cálculos (`calculos.py`), operaciones del empleado (`servicios.py`) y liquidaciones (`liquidaciones.py`).
- [x] API REST con JWT (ver la tabla de endpoints del `README.md`): login, usuarios, parámetros, feriados, productos, tarifas, horarios, hoja del día, notificaciones, liquidaciones (previsualizar, liquidar, anular) y pagos (adelantos, anular).
- [x] Django Admin "AgendApp - BackEnd" con las mismas reglas (auditoría, solo lectura de lo histórico, bloqueo de días liquidados).
- [x] Comando `seed_agenda` (con `--demo`) y usuarios de prueba.
- [x] 55 tests automáticos.
- [x] `.gitignore` del backend y renombre del proyecto a AgendApp.

**Verificación:**
```powershell
cd "C:\Personal\Trabajo - Mami\AgendApp\AgendApp - BackEnd"
.\.venv\Scripts\Activate.ps1
python manage.py migrate
python manage.py test agenda
python manage.py runserver 0.0.0.0:8000
```

**Quedó fuera de la Fase 1 a propósito** (se hace en la fase indicada):
- Endpoints para que el celular suba fichajes y retiros → Fase 4.
- Endpoints para que el encargado corrija fichajes y retiros con motivo y consulte la auditoría (hoy solo desde el Django Admin) → Fase 5.

---

### Fase 2 — App Android base ⏳
**Objetivo:** proyecto Android funcionando en el celular, con login por rol y los datos necesarios guardados localmente.

**Decisiones tomadas:** paquete `com.agendapp`; repo https://github.com/cristiandevar/AgendApp---FrontEnd.git; Kotlin + Jetpack Compose + Material 3.

**A realizar:**
- [ ] Crear el proyecto de Android Studio en `AgendApp - FrontEnd` (`applicationId` y `namespace` = `com.agendapp`, nombre visible "AgendApp").
- [ ] `.gitignore` de Android y primer commit en el repo del FrontEnd.
- [ ] Dependencias: Compose + Material 3, Navigation Compose, Room, Retrofit + OkHttp + serialización JSON, DataStore (sesión), WorkManager (para la Fase 4).
- [ ] URL del servidor por variante: `debug` = IP local de la PC (`runserver 0.0.0.0:8000`), `release` = dominio de producción.
- [ ] Login contra `/api/auth/login/`, guardado de tokens y renovación con `/api/auth/refresh/`.
- [ ] Navegación según rol: Empleado → libreta (pantalla provisoria en esta fase) · Encargado → backoffice (pantalla provisoria).
- [ ] Base local Room con las tablas de catálogo y configuración: productos, parámetros, feriados, tarifas y horarios del empleado.
- [ ] Descarga inicial de esos datos al iniciar sesión, con los endpoints existentes.
- [ ] Manejo de errores de la API (formato `detalle`) y de falta de conexión.

**Criterio de cierre:** la app compila, corre en el celular por USB, loguea con `ana` y con `encargado`, abre la pantalla de cada rol y muestra los productos descargados aun sin conexión.

**Backend:** no requiere cambios (si hiciera falta algún ajuste, se agrega acá).

---

### Fase 3 — Libreta del empleado ⏳
**Objetivo:** el empleado registra su jornada y sus retiros sin conexión y ve cada hoja con su cuenta.

**A realizar:**
- [ ] Hoja vertical rayada por día con `HorizontalPager` (izquierda → días siguientes, derecha → anteriores).
- [ ] Botón de calendario (`DatePicker` de Material 3) para saltar a una fecha.
- [ ] Fichar entrada y salida con la hora del celular; respetar la secuencia entrada/salida y varios tramos por día.
- [ ] Control de tolerancia local con los horarios y parámetros descargados: si la marca está fuera, pedir **motivo obligatorio**.
- [ ] Registrar retiros: elegir producto, cantidad y subtotal, con control del máximo diario.
- [ ] Anular un fichaje, o modificar o anular un retiro, dentro de los 10 minutos y sin pedir justificación; después de ese plazo, no permitirlo.
- [ ] Hoja: saldo anterior, movimientos ordenados por hora (anulados tachados), ganado, retiros, monto recibido y saldo a la fecha; día feriado indicado.
- [ ] Guardar todo en Room con UUID generado en el celular y marca de "pendiente de sincronizar".
- [ ] Replicar en Kotlin `calculos.py` y las reglas necesarias de `reglas.py`, con **tests que usen los mismos casos del backend** (por ejemplo, 08:00–12:00 y 13:00–17:30 = 8:30 h × $2000 = $17000).

**Criterio de cierre:** con el celular en modo avión se puede fichar, retirar, anular y navegar entre días, y las cuentas coinciden con las del backend para los mismos datos.

**Backend:** no requiere cambios.

---

### Fase 4 — Sincronización ⏳
**Objetivo:** que lo registrado en el celular llegue al servidor y que el celular reciba lo que cambió en el servidor.

**A realizar — Backend:**
- [ ] `POST /api/sync/subir/`: lote de fichajes, retiros, anulaciones y modificaciones con su UUID y el momento real de cada acción en el celular. Procesa con `servicios.py`, es idempotente (reenviar lo mismo no duplica) y responde qué se aceptó y qué se rechazó con el motivo.
- [ ] `GET /api/sync/bajar/?desde=<marca>`: lo que cambió desde la última sincronización (productos, parámetros, feriados, tarifas, horarios, fichajes y retiros propios —incluidas las correcciones del encargado—, pagos y liquidaciones).
- [ ] Registrar la diferencia entre la hora del celular y la de llegada, para detectar relojes desajustados.
- [ ] Tests de idempotencia, rechazos y sync tardío sobre días liquidados.

**A realizar — Android:**
- [ ] WorkManager: sincronizar en segundo plano cuando haya red, y también a demanda.
- [ ] Aplicar lo que baja del servidor y adoptar su versión ante cualquier diferencia.
- [ ] Mostrar en la hoja lo rechazado por el servidor y el estado de sincronización.

**Criterio de cierre:** se registra sin conexión, se recupera la red y los datos aparecen en el servidor (y las notificaciones le llegan al encargado); una corrección del encargado aparece en el celular del empleado.

---

### Fase 5 — Backoffice móvil del encargado ⏳
**Objetivo:** que el encargado gestione todo desde el celular.

**A realizar — Backend:**
- [ ] Endpoints para que el encargado cree, corrija y anule fichajes y retiros **con motivo**, respetando la auditoría y el bloqueo de días liquidados.
- [ ] Endpoint de consulta de la auditoría por fichaje o retiro.

**A realizar — Android** (menú lateral, estilo similar a la app de gestión de productos):
- [ ] Empleados: alta, edición, modalidad de liquidación y desactivación.
- [ ] Productos: precio de costo, máximo diario y baja.
- [ ] Tarifas por hora: historial; nueva tarifa; editar o eliminar solo las que todavía no rigen.
- [ ] Horarios asignados por día y por semana.
- [ ] Feriados y parámetros.
- [ ] Agenda de cada empleado: ver su libreta y corregir con motivo.
- [ ] Notificaciones: lista, destacadas y marcar como leídas.
- [ ] Liquidaciones: previsualizar, liquidar (monto, fecha y hora del pago), ver el comprobante y anular con motivo.
- [ ] Adelantos: registrar y anular.

**Decisión pendiente:** notificaciones push con Firebase Cloud Messaging (requiere crear un proyecto de Firebase) o solo avisos dentro de la app.

**Criterio de cierre:** el encargado puede operar toda la semana del local sin usar el Django Admin.

---

### Fase 6 — Reportes ⏳
**Objetivo:** reportes para el encargado, con vista previa en pantalla y exportación.

**A realizar:**
- [ ] Resumen a cobrar por empleado y período: dinero a cobrar = dinero ganado − costo de productos retirados (con pagos y saldo).
- [ ] Costo por empleado en un período.
- [ ] Cumplimiento de horario: horas asignadas contra trabajadas, llegadas tarde, marcas fuera de tolerancia con su motivo.
- [ ] Retiros por producto.
- [ ] Vista previa en la app y exportación a PDF (reportlab) o Excel (openpyxl).

**Criterio de cierre:** los reportes coinciden con las hojas y las liquidaciones para los mismos datos.

---

### Fase 7 — Cierre y puesta en producción ⏳
**A realizar:**
- [ ] Servidor en la nube: PostgreSQL, Gunicorn + Nginx, HTTPS, dominio y variables `AGENDAPP_*`.
- [ ] URL de producción en la variante `release` de la app.
- [ ] APK/AAB de release firmado.
- [ ] Backups automáticos de la base.
- [ ] Revisión final de seguridad y permisos.

**Decisión pendiente:** proveedor de nube.

---

## 5. Decisiones pendientes

| Decisión | Se necesita en |
|---|---|
| Push con Firebase o solo avisos dentro de la app | Fase 5 |
| Proveedor de nube | Fase 7 |

## 6. Limitaciones conocidas del entorno

- Desde la terminal que Claude usa en la PC no se permite `git push` (solo clone y fetch). El push se hace desde la nube con GitHub vinculado o desde la PC del usuario.
- El puente de archivos con la PC no puede **leer** archivos a más de 7 carpetas de profundidad (sí escribirlos). Los `.kt` de Android quedan más abajo: para leer cambios hechos a mano, copiar la carpeta de código a un nivel superior fuera de `src`.
- En Windows el entorno virtual (`.venv`) guarda rutas absolutas: si se mueve o renombra la carpeta del backend, hay que recrearlo.

## 7. Registro de cambios

| Fecha | Fase | Cambio |
|---|---|---|
| 13/10/2026 | 0 | Definiciones de negocio y arquitectura acordadas |
| 13/10/2026 | 1 | Backend base: modelos, reglas, API, admin y tests |
| 13/10/2026 | 1 | Plazo de 10 min para retiros, auditoría de retiros y notificaciones al encargado |
| 13/10/2026 | 1 | Historial de tarifas y feriados protegido; multiplicador propio por feriado |
| 14/10/2026 | 1 | Hora propia en retiros y pagos; liquidaciones por período contiguo con adelantos y bloqueo de días |
| 14/10/2026 | 1 | `.gitignore`, renombre a AgendApp y cierre de la Fase 1 |
| 14/11/2026 | 2 | Decisiones: paquete `com.agendapp` y repo del FrontEnd |
| 15/11/2026 | — | Plan guardado en el proyecto; versionado por fase (rama + commit + push) |
