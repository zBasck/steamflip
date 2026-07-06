"""Login e ciclo de vida da sessão Steam.

Usa ``pysteamauth`` para fazer login com username + senha + shared_secret
do maFile (Steam Desktop Authenticator). O cliente resultante tem
``await client.request(url)`` que devolve JSON ou HTML, e já mantém
os cookies autenticados entre chamadas — destravando o ``/pricehistory/``
e o ``/priceoverview/`` que sem login retornam HTTP 400.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from pysteamauth.auth import Steam
from pysteamauth.errors import SteamError

from .config import MAFILE_PATH, STEAM_PASSWORD, STEAM_USERNAME

LOG = logging.getLogger("steamflip")


class AuthError(Exception):
    """Erro de autenticação na Steam."""


def _ler_shared_secret(caminho: str | Path) -> str:
    """Lê o shared_secret do maFile no formato SDA (JSON)."""
    caminho = Path(caminho)
    if not caminho.is_file():
        raise AuthError(
            f"maFile não encontrado: {caminho}. "
            f"Verifique se o arquivo está no caminho esperado."
        )
    try:
        with caminho.open("r", encoding="utf-8") as f:
            dados = json.load(f)
    except json.JSONDecodeError as exc:
        raise AuthError(f"maFile inválido (JSON corrompido): {exc}") from exc

    shared = dados.get("shared_secret")
    if not shared:
        raise AuthError(
            f"maFile não contém 'shared_secret'. "
            f"Abra o SDA, clique 'Login Again' e salve novamente."
        )
    return shared


async def fazer_login(
    username: str = STEAM_USERNAME,
    password: str = STEAM_PASSWORD,
    mafile_path: str | Path = MAFILE_PATH,
) -> Steam:
    """Faz login na Steam e devolve um cliente autenticado.

    O ``pysteamauth.Steam`` aceita username/senha + shared_secret do maFile
    e gera automaticamente o código 2FA a cada login (sem precisar do app
    do celular). Após o login, o cliente mantém cookies em todos os domínios
    Steam necessários (steamcommunity, store, help.steampowered).

    Levanta ``AuthError`` em qualquer falha de login.
    """
    LOG.info("Fazendo login na Steam como %s ...", username)
    shared_secret = _ler_shared_secret(mafile_path)

    try:
        client = Steam(
            login=username,
            password=password,
            shared_secret=shared_secret,
        )
        await client.login_to_steam()
    except SteamError as exc:
        raise AuthError(
            f"Falha no login Steam ({type(exc).__name__}): {exc}. "
            f"Verifique usuário, senha e se o maFile foi gerado pelo SDA "
            f"com 'shared_secret' válido."
        ) from exc
    except Exception as exc:  # noqa: BLE001
        raise AuthError(
            f"Erro inesperado no login: {type(exc).__name__}: {exc}"
        ) from exc

    LOG.info("✓ Login Steam realizado com sucesso (modo autenticado).")
    return client
