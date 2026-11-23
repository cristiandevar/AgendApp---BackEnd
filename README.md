# AgendApp - BackEnd

Servidor de **AgendApp**: registro de horas trabajadas y productos retirados por los empleados, con
liquidaciones y saldo a cobrar. Lo usan la app Android (repositorio **AgendApp - FrontEnd**) a través de
una API REST y el encargado a través del Django Admin.

- Python 3 · Django 5.2 · Django REST Framework 3.18 · SimpleJWT 5.5
- SQLite en desarrollo, PostgreSQL en producción
- Una sola app de Django: `agenda`

## Puesta en marcha rápida

```bash
python -m venv .venv
.venv\Scripts\activate            # Windows  (Linux/macOS: source .venv/bin/activate)
pip install -r requirements.txt
python manage.py migrate
python manage.py seed_agenda --demo  # datos de ejemplo (idempotente)
python manage.py runserver 0.0.0.0:8000
```

- Admin: <http://localhost:8000/admin/> con `encargado` / `encargado123`
- API: <http://localhost:8000/api/>
- Empleados de prueba: `ana` / `ana12345` y `luis` / `luis12345`

Tests: `python manage.py test agenda` (58 tests).

## Documentación

| Para | Documento |
|---|---|
| Entender el sistema | [Arquitectura](docs/desarrollo/arquitectura.md) · [Modelo de datos](docs/desarrollo/modelo-de-datos.md) · [Reglas de negocio](docs/desarrollo/reglas-de-negocio.md) |
| Integrar la app | [API REST](docs/desarrollo/api.md) |
| Aportar código | [Cómo aportar](docs/desarrollo/como-aportar.md) |
| Usar el sistema (encargado) | [Guía del encargado](docs/uso/guia-del-encargado.md) |

El plan de fases del proyecto está en [`PLAN.md`](PLAN.md).
