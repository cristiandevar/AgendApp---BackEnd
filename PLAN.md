# AgendApp — Plan de desarrollo por fases

Documento vivo para seguir el avance del proyecto. Se actualiza **al cerrar cada fase** (o cuando cambia una decisión): marcar el estado, tildar las tareas, anotar lo nuevo que hay que conservar y sumar una línea al registro de cambios del final.

**Dónde vive:** el original es `AgendApp\PLAN.md` (raíz del proyecto, compartida por BackEnd y FrontEnd). Al cerrar cada fase se copia, actualizado, a la raíz del repositorio o los repositorios que esa fase modificó, y va en el commit de cierre.

**Estados:** ✅ terminada · 🔄 en curso · 📝 definida, por empezar · ⏳ pendiente · ⛔ bloqueada

| Fase | Nombre | Estado |
|---|---|---|
| 0 | Definiciones | ✅ |
| 1 | Backend base | ✅ |
| 2 | App Android base | ✅ |
| 3 | Libreta del empleado | ✅ |
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
4. Toda regla de negocio nueva o modificada lleva **tests** y se documenta en `docs/` (reglas de negocio, guías de uso).
5. Los cambios de base de datos van siempre en **migraciones nuevas**: no se reescriben las que ya están aplicadas.
6. Las decisiones que dependen del negocio se consultan antes de implementarlas; las técnicas se proponen con su justificación.

### Versionado (al cerrar cada fase)
- Un **commit por fase terminada** en cada repositorio que la fase modificó, en una rama con el formato del proyecto: `AAAAMMDD_descripcion` (por ejemplo `20261115_fase_2_app_base`), seguido de **push** y Pull Request a `main`.
- El mensaje del commit resume lo realizado en la fase y referencia este plan.
- Junto con el commit se actualiza este `PLAN.md` y se copia al repositorio.
- Los archivos del proyecto tienen saltos de línea de Windows (CRLF) y el repositorio guarda LF. Al operar git desde fuera de Windows se usa `core.autocrlf=input` para no generar cambios falsos.
- **Desde el 16/11/2026 todo el versionado se ejecuta en la PC del usuario**, sobre sus repositorios en `C:\Personal\Trabajo - Mami\AgendApp`: Claude corre ahí los comandos de git (vía la conexión con la PC) y nunca versiona en su entorno de pruebas. Si desde la PC no se puede hacer el push o el PR, el usuario los hace a mano.
- Claude copia los cambios a la carpeta del proyecto, verifica que lleguen completos y recién versiona cuando el usuario confirma que las pruebas dieron lo esperado.

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
- Los eventos se agregan con el **botón (+)** (solo en la hoja de hoy) → menú de tipos de evento → **popup** con Aceptar/Cancelar. Cada evento es un **renglón de 4 secciones**: hora, tipo, detalle y monto. Tocar un renglón abre su detalle y, dentro del plazo, las acciones permitidas.
- No se maneja stock de productos: el único límite es el **máximo diario por empleado**.
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

### Fase 2 — App Android base ✅
**Cerrada el 15/11/2026:** compila, corre en el celular y el login funciona con ambos roles.

**Objetivo:** proyecto Android funcionando en el celular, con login por rol y los datos necesarios guardados localmente.

**Decisiones tomadas:** paquete `com.agendapp`; repo https://github.com/cristiandevar/AgendApp---FrontEnd.git; Kotlin + Jetpack Compose + Material 3. Versiones: Gradle 8.11.1, AGP 8.7.3, Kotlin 2.1.0, KSP 2.1.0-1.0.29, Compose BOM 2024.12.01, Room 2.6.1, Retrofit 2.11.0, kotlinx.serialization 1.7.3, DataStore 1.1.1; minSdk 26, targetSdk 35. Gradle JDK: 21 (el que trae Android Studio).

**Se realizó:**
- [x] Proyecto en `AgendApp - FrontEnd` (`applicationId` y `namespace` = `com.agendapp`, nombre visible "AgendApp", ícono de libreta).
- [x] `.gitignore` de Android y `README.md` con los pasos para abrirlo y correrlo.
- [x] Dependencias: Compose + Material 3, Room, Retrofit + OkHttp + kotlinx.serialization, DataStore. (Navigation Compose y WorkManager se suman cuando se usen: WorkManager en la Fase 4.)
- [x] URL del servidor por variante: `debug` = `agendapp.api.debug` de `local.properties` (o de `gradle.properties`); `release` = dominio de producción (Fase 7). HTTP sin cifrar permitido solo en debug.
- [x] Login contra `/api/auth/login/`, sesión guardada con DataStore y renovación automática del token con `/api/auth/refresh/`; si el servidor rechaza la sesión, vuelve al login.
- [x] Al abrir la app sin conexión, entra igual con la sesión guardada.
- [x] Pantalla según rol: Empleado e Encargado tienen su inicio provisorio (datos descargados, tarifa vigente y próximos horarios del empleado, parámetros para el encargado).
- [x] Base local Room: productos, parámetros, feriados, tarifas y horarios.
- [x] Descarga automática al iniciar sesión y botón "Actualizar datos"; al cerrar sesión se borran los datos locales.
- [x] Errores de la API traducidos a mensajes claros (formato `detalle`, errores de SimpleJWT y de campos) y aviso de "sin conexión".
- [x] Tests unitarios con respuestas reales del backend (errores, DTOs, formato de pesos).

- [x] Compilado en Android Studio y probado en el celular por USB: login correcto con `ana` (empleado) y `encargado`.
- [x] Esquema de Room versionado (`app/schemas/.../1.json`), base para las migraciones de la Fase 3.
- [x] IP de desarrollo actual de la PC: `192.168.0.154` (en `gradle.properties`).
- [x] Versionado: commit inicial en `main` y rama `20261115_fase_2_app_base` con PR en el repo del FrontEnd.

**Criterio de cierre:** la app compila, corre en el celular por USB, loguea con `ana` y con `encargado`, abre la pantalla de cada rol y muestra los productos descargados aun sin conexión.

**Backend:** no requiere cambios.

---

### Fase 3 — Libreta del empleado ✅
**Estado:** comportamiento definido y confirmado (16/11/2026). Entrega 3a probada y commiteada en la rama `20261116_fase_3_libreta` de ambos repos (**sin push** hasta cerrar 3b y 3c). Entrega 3b probada y commiteada (`9429e94`, 22/11/2026, sin push). Entrega 3c probada y commiteada (`3736c7c`, 22/11/2026). **Fase cerrada el 22/11/2026**, con la documentación de ambos repos (`docs/`). Push y PR: los hace el usuario desde su PC.

**Objetivo:** el empleado registra su jornada y sus retiros sin conexión y ve cada hoja con su cuenta.

#### 3.1 La libreta
- Una hoja vertical rayada por día, con margen rojo, dentro de un `HorizontalPager`: deslizar a la izquierda → días siguientes; a la derecha → días anteriores.
- **Encabezado de la hoja:** fecha ("lunes 16 de noviembre"), marca de feriado (con su multiplicador), horario esperado del día ("08:00–12:00 · 16:00–20:00") y estado del turno en la hoja de hoy ("Trabajando desde 08:05" / "Fuera de turno").
- Barra superior con botón de **calendario** (`DatePicker` de Material 3) para saltar a una fecha.
- **Botón (+)** solo en la hoja de hoy. En los demás días se reemplaza por un botón **"Hoy"** para volver. Los días pasados y futuros son de solo lectura para el empleado.

#### 3.2 Alta de eventos: botón (+)
Al tocar (+) se despliega un menú con los tipos de evento: **Fichaje** y **Retiro de producto**. Cada opción abre su formulario en un **popup** con **Aceptar** y **Cancelar**. Al tocar Aceptar se aplican los controles y se registra en la base local.

**Fichaje**
- El tipo (**Entrada** / **Salida**) se decide por el **último fichaje vigente del día**: si es una entrada, toca salida; si no, entrada (permite varios tramos por día).
- Fecha y hora de **solo lectura**, con un reloj en vivo. **Se registra la hora del momento de tocar Aceptar**, no la de abrir el popup.
- Muestra el horario esperado ("Esperado: 08:00"), o "Sin horario asignado".
- Si la hora queda fuera de la tolerancia (o el día no tiene horario asignado), aparece el campo **motivo, obligatorio**. La tolerancia **se vuelve a evaluar al tocar Aceptar**: si con el popup abierto la hora pasa el límite, aparece el motivo y no deja confirmar sin completarlo.
- La hora se registra **al minuto** (sin segundos) y tiene que ser **posterior al último fichaje vigente del día**, igual que en el servidor (que rechaza dos fichajes a la misma hora): si se intenta fichar en el mismo minuto, avisa "Ya fichaste a las 08:05…"; si la hora del celular quedó antes del último fichaje, pide revisar la fecha y hora del teléfono.

**Retiro de producto**
- **Búsqueda incremental** por nombre: al escribir se muestra una lista filtrada con **nombre y precio** de cada producto activo.
- Ícono de **escáner** al lado de la búsqueda: abre la cámara (lector de Google, Play Services; no pide permiso de cámara) y lee **código de barras o QR**; si el código coincide con un producto activo, lo selecciona; si no, avisa "Producto no encontrado".
- **Cantidad** con botones − y +: mínimo 1 y máximo lo que le queda del día ("Te quedan 2 de hoy"); el + se deshabilita al llegar al tope. Sin límite si el producto no tiene máximo diario.
- **Subtotal en vivo** (cantidad × precio de costo).
- Control al tocar Aceptar: producto activo y **máximo diario por empleado** (no se maneja stock).

#### 3.3 La línea escrita
Cada evento ocupa un renglón dividido en **4 secciones**:

| Hora | Tipo | Detalle | Monto |
|---|---|---|---|
| 08:05 | Entrada | motivo, si estuvo fuera de tolerancia | — |
| 10:15 | Retiro | "2 × Café" | −$1.800,00 (rojo) |
| 12:00 | Salida | motivo, si estuvo fuera de tolerancia | +$9.791,67 (tinta azul): lo ganado en el tramo (horas × tarifa × multiplicador si es feriado) |
| 20:05 | Recibido | "Liquidación del 01/11 al 15/11" o "Adelanto" | −$30.000,00 (verde oscuro) |

- Orden por la **hora del movimiento**. El detalle se corta con "…" si no entra.
- **Saldo anterior** (primer renglón) y **Saldo a la fecha** (último renglón): no son eventos guardados sino renglones **calculados** cada vez que se dibuja la hoja; por eso siempre quedan primero y último aunque se agreguen fichajes o tramos nuevos, sin horas ficticias ni reubicaciones. El saldo a la fecha incluye los tramos cerrados (un turno abierto suma recién al fichar la salida).
- **Marcas**, en el margen rojo de la izquierda:
  - Anulado: renglón **tachado** y en gris.
  - Cargado o corregido por el encargado: ícono de **lápiz** (✎).
  - Fuera de tolerancia: el motivo en el detalle.
  - Pendiente de sincronizar: puntito gris (se usa desde la Fase 4).

#### 3.4 Tocar un renglón: popup de detalle
- Tocar cualquier renglón abre un **popup de detalle** con toda la información: hora, tipo y detalle completo (fichaje: motivo y horario esperado; retiro: producto, cantidad, precio unitario y subtotal; recibido: período o adelanto), si fue anulado o corregido por el encargado.
- Si el evento es del empleado y está **dentro del plazo de 10 minutos**, el popup suma las acciones y el tiempo restante ("Podés anularlo hasta las 10:25"):
  - Fichaje: **Anular** (no se edita). Solo se puede anular el **último fichaje vigente del día**: anular uno anterior dejaría la secuencia rota (por ejemplo, una salida sin entrada).
  - Retiro: **Modificar** (abre el popup del retiro con los datos cargados) y **Anular**.
- Pasado el plazo, solo se ve el detalle.
- Tocar **Saldo a la fecha** abre el resumen del día: horas, ganado, retiros, recibido y saldo.

#### 3.5 Datos y cálculos en el celular
- Tablas nuevas en Room para fichajes, retiros y pagos, con UUID generado en el celular y marca de **pendiente de sincronizar**. Room pasa a la versión 2: como la versión 1 solo tenía el catálogo (se vuelve a descargar), se recrea la base. **Desde la versión 2 toda migración debe ser real, nunca destructiva**, porque puede haber movimientos sin sincronizar.
- Replicar en Kotlin `calculos.py` y las reglas necesarias de `reglas.py` (secuencia, tolerancia, plazo, máximo diario), con **tests que usen los mismos casos del backend** (por ejemplo, 08:00–12:00 y 13:00–17:30 = 8:30 h × $2000 = $17000).
- Limitación hasta la Fase 4: el celular todavía no descarga del servidor los movimientos ya registrados, así que el saldo anterior y los días pasados se calculan solo con lo registrado en ese celular.

#### 3.6 Backend
- [x] `Producto.codigo_barra` (texto, opcional, único; vacío = sin código) con migración `0005`, Django Admin (columna y búsqueda) y API. 58 tests.
- [x] `seed_agenda` asigna códigos de ejemplo `AGENDAPP-0001` a `AGENDAPP-0008` para probar el escáner.
- [x] El catálogo descargado por la app incluye el código.

#### 3.7 Entregas (cada una se prueba en el celular antes de seguir)
- [x] **3a — Base y libreta de solo lectura** (probada en el celular el 16/11/2026; commit local `750fbd5` BackEnd / `351382d` FrontEnd, sin push):
  - [x] Campo `codigo_barra` en el backend.
  - [x] Room v2 con fichajes, retiros y pagos; código de barras en productos.
  - [x] Dominio en Kotlin puro (`dominio/`): réplica de `calculos.py` y `reglas.py` (tramos, ganado con los mismos redondeos que Python, saldo, tolerancia, plazo, último fichaje anulable, máximo diario) y armado de la hoja. **15 tests corridos y en verde** con los casos del backend.
  - [x] Libreta: páginas por día, calendario, botón "Hoy", encabezado (fecha, feriado, horario, estado del turno), renglones de 4 secciones sobre papel rayado con margen, saldos calculados, popup de detalle (y resumen del día al tocar el saldo).
  - [x] Datos de ejemplo en debug (menú ⋮) para ver la hoja con contenido; no se sincronizan.
- [x] **3b — Fichajes** (probada en el celular el 22/11/2026; commit local `9429e94` en el FrontEnd, sin push):
  - [x] Botón (+) solo en la hoja de hoy, con menú: "Fichaje · entrada/salida" y "Retiro de producto" (deshabilitado hasta la 3c).
  - [x] Popup de fichaje: reloj en vivo, fecha, horario esperado, "Dentro del horario" o motivo obligatorio; al tocar Aceptar se vuelven a controlar secuencia, hora y tolerancia con los fichajes leídos de la base, y se guarda pendiente de sincronizar.
  - [x] Popup de detalle: Anular (con confirmación) solo para el último fichaje vigente propio dentro del plazo, con "Podés anularlo hasta las HH:MM"; si está en plazo pero no es el último, explica por qué. La acción desaparece sola al vencer el plazo.
  - [x] Dominio: `Reglas.controlarFichaje`, `errorDeSecuencia` (réplica de `validar_secuencia`) e `impedimentoParaAnular`. **24 tests en verde** (10 nuevos en `FichajeTest.kt`).
- [x] **3c — Retiros** (probada en el celular el 22/11/2026; commit local `3736c7c` en el FrontEnd):
  - [x] Popup de retiro desde el (+): búsqueda incremental por nombre (sin importar acentos ni mayúsculas, palabras en cualquier orden) o por código tipeado; lista con nombre, precio y máximo diario.
  - [x] Escáner de código de barras o QR (Google Play Services, `play-services-code-scanner` 16.1.0): selecciona el producto o avisa "Producto no encontrado". El módulo se pide descargar al abrir la libreta, para que después funcione sin conexión.
  - [x] Cantidad con − y + (mínimo 1, tope = lo que queda del día), "Te quedan N de hoy" / "Sin límite diario", subtotal en vivo.
  - [x] Modificar (mismo popup con los datos cargados) y Anular (con confirmación) desde el detalle, dentro del plazo, con la hora límite.
  - [x] Mismas reglas que el backend: al modificar sin cambiar de producto se conserva el precio congelado; si cambia el producto, toma su precio actual; se puede conservar un producto que ya no está activo, pero no elegir otro inactivo; el máximo diario excluye el propio retiro.
  - [x] Dominio: `Reglas.controlarRetiro`, `impedimentoParaCambiarRetiro`, `yaRetirado` y `Busqueda.filtrar`. **36 tests de dominio en verde** (12 en `RetiroTest.kt`).
  - [x] Ajustes de la prueba del 22/11/2026: el subtotal del popup de retiro y los montos del detalle de una línea (retiro, monto recibido) se ven en positivo (el negativo queda solo en la hoja). El plazo corre desde el momento exacto de registro, con segundos, como en el servidor: el detalle muestra "Registrado a las HH:MM:SS" y "hasta las HH:MM:SS (quedan m:ss)", y el popup de Modificar muestra la cuenta regresiva y no deja aceptar al vencer.
  - [x] Hoja de códigos de prueba (`AgendApp\codigos_prueba_escaner.png`) con QR y código de barras de los 8 productos del `seed_agenda`.

- [x] **Documentación** (22/11/2026), en `docs/` de cada repositorio:
  - BackEnd: `README.md` nuevo; para desarrolladores, arquitectura, modelo de datos, reglas de negocio (marcando las replicadas en la app), API REST con respuestas reales y cómo aportar; para usuarios, la **guía del encargado** con capturas reales del Django Admin (datos del `seed_agenda --demo`).
  - FrontEnd: para desarrolladores, arquitectura, dominio, la libreta (UI) y cómo aportar (incluye cómo migrar Room); para usuarios, la **guía del empleado** con maquetas de las pantallas generadas con los colores, medidas, tipografía y textos de los Composables.
  - De ahora en más, cada fase actualiza `docs/` (está en el checklist de los PR).

**Criterio de cierre:** con el celular en modo avión se puede fichar, retirar (buscando o escaneando), anular, modificar y navegar entre días, y las cuentas coinciden con las del backend para los mismos datos.

---

### Fase 4 — Sincronización ⏳
**Objetivo:** que lo registrado en el celular llegue al servidor y que el celular reciba lo que cambió en el servidor.

**A realizar — Backend:**
- [ ] `POST /api/sync/subir/`: lote de fichajes, retiros, anulaciones y modificaciones con su UUID y el momento real de cada acción en el celular. Procesa con `servicios.py`, es idempotente (reenviar lo mismo no duplica) y responde qué se aceptó y qué se rechazó con el motivo.
- [ ] `GET /api/sync/bajar/?desde=<marca>`: lo que cambió desde la última sincronización (productos, parámetros, feriados, tarifas, horarios, fichajes y retiros propios —incluidas las correcciones del encargado—, pagos y liquidaciones).
- [ ] Registrar la diferencia entre la hora del celular y la de llegada, para detectar relojes desajustados.
- [ ] Tests de idempotencia, rechazos y sync tardío sobre días liquidados.
- [ ] Llevar al backend la regla de la app: el empleado solo puede anular su **último fichaje vigente del día** (hoy `anular_fichaje_empleado` no lo controla).

**A realizar — Android:**
- [ ] WorkManager, con esta frecuencia (acordada el 22/11/2026):
  - **Al registrar** un fichaje o retiro: si hay red, se envía en el momento (para que el encargado reciba el aviso casi en tiempo real).
  - **Sin red:** queda pendiente y se envía solo al volver la conexión, aunque la app esté cerrada.
  - **Periódica cada 15 minutos** (el mínimo de Android) como respaldo: sube lo pendiente y baja lo que cambió en el servidor (correcciones del encargado, pagos, catálogo).
  - **A demanda:** el botón de actualizar sube y baja todo.
- [ ] Cola de operaciones pendientes (alta, modificación y anulación) para que una modificación o anulación de algo ya sincronizado llegue como tal al servidor. Requiere Room v3 con **migración real**.
- [ ] Al aceptarse en el servidor se apaga la marca de pendiente (puntito gris); si se rechaza, la hoja lo muestra con el motivo.
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
- [ ] Productos: precio de costo, máximo diario, código de barras y baja.
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

- Desde la terminal que Claude usa en la PC no se permite `git push` (solo clone y fetch). Como el versionado se hace solo en la PC del usuario, Claude deja los commits hechos y **el push lo corre el usuario** en su terminal.
- Ni en la nube ni en la terminal de la PC hay acceso a los repositorios de Google/Maven: **Claude no puede compilar Android**. Sí puede compilar y testear el **Kotlin puro** (`dominio/`, `util/`) con el compilador que trae Gradle. La compilación y la prueba las hace el usuario en Android Studio; Claude revisa el código sin compilarlo y valida los modelos contra respuestas reales del backend.
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
| 15/11/2026 | 2 | Proyecto Android base creado (login por rol, Room, descarga inicial) |
| 15/11/2026 | 2 | Fase 2 probada en el celular y cerrada; versionada en el repo del FrontEnd |
| 16/11/2026 | 3 | Definido el comportamiento de la libreta: botón (+), popups de fichaje y retiro, escáner de código, renglones de 4 secciones; entregas 3a/3b/3c |
| 16/11/2026 | 3 | Entrega 3a implementada (código de barras en el backend, Room v2, dominio en Kotlin con tests, libreta de solo lectura) |
| 16/11/2026 | 3 | Entrega 3a probada en el celular; commit local en la rama `20261116_fase_3_libreta` de ambos repos, sin push hasta cerrar la fase |
| 16/11/2026 | — | El versionado se ejecuta solo en la PC del usuario (sus repos), nunca en el entorno de pruebas de Claude |
| 16/11/2026 | 3 | Entrega 3b implementada (botón (+), popup de fichaje, anulación desde el detalle); regla nueva en el celular: la hora del fichaje debe ser posterior al último vigente |
| 22/11/2026 | 3 | Entrega 3b probada; commit `9429e94` en la PC del usuario, sin push. Definida la frecuencia de sincronización de la Fase 4. Se empieza la 3c |
| 22/11/2026 | 3 | Entrega 3c implementada (retiros con búsqueda, escáner, tope diario, modificar y anular); pendiente de prueba |
| 22/11/2026 | 3 | Prueba de la 3c: montos en positivo en popups; el plazo se mostraba al minuto pero corre con segundos → se muestra el momento de registro y una cuenta regresiva, y Modificar se bloquea al vencer. 36 tests en verde |
| 22/11/2026 | 3 | Fase 3 cerrada: commit de la 3c (`3736c7c`) en la PC; documentación en `docs/` de ambos repos (desarrollo y uso, con imágenes); push y PR a cargo del usuario |
