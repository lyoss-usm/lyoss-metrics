"""Autenticacion como GitHub App (mvp-ingesta.md, seccion 10).

JWT (RS256) firmado con la clave privada -> token de instalacion (dura 1 h).
La clave privada se lee de Secret Manager con ADC y solo vive en memoria.
"""
import logging
import time

import jwt
import requests
from google.cloud import secretmanager

API = "https://api.github.com"
API_VERSION = "2026-03-10"
TIMEOUT = (10, 30)  # (connect, read) en segundos

log = logging.getLogger(__name__)


class AuthError(Exception):
    """Fallo al obtener la clave privada o el token de instalacion."""


def read_pem(project: str, secret: str) -> str:
    """Lee la ultima version del secreto con Application Default Credentials."""
    name = f"projects/{project}/secrets/{secret}/versions/latest"
    try:
        client = secretmanager.SecretManagerServiceClient()
        response = client.access_secret_version(name=name, retry=None, timeout=30)
    except Exception as e:  # noqa: BLE001 - se reporta con contexto, sin el contenido
        raise AuthError(f"no se pudo leer el secreto {name}: {type(e).__name__}: {e}") from e
    return response.payload.data.decode("utf-8")


def installation_token(app_id: str, installation_id: str, pem: str) -> str:
    now = int(time.time())
    iat = now - 60  # tolerancia ante desfase de reloj
    claims = {"iss": str(app_id), "iat": iat, "exp": iat + 10 * 60}
    try:
        app_jwt = jwt.encode(claims, pem, algorithm="RS256")
    except Exception as e:  # noqa: BLE001 - PEM invalido, etc. (sin volcar el PEM)
        raise AuthError(f"no se pudo firmar el JWT: {type(e).__name__}") from e

    try:
        resp = requests.post(
            f"{API}/app/installations/{installation_id}/access_tokens",
            headers={
                "Authorization": f"Bearer {app_jwt}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": API_VERSION,
            },
            timeout=TIMEOUT,
        )
    except requests.RequestException as e:
        raise AuthError(f"error de red al pedir el token de instalacion: {type(e).__name__}: {e}") from e

    if resp.status_code != 201:
        try:
            detail = resp.json().get("message", "")
        except ValueError:
            detail = resp.text[:200]
        raise AuthError(f"GitHub respondio HTTP {resp.status_code} al pedir el token: {detail}")

    token = resp.json().get("token")
    if not token:
        raise AuthError("la respuesta de GitHub no incluye 'token'")
    log.info("token de instalacion obtenido")
    return token
