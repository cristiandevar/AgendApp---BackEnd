# Reglas de negocio

Cada regla indica **dónde está implementada**. Las marcadas con 📱 también están replicadas en la app
(`dominio/` del FrontEnd) para funcionar sin conexión: si se cambian acá, hay que cambiarlas allá.

## Fichajes

| Regla | Dónde |
|---|---|
| Las marcas vigentes del día, ordenadas por hora, alternan **entrada, salida, entrada…**, empiezan con entrada y **no se repiten horas**. 📱 | `reglas.validar_secuencia` |
| Se pueden tener **varios tramos por día** (mañana y tarde). Una entrada sin salida es un *turno abierto* y no suma horas hasta que se fiche la salida. 📱 | `calculos.armar_tramos` |
| **Tolerancia** (parámetro, 15 min): la entrada se compara con el inicio de horario más cercano y la salida con el fin más cercano. Si la diferencia supera la tolerancia, o si ese día **no tiene horario asignado**, la marca queda *fuera de tolerancia*. 📱 | `reglas.evaluar_tolerancia` |
| Fuera de tolerancia, el **motivo es obligatorio**. 📱 | `reglas.validar_motivo` |
| Se pagan las **horas reales**, no las del horario. | `calculos` |
| No hay horarios que crucen la medianoche. | `HorarioAsignado.clean` |
| El empleado no modifica fichajes: **solo puede anularlos**, dentro del plazo (parámetro, 10 min). 📱 | `servicios.anular_fichaje_empleado` |
| Solo se puede anular el **último fichaje vigente del día**. 📱 *(en el servidor, Fase 4)* | `Reglas.impedimentoParaAnular` (app) |
| La hora del celular para un fichaje nuevo tiene que ser **posterior al último fichaje vigente** del día (el servidor rechaza dos marcas a la misma hora). 📱 | `Reglas.controlarFichaje` (app) |
| Los fichajes olvidados los carga el **encargado**, con motivo y auditoría. | `admin.FichajeAdmin` |

## Retiros de productos

| Regla | Dónde |
|---|---|
| **Máximo diario** por empleado y producto (`max_diario`, 0 = sin límite). Al modificar, no cuenta el propio retiro. No se maneja stock. 📱 | `reglas.validar_maximo_diario` |
| El **precio de costo se congela** al retirar. 📱 | `servicios.registrar_retiro` |
| Dentro del plazo el empleado puede **modificar** (producto y/o cantidad) o **anular** sin justificar. Si cambia el producto, toma el precio actual del nuevo; si no, conserva el congelado. 📱 | `servicios.modificar_retiro_empleado`, `anular_retiro_empleado` |
| Un producto inactivo no se puede retirar (sí conservar en una modificación del mismo retiro). 📱 | `servicios` |
| Pasado el plazo, solo el encargado cambia el retiro, con motivo y auditoría. | `admin.RetiroAdmin` |

## El plazo del empleado

El plazo (parámetro `anulacion_fichaje_minutos`, 10 min) corre desde **`registrado_en`, el momento exacto
de registro con segundos**, no desde la hora que muestra la hoja (que va al minuto). Un retiro registrado
a las 22:38:45 se puede cambiar hasta las 22:48:45. 📱 `reglas.dentro_del_plazo`

## Horas, ganado y saldo

```
ganado del día   = minutos trabajados / 60 × tarifa vigente × multiplicador del día
saldo a la fecha = saldo anterior + ganado − productos retirados − monto recibido
```

| Regla | Dónde |
|---|---|
| Redondeo: operaciones con `Decimal` y redondeo final **HALF_UP a 2 decimales**. 📱 (la app usa `MathContext(28, HALF_EVEN)` en el medio, igual que el contexto por defecto de Python) | `calculos.calcular_ganado` |
| **Tarifa vigente** de un día = la de `vigente_desde` más reciente que sea ≤ ese día. 📱 | `calculos` |
| **Feriado**: la hora vale el multiplicador **guardado en el feriado** (default 2, del parámetro al crearlo). 📱 | `Feriado` |
| El saldo se **arrastra** día a día como una cuenta corriente: positivo = el local le debe al empleado; negativo = el empleado debe. 📱 | `calculos.saldo_hasta` |
| Los movimientos **anulados no suman**. 📱 | todo `calculos` |
| En la hoja, el monto de cada salida es lo ganado en ese tramo, calculado como diferencia acumulada para que la suma de las salidas dé exacto el total del día. 📱 | `Calculos.ganadoPorSalida` (app) |

## Historial protegido

| Regla | Dónde |
|---|---|
| Una **tarifa** nueva rige desde hoy en adelante **y** después del último fichaje del empleado. Una que ya empezó a regir no se modifica ni se elimina: se carga otra. | `TarifaHora.clean`, `validar_eliminable` |
| Un **feriado** de fecha pasada no se carga, modifica ni elimina. | `Feriado.clean`, `validar_eliminable` |
| **Nada se borra**: fichajes, retiros, pagos y liquidaciones se anulan; productos y usuarios se desactivan. | modelos, admin y vistas |

## Liquidaciones y pagos

```
total a pagar    = saldo anterior + ganado − retiros − adelantos pendientes
saldo resultante = total a pagar − monto pagado
```

| Regla | Dónde |
|---|---|
| **Períodos contiguos**: cada liquidación empieza el día siguiente al `hasta` de la última vigente. La primera, en la fecha de alta (o en el primer movimiento, si hay uno anterior). | `liquidaciones.proximo_desde` |
| El encargado elige solo el `hasta`; el sistema **sugiere** uno según la modalidad (diaria, semanal = 7 días, quincenal = 15 o fin de mes, mensual, trimestral), sin pasar de hoy. | `liquidaciones.hasta_sugerido` |
| Se permiten **pagos parciales**: lo que falta queda como saldo anterior de la próxima. | `liquidaciones.liquidar` |
| Un **adelanto** (pago sin liquidar) queda pendiente y la próxima liquidación lo descuenta y lo asocia. Se registra con fecha de hoy o anterior, en un día no liquidado. | `registrar_adelanto`, `validar_pago_suelto` |
| Mientras una liquidación está vigente, sus días quedan **bloqueados para el encargado**. Para corregir, primero se anula la liquidación (solo la última vigente, con motivo); sus pagos vuelven a quedar pendientes. | `reglas.validar_dia_no_liquidado`, `liquidaciones.anular` |
| Lo que llega **tarde por sincronización** a un día ya liquidado se acepta igual (ya ocurrió) y aparece como **diferencia** en el saldo anterior de la liquidación siguiente. | `liquidaciones.diferencia` |
| El **estado de pago** de cada día (pagado, parcial, pendiente o sin monto) no se guarda: se calcula aplicando todo lo pagado a los días más viejos primero (FIFO). | `calculos.estado_pago_por_dia` |

## Notificaciones y auditoría

- Cada fichaje, retiro, anulación o modificación del empleado **notifica al encargado**. Un fichaje fuera
  de horario llega *destacado* e incluye el motivo. (`servicios._notificar`)
- Toda corrección del encargado pide **motivo** y queda en `AuditoriaFichaje` / `AuditoriaRetiro` con los
  datos anteriores y nuevos. Lo que carga o corrige el encargado queda con `corregido = True` y la app lo
  muestra con un lápiz.
