"""La clave de la API guardada fuera del config.toml: en Windows, en el Administrador de
credenciales (vía keyring), cifrada con la cuenta del usuario. Si keyring no está o no tiene un
sistema donde guardar (Linux sin llavero), `available()` da False y se sigue con la variable de
entorno de siempre."""
from __future__ import annotations

SERVICE = "AltR"
ACCOUNT = "openai-api-key"


class SecretsError(RuntimeError):
    pass


def _keyring():
    try:
        import keyring
    except ImportError:
        return None
    return keyring


def available() -> bool:
    kr = _keyring()
    if kr is None:
        return False
    try:
        backend = kr.get_keyring()
    except Exception:
        return False
    # "fail.Keyring" y "null.Keyring" son los de mentira (prioridad 0): no guardan nada
    return getattr(backend, "priority", 0) > 0 or type(backend).__module__.endswith("Windows")


def get_api_key() -> str:
    """La clave guardada, o "" si no hay (o no se puede leer)."""
    kr = _keyring()
    if kr is None:
        return ""
    try:
        return (kr.get_password(SERVICE, ACCOUNT) or "").strip()
    except Exception:
        return ""


def set_api_key(key: str) -> None:
    kr = _keyring()
    if kr is None or not available():
        raise SecretsError("Este sistema no tiene dónde guardar claves de forma segura; "
                           "usá la variable de entorno.")
    try:
        kr.set_password(SERVICE, ACCOUNT, key.strip())
    except Exception as e:
        raise SecretsError(f"No pude guardar la clave: {e}") from e


def delete_api_key() -> None:
    kr = _keyring()
    if kr is None:
        return
    try:
        kr.delete_password(SERVICE, ACCOUNT)
    except Exception as e:
        if type(e).__name__ != "PasswordDeleteError":
            raise SecretsError(f"No pude borrar la clave: {e}") from e
