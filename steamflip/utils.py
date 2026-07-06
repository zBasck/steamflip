"""Funções utilitárias compartilhadas."""

from __future__ import annotations

import logging
import re
import time
from datetime import datetime
from typing import Callable, Iterable, TypeVar

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

T = TypeVar("T")

LOG = logging.getLogger("steamflip")

# Cabeçalho padrão para se passar por um navegador comum. O mercado Steam público
# retorna HTML/JSON um pouco diferente para clientes sem User-Agent.
DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json,text/plain,*/*",
    "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
}


def configurar_logging(verbose: bool = False) -> None:
    """Configura logging em formato simples para o terminal.

    Força ``stream=sys.stdout`` e remove o buffering para que as linhas
    apareçam em tempo real (no Windows o ``print``/``logging`` pode
    bufferizar a saída inteira e o usuário só vê os logs no final).
    """
    import sys

    level = logging.DEBUG if verbose else logging.INFO
    handler = logging.StreamHandler(stream=sys.stdout)
    handler.setFormatter(
        logging.Formatter(
            fmt="%(asctime)s [%(levelname)s] %(message)s",
            datefmt="%H:%M:%S",
        )
    )
    handler.flush = sys.stdout.flush  # type: ignore[method-assign]

    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(level)
    root.addHandler(handler)


def criar_sessao(cookies: dict[str, str] | None = None) -> requests.Session:
    """Cria uma sessão HTTP com retry automático.

    Se cookies for informado, aplica-os aos domínios do Steam
    (steamcommunity.com e store.steampowered.com). Os cookies
    esperados são steamLoginSecure e sessionid (CSRF token).
    """
    s = requests.Session()
    s.headers.update(DEFAULT_HEADERS)
    retries = Retry(
        total=3,
        backoff_factor=0.6,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset(["GET"]),
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retries, pool_connections=4, pool_maxsize=4)
    s.mount("https://", adapter)
    s.mount("http://", adapter)

    if cookies:
        for dominio in ("steamcommunity.com", "store.steampowered.com"):
            for chave, valor in cookies.items():
                s.cookies.set(chave, valor, domain=dominio, path="/")
    return s


def slugify_appid(jogo: str) -> int:
    """Resolve um nome amigável de jogo (dota2, cs2, tf2) para o appid Steam."""
    from .config import JOGOS

    chave = jogo.lower().strip()
    if chave not in JOGOS:
        raise ValueError(
            f"Jogo desconhecido: {jogo!r}. Use um destes: {sorted(JOGOS)}"
        )
    return JOGOS[chave]["appid"]


def parse_preco_steam(texto: str | None) -> float:
    """Converte 'R$ 12,34' / '$12.34' / '12,34' em float. Retorna 0.0 se vazio."""
    if not texto:
        return 0.0
    s = re.sub(r"[^\d,.\-]", "", texto)
    if not s:
        return 0.0
    # O último separador presente define o decimal:
    #   "1.234,56" (BR) -> vírgula é o decimal -> 1234.56
    #   "1,234.56" (US) -> ponto é o decimal -> 1234.56
    if "," in s and "." in s:
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "," in s:
        s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return 0.0


def parse_timestamp_steam(ts: str) -> datetime:
    """O histórico de preços vem como 'Jul 01 2026 01: +0'."""
    return datetime.strptime(ts, "%b %d %Y %H: +0")


def url_listing(appid: int, market_hash_name: str) -> str:
    """Monta a URL direta da página de listagem do item no mercado Steam."""
    from urllib.parse import quote

    return (
        f"https://steamcommunity.com/market/listings/{appid}/"
        f"{quote(market_hash_name, safe='')}"
    )


def rate_limit(segundos: float) -> None:
    """Pausa para evitar 429 do mercado público."""
    if segundos > 0:
        time.sleep(segundos)


def em_partes(itens: Iterable[T], tamanho: int) -> Iterable[list[T]]:
    """Quebra uma coleção em lotes de tamanho fixo."""
    lote: list[T] = []
    for item in itens:
        lote.append(item)
        if len(lote) >= tamanho:
            yield lote
            lote = []
    if lote:
        yield lote


def com_retry(fn: Callable[[], T], tentativas: int = 3, espera: float = 1.5) -> T:
    """Executa fn() com retry exponencial; propaga a última exceção."""
    ultimo_erro: Exception | None = None
    for i in range(tentativas):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001
            ultimo_erro = exc
            LOG.debug("Falha na tentativa %d: %s", i + 1, exc)
            time.sleep(espera * (2**i))
    assert ultimo_erro is not None
    raise ultimo_erro
