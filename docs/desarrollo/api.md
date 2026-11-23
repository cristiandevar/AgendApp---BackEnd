# API REST

Base: `/api/`. JSON en UTF-8. Montos como **números** (`COERCE_DECIMAL_TO_STRING = False`), fechas
`AAAA-MM-DD`, horas `HH:MM[:SS]`. Los ejemplos son respuestas reales del servidor con los datos de
`seed_agenda --demo`.

## Autenticación (JWT)

| Método | Ruta | Descripción |
|---|---|---|
| POST | `auth/login/` | `{username, password}` → tokens y datos del usuario |
| POST | `auth/refresh/` | `{refresh}` → nuevo `access` (y nuevo `refresh`: hay rotación) |
| GET | `auth/yo/` | Datos del usuario logueado |

```json
POST /api/auth/login/   {"username": "ana", "password": "ana12345"}

{
  "refresh": "eyJhbGciOiJIUzI1NiIs…",
  "access": "eyJhbGciOiJIUzI1NiIs…",
  "usuario": {
    "id": 2, "username": "ana", "first_name": "Ana", "last_name": "Pérez",
    "nombre_completo": "Ana Pérez", "rol": "EMPLEADO", "modalidad_liquidacion": "DIARIA",
    "fecha_alta": "2026-11-09", "is_active": true
  }
}
```

Las demás rutas piden `Authorization: Bearer <access>`. El `access` dura 12 horas y el `refresh`, 30 días.
El token también lleva el `rol` como claim. Un superusuario siempre se informa como `ENCARGADO`.

## Permisos

| Permiso | Regla | Dónde |
|---|---|---|
| `EsEncargado` | Solo el encargado | usuarios, notificaciones |
| `EncargadoEditaTodosLeen` | Cualquiera logueado lee; solo el encargado escribe | parámetros, feriados, productos, tarifas, horarios |
| Solo encargado escribe + cada empleado ve lo suyo | El empleado ve únicamente sus datos; el encargado ve todo y filtra con `?empleado=<id>` | tarifas, horarios, liquidaciones, pagos, resumen del día |

## Endpoints

### Catálogo y configuración

| Método | Ruta | Notas |
|---|---|---|
| GET/PATCH | `parametros/` · `parametros/<clave>/` | No se crean ni borran: solo se edita `valor` |
| GET/POST/PUT/PATCH/DELETE | `feriados/` | `?desde=&hasta=`. Un feriado pasado responde 409 al modificar o eliminar |
| GET/POST/PUT/PATCH/DELETE | `productos/` | `?activos=1`, `?buscar=texto`. DELETE = baja lógica (queda inactivo) |
| GET/POST/PUT/PATCH/DELETE | `tarifas/` | `?empleado=`. Historial protegido (ver reglas) |
| GET/POST/PUT/PATCH/DELETE | `horarios/` | `?empleado=&desde=&hasta=` |
| GET/POST/PUT/PATCH/DELETE | `usuarios/` | `?rol=&activos=1`. DELETE = desactivar (no a uno mismo) |

```json
GET /api/productos/?activos=1
[
  {"id": "9d89bbe9-…", "nombre": "Agua mineral 500 ml", "precio_costo": 600.0, "max_diario": 2,
   "codigo_barra": "AGENDAPP-0001", "activo": true, "actualizado": "2026-11-22T23:12:32.764970-03:00"},
  …
]
```

### Hoja del día

`GET resumen-dia/?fecha=AAAA-MM-DD[&empleado=<id>]` devuelve la cuenta de la hoja de ese día: tramos,
horas, tarifa y multiplicador aplicados, saldo anterior, movimientos ordenados y saldo a la fecha.

```json
GET /api/resumen-dia/?fecha=2026-11-19
{
  "empleado": 2, "fecha": "2026-11-19", "es_feriado": false, "feriado": null,
  "multiplicador": 1.0, "tarifa_hora": 2500.0,
  "tramos": [{"entrada": "08:40", "salida": "12:00"}, {"entrada": "16:00", "salida": "20:00"}],
  "turno_abierto": false, "minutos_trabajados": 440, "horas_trabajadas": "7:20",
  "saldo_anterior": 17208.33,
  "movimientos": [
    {"id": "0aab348c-…", "tipo": "ENTRADA", "hora": "08:40", "descripcion": "Entrada", "monto": null,
     "anulado": false, "corregido": false, "fuera_de_tolerancia": true, "motivo": "Se cortó el colectivo"},
    {"id": "3b1e390d-…", "tipo": "RETIRO", "hora": "11:00", "descripcion": "1 x Sándwich de miga (x2)",
     "cantidad": 1, "precio_costo": 1500.0, "monto": -1500.0, "anulado": false, "corregido": false},
    …
  ],
  …
}
```

### Notificaciones (encargado)

| Método | Ruta |
|---|---|
| GET | `notificaciones/[?no_leidas=1][&desde=<fecha-hora ISO>]` |
| GET | `notificaciones/cantidad_no_leidas/` → `{"cantidad": N}` |
| POST | `notificaciones/<id>/marcar_leida/` |
| POST | `notificaciones/marcar_todas_leidas/` |

### Pagos

| Método | Ruta | Notas |
|---|---|---|
| GET | `pagos/[?empleado=&desde=&hasta=&pendientes=1]` | El empleado ve solo los suyos |
| POST | `pagos/` | `{empleado, fecha, hora?, monto, observacion?}` registra un **adelanto** (solo el encargado) |
| POST | `pagos/<id>/anular/` | `{motivo}` |

### Liquidaciones

| Método | Ruta | Notas |
|---|---|---|
| GET | `liquidaciones/[?empleado=&estado=VIGENTE]` | |
| GET | `liquidaciones/<id>/` | Incluye `dias`: detalle por día con su estado de pago |
| GET | `liquidaciones/previsualizar/?empleado=<id>[&hasta=]` | Lo que se liquidaría, sin guardar nada |
| POST | `liquidaciones/` | `{empleado, hasta?, monto_pagado, fecha_pago?, hora_pago?, observacion?}` |
| POST | `liquidaciones/<id>/anular/` | `{motivo}`. Solo la última vigente |

```json
GET /api/liquidaciones/previsualizar/?empleado=3
{
  "empleado": 3, "modalidad": "DIARIA", "desde": "2026-11-09", "hasta": "2026-11-09",
  "saldo_anterior": 0.0, "minutos_trabajados": 0, "horas_trabajadas": "0:00",
  "ganado": 0.0, "retiros": 0.0, "adelantos": 0.0, "total_a_pagar": 0.0,
  "dias_con_turno_abierto": [], "dias": []
}
```

### Fichajes y retiros *(Fase 4)*

Los endpoints para que el celular **suba** fichajes y retiros (alta, anulación y modificación dentro del
plazo) llegan con la sincronización. La lógica ya está en `servicios.py` y probada en `ServiciosTests`.

## Errores

| Código | Cuándo | Forma |
|---|---|---|
| 400 | Una regla de negocio no se cumple | `{"detalle": ["mensaje", …]}` |
| 400 | Error de un campo (serializer) | `{"campo": ["mensaje"]}` |
| 401 | Falta el token o venció | `{"detail": "…"}` (formato de DRF) |
| 403 | No tiene permiso | `{"detail": "Solo el encargado puede realizar esta acción."}` |
| 409 | Conflicto: eliminar o modificar algo protegido | `{"detalle": "mensaje"}` |

Los mensajes están escritos para mostrarse tal cual al usuario. Ejemplos reales:

```json
POST /api/tarifas/  {"empleado": 2, "monto": "3000", "vigente_desde": "2026-11-01"}
400 {"detalle": ["La fecha de vigencia no puede ser anterior a hoy."]}

POST /api/liquidaciones/  {"empleado": 2, "monto_pagado": "100", "hasta": "2026-11-10"}
400 {"detalle": ["La fecha hasta no puede ser anterior al 21/11/2026 (día siguiente a la última liquidación)."]}

DELETE /api/feriados/<id del 01/01/2026>/
409 {"detalle": "El feriado del 01/01/2026 ya pasó: no se puede cargar, modificar ni eliminar porque cambiaría lo que se pagó ese día."}
```

La app interpreta estos formatos en `data/remote/ApiError.kt` (FrontEnd).
