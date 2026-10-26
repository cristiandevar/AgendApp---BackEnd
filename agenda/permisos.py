from rest_framework.permissions import SAFE_METHODS, BasePermission


class EsEncargado(BasePermission):
    message = "Solo el encargado puede realizar esta acción."

    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and request.user.es_encargado)


class EncargadoEditaTodosLeen(BasePermission):
    """Cualquier usuario logueado puede consultar; solo el encargado crea, modifica o elimina."""

    message = "Solo el encargado puede modificar estos datos."

    def has_permission(self, request, view):
        if not (request.user and request.user.is_authenticated):
            return False
        return request.method in SAFE_METHODS or request.user.es_encargado
