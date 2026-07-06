"""Carregamento e operações com .maFile do Steam Desktop Authenticator.

Fornece:
- ``MaFile``: dataclass com os campos necessários.
- ``carregar_mafile``: lê do disco e detecta formato (moderno ou legado).
- ``codigo_totp``: gera código 2FA Steam.
- ``tag_mobileconf``: gera tag para confirmação mobile (HMAC-SHA1 com identity_secret).
- ``montar_cookies``: monta ``steamLoginSecure`` e ``sessionid`` para a ``requests.Session``.
- ``session_expirada``: checa o ``exp`` do JWT embutido.

Este módulo **NUNCA** deve logar os segredos. Logs só contêm ``account_name``
e o final do ``steam_id`` (com mascaramento).

Referências:
    - https://github.com/bukson/steampy (TOTP, mobileconf)
    - https://github.com/SteamDatabase/SteamAuth (SDA)
"""

from __future__ import annotations

import base64
import hmac
import json
import logging
import re
import struct
import time
from dataclasses import dataclass
from hashlib import sha1
from pathlib import Path

LOG = logging.getLogger("steamflip")

# Alfabeto customizado da Steam (26 chars, sem 0/1/O/I/L/Z para evitar confusão).
_STEAM_CHARS = "23456789BCDFGHJKMNPQRTVWXY"


# ============================================================
# Estruturas de dados
# ============================================================


@dataclass
class MaFile:
    """Representa um .maFile SDA carregado em memória."""

    account_name: str
    shared_secret: str  # base64
    identity_secret: str  # base64
    steam_id: int
    access_token: str  # JWT
    refresh_token: str | None  # pode ser None no formato legado
    session_id: str  # CSRF token (32 chars hex)
    fully_enrolled: bool
    caminho_origem: Path

    def steam_id_mascarado(self) -> str:
        """Retorna o SteamID64 mascarado para logs seguros (ex: ``...0425654``)."""
        s = str(self.steam_id)
        if len(s) <= 7:
            return "***"
        return "..." + s[-7:]


# ============================================================
# Exceções
# ============================================================


class MaFileError(Exception):
    """Erro de leitura/validação do .maFile."""


# ============================================================
# Leitura do .maFile
# ============================================================


def carregar_mafile(caminho: str | Path) -> MaFile:
    """Lê e valida um .maFile SDA.

    Suporta dois formatos:
        - **Moderno (pós-2022)**: ``Session.AccessToken`` + ``Session.RefreshToken``.
        - **Legado**: ``Session.SteamLoginSecure`` (cookie pronto).

    Levanta ``MaFileError`` se o arquivo for inválido, não estiver ``fully_enrolled``,
    ou se faltarem campos essenciais.
    """
    p = Path(caminho)
    if not p.is_file():
        raise MaFileError(f"maFile não encontrado: {caminho}")

    # Aviso de permissões (operações 2FA: arquivo não deve ser world-readable).
    try:
        mode = p.stat().st_mode & 0o777
        if mode & 0o044:
            LOG.warning(
                "maFile com permissões amplas (mode=%s); recomenda-se 0600.",
                oct(mode),
            )
    except OSError:
        pass  # não bloqueia em FS que não suportam stat mode

    try:
        dados = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise MaFileError(f"Falha ao ler JSON do maFile: {exc}") from exc

    if not isinstance(dados, dict):
        raise MaFileError("maFile não é um objeto JSON.")

    if not dados.get("fully_enrolled"):
        raise MaFileError(
            "maFile com fully_enrolled=false; o autenticador ainda não foi "
            "aplicado à conta. Gere o maFile pelo SDA após a confirmação inicial."
        )

    sessao = dados.get("Session") or {}
    if not isinstance(sessao, dict):
        raise MaFileError("Campo 'Session' inválido no maFile.")

    # --- SteamID ---
    steam_id_raw = sessao.get("SteamID")
    if steam_id_raw is None:
        raise MaFileError("maFile sem Session.SteamID.")
    try:
        steam_id = int(steam_id_raw)
    except (TypeError, ValueError) as exc:
        raise MaFileError(f"Session.SteamID inválido: {steam_id_raw!r}") from exc

    # --- AccessToken (formato moderno) ---
    access_token = (sessao.get("AccessToken") or "").strip()
    refresh_token = sessao.get("RefreshToken")

    # --- Fallback: formato legado (SteamLoginSecure pronto) ---
    if not access_token:
        legacy = (sessao.get("SteamLoginSecure") or "").strip()
        if not legacy:
            raise MaFileError(
                "maFile sem AccessToken nem SteamLoginSecure; sessão ausente."
            )
        # O cookie legado tem o formato "{SteamID}%7C%7C{JWT}".
        # Reaproveitamos o JWT cru.
        partes = legacy.split("%7C%7C", 1)
        if len(partes) != 2 or not partes[1]:
            raise MaFileError(
                "SteamLoginSecure em formato inesperado; não consegui extrair o JWT."
            )
        access_token = partes[1]

    # --- SessionID (CSRF token) ---
    session_id = (sessao.get("SessionID") or "").strip()
    if not session_id or not re.fullmatch(r"[0-9a-fA-F]+", session_id):
        raise MaFileError("Session.SessionID ausente ou inválido.")

    # --- Campos essenciais do maFile ---
    shared_secret = (dados.get("shared_secret") or "").strip()
    identity_secret = (dados.get("identity_secret") or "").strip()
    if not shared_secret or not identity_secret:
        raise MaFileError(
            "maFile sem shared_secret ou identity_secret; authenticator incompleto."
        )

    account_name = (dados.get("account_name") or "").strip()
    if not account_name:
        account_name = f"steam_{steam_id}"

    return MaFile(
        account_name=account_name,
        shared_secret=shared_secret,
        identity_secret=identity_secret,
        steam_id=steam_id,
        access_token=access_token,
        refresh_token=refresh_token,
        session_id=session_id,
        fully_enrolled=True,
        caminho_origem=p,
    )


# ============================================================
# TOTP (código 2FA)
# ============================================================


def codigo_totp(shared_secret: str, *, timestamp: int | None = None) -> str:
    """Gera um código TOTP Steam de 5 caracteres.

    O algoritmo é HMAC-SHA1 com:
        - counter = int(timestamp) // 30
        - counter packed como uint64 big-endian
        - alfabeto: ``23456789BCDFGHJKMNPQRTVWXY``
    """
    if not shared_secret:
        raise MaFileError("shared_secret vazio; impossível gerar TOTP.")
    if timestamp is None:
        timestamp = int(time.time())
    try:
        key = base64.b64decode(shared_secret, validate=False)
    except (TypeError, ValueError) as exc:
        raise MaFileError("shared_secret não é base64 válido.") from exc

    counter = timestamp // 30
    msg = struct.pack(">Q", counter)
    digest = hmac.new(key, msg, sha1).digest()

    # Truncamento dinâmico (RFC 4226).
    offset = digest[-1] & 0x0F
    code_int = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF

    # Mapeia em base-26 sobre o alfabeto Steam.
    code_chars = []
    for _ in range(5):
        code_int, idx = divmod(code_int, len(_STEAM_CHARS))
        code_chars.append(_STEAM_CHARS[idx])
    return "".join(code_chars)


# ============================================================
# Mobile confirmation tag (HMAC com identity_secret)
# ============================================================


def tag_mobileconf(identity_secret: str, tag: str, *, timestamp: int | None = None) -> str:
    """Gera o ``tag`` para confirmação mobile Steam (base64 padrão).

    Usado nos endpoints ``/mobileconf/getlist`` e ``/mobileconf/ajaxop``,
    e também no campo ``conf`` de ``/market/sellitem`` e ``/market/buylisting``.

    Layout do HMAC input (sem divisor):
        - 8 bytes: timestamp Unix (little-endian, uint64) — note: não é big-endian
        - N bytes: tag em UTF-8
    """
    if not identity_secret:
        raise MaFileError("identity_secret vazio; impossível gerar tag.")
    if timestamp is None:
        timestamp = int(time.time())
    try:
        key = base64.b64decode(identity_secret, validate=False)
    except (TypeError, ValueError) as exc:
        raise MaFileError("identity_secret não é base64 válido.") from exc

    # Little-endian! (é o caso da implementação canônica do SteamAuth C#)
    msg = struct.pack("<Q", timestamp) + tag.encode("utf-8")
    digest = hmac.new(key, msg, sha1).digest()
    return base64.b64encode(digest).decode("ascii")


# ============================================================
# Cookies para requests.Session
# ============================================================


def montar_cookies(mafile: MaFile) -> dict[str, str]:
    """Monta os cookies ``steamLoginSecure`` e ``sessionid`` para uso HTTP."""
    steam_login_secure = f"{mafile.steam_id}%7C%7C{mafile.access_token}"
    return {
        "steamLoginSecure": steam_login_secure,
        "sessionid": mafile.session_id,
        # domínios são aplicados pelo caller (mercado.py).
    }


# ============================================================
# Validade da sessão (JWT exp)
# ============================================================


def session_expirada(mafile: MaFile) -> bool:
    """Checa se o ``access_token`` embutido já expirou.

    Decodifica **apenas** o payload do JWT (base64 url-safe, sem verificar
    assinatura) e olha o claim ``exp``. Falha = considera expirada (fail-closed).
    """
    jwt = mafile.access_token
    if not jwt:
        return True

    partes = jwt.split(".")
    if len(partes) < 2:
        LOG.debug("AccessToken não parece JWT; considerando expirado.")
        return True

    payload_b64 = partes[1]
    # base64 url-safe com padding ajustado.
    padding = "=" * (-len(payload_b64) % 4)
    try:
        payload_bytes = base64.urlsafe_b64decode(payload_b64 + padding)
        payload = json.loads(payload_bytes)
    except (ValueError, json.JSONDecodeError) as exc:
        LOG.debug("Falha ao decodificar payload do JWT: %s", exc)
        return True

    exp = payload.get("exp")
    if not isinstance(exp, (int, float)):
        # Sem claim exp; não dá pra garantir; trate como expirada.
        LOG.debug("JWT sem claim 'exp'; considerando expirado.")
        return True

    agora = int(time.time())
    return bool(exp <= agora)


__all__ = [
    "MaFile",
    "MaFileError",
    "carregar_mafile",
    "codigo_totp",
    "tag_mobileconf",
    "montar_cookies",
    "session_expirada",
]
