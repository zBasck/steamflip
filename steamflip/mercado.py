"""Cliente HTTP autenticado para o mercado Steam (pysteamauth).

O ``pysteamauth.Steam`` mantém cookies de sessão após o login, então as
chamadas para ``/search/render/``, ``/pricehistory/`` e ``/priceoverview/``
funcionam autenticadas — sem o HTTP 400 do mercado público anônimo.

Todas as funções são ``async`` e devolvem os dados normalizados ou
levantam ``MercadoError`` em caso de falha.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import AsyncIterator

import pandas as pd

from .config import MOEDAS
from .utils import (
    parse_preco_steam,
    parse_timestamp_steam,
    rate_limit_async,
    url_listing,
)

LOG = logging.getLogger("steamflip")

BASE_URL = "https://steamcommunity.com/market"
SEARCH_URL = "https://steamcommunity.com/market/search/render/"


class MercadoError(Exception):
    """Erro de comunicação com o mercado Steam."""


@dataclass
class ItemPopular:
    """Item retornado pela busca de populares."""

    appid: int
    market_hash_name: str
    nome: str
    url_imagem: str
    sell_listings: int  # ordens de venda ativas (proxy de volume/liquidez)
    moeda: str  # texto original (ex.: "R$ 12,34")
    preco_lowest: float  # lowest sell price atual (pode ser 0 se não disponível)
    preco_median: float  # median price atual


async def _request_json(client, url: str, params: dict | None = None) -> dict | list:
    """Faz GET autenticado via pysteamauth e devolve o JSON decodificado.

    pysteamauth devolve um dict/list se a resposta for JSON, ou string/bytes
    se for HTML. Aqui nós aceitamos ambos e convertemos.
    """
    try:
        resp = await client.request(url=url, method="GET", params=params or {})
    except Exception as exc:  # noqa: BLE001
        raise MercadoError(f"Falha HTTP em {url}: {exc}") from exc

    # pysteamauth pode devolver string (JSON) ou bytes.
    if isinstance(resp, (bytes, bytearray)):
        try:
            texto = resp.decode("utf-8", errors="ignore")
        except Exception:  # noqa: BLE001
            raise MercadoError(f"Resposta binária inválida em {url}")
        if not texto.strip():
            raise MercadoError(f"Resposta vazia em {url}")
        if texto.lstrip()[:200].lower().startswith(("<!doctype", "<html")):
            raise MercadoError(
                f"Resposta HTML em {url} (provável erro/rate limit)."
            )
        try:
            return json.loads(texto)
        except json.JSONDecodeError as exc:
            raise MercadoError(f"JSON inválido em {url}: {exc}") from exc

    if isinstance(resp, str):
        if not resp.strip():
            raise MercadoError(f"Resposta vazia em {url}")
        head = resp.lstrip()[:200].lower()
        if head.startswith(("<!doctype", "<html")):
            raise MercadoError(
                f"Resposta HTML em {url} (provável erro/rate limit)."
            )
        try:
            return json.loads(resp)
        except json.JSONDecodeError as exc:
            raise MercadoError(f"JSON inválido em {url}: {exc}") from exc

    if isinstance(resp, (dict, list)):
        return resp

    raise MercadoError(
        f"Tipo inesperado de resposta em {url}: {type(resp).__name__}"
    )


async def _request_text(client, url: str, params: dict | None = None) -> str:
    """GET autenticado devolvendo o corpo como string (HTML ou texto)."""
    try:
        resp = await client.request(url=url, method="GET", params=params or {})
    except Exception as exc:  # noqa: BLE001
        raise MercadoError(f"Falha HTTP em {url}: {exc}") from exc
    if isinstance(resp, (bytes, bytearray)):
        return resp.decode("utf-8", errors="ignore")
    if isinstance(resp, str):
        return resp
    raise MercadoError(
        f"Tipo inesperado de resposta em {url}: {type(resp).__name__}"
    )


# Categorias aceitas pelo endpoint /search/render/. Apenas CS2 (appid 730)
# suporta os filtros de categoria abaixo; enviar esses parâmetros para
# outros appids faz a Steam retornar HTTP 400.
_CATEGORIAS_CS2 = (
    "category_730_ItemSet[]",
    "category_730_ProPlayer[]",
    "category_730_StickerCapsule[]",
    "category_730_Tournament[]",
    "category_730_TournamentTeam[]",
)


def _categorias_para_appid(appid: int) -> dict[str, str]:
    if appid == 730:
        return {chave: "" for chave in _CATEGORIAS_CS2}
    return {}


async def listar_itens_populares(
    client,
    appid: int,
    *,
    limite: int = 1000,
    currency: int = 986,
    pagina_tamanho: int = 10,
    rate: float = 1.5,
) -> list[ItemPopular]:
    """Lista os itens mais populares de um app por volume/quantidade de
    listagens ativas (proxy de popularidade).

    Observação: o mercado Steam trava ``pagesize`` em 10 mesmo autenticado
    em algumas situações. Por isso o default é 10 e o avanço é de 10 em 10.
    """
    pagina_tamanho = max(1, min(pagina_tamanho, 10))

    itens: list[ItemPopular] = []
    start = 0
    pagina = 0
    categorias = _categorias_para_appid(appid)
    while len(itens) < limite:
        pagina += 1
        params = {
            "appid": appid,
            "norender": 1,
            "count": pagina_tamanho,
            "start": start,
            "sort_column": "quantity",  # ordena por volume
            "sort_dir": "desc",
            "currency": currency,
        }
        params.update(categorias)
        LOG.info(
            "Buscando populares appid=%s página=%d start=%d",
            appid,
            pagina,
            start,
        )
        await rate_limit_async(rate)
        data = await _request_json(client, SEARCH_URL, params)

        resultados = data.get("results", []) if isinstance(data, dict) else []
        if not resultados:
            LOG.info("Sem mais resultados para appid=%s (start=%d)", appid, start)
            break

        for r in resultados:
            hash_name = (r.get("hash_name") or "").strip()
            if not hash_name:
                continue
            sell_listings = int(r.get("sell_listings") or 0)
            if sell_listings <= 0:
                continue
            itens.append(
                ItemPopular(
                    appid=appid,
                    market_hash_name=hash_name,
                    nome=(r.get("name") or hash_name).strip(),
                    url_imagem=r.get("asset_description", {}).get("icon_url", "")
                    or r.get("icon_url", ""),
                    sell_listings=sell_listings,
                    moeda=r.get("sell_price_text", ""),
                    preco_lowest=parse_preco_steam(r.get("sell_price_text", "")),
                    preco_median=parse_preco_steam(r.get("median_price_text", "")),
                )
            )
            if len(itens) >= limite:
                break

        # Critério principal: página incompleta = fim do inventário.
        if len(resultados) < pagina_tamanho:
            break

        total = int(data.get("total_count", 0)) if isinstance(data, dict) else 0
        if total and start + pagina_tamanho >= total:
            break

        start += pagina_tamanho

    LOG.info("Total coletado para appid=%s: %d itens", appid, len(itens))
    return itens


async def obter_historico(
    client,
    appid: int,
    market_hash_name: str,
    *,
    currency: int = 986,
    rate: float = 1.0,
) -> pd.DataFrame:
    """Baixa o histórico de preços de um item. Retorna DataFrame vazio em
    caso de erro ou item sem histórico.
    """
    params = {
        "appid": appid,
        "market_hash_name": market_hash_name,
        "currency": currency,
    }
    url = f"{BASE_URL}/pricehistory/"
    try:
        await rate_limit_async(rate)
        data = await _request_json(client, url, params)
    except MercadoError as exc:
        LOG.debug("Histórico indisponível para %s: %s", market_hash_name, exc)
        return pd.DataFrame(columns=["timestamp", "preco", "volume"])

    if not isinstance(data, dict) or not data.get("success"):
        return pd.DataFrame(columns=["timestamp", "preco", "volume"])

    precos = data.get("prices") or []
    if not precos:
        return pd.DataFrame(columns=["timestamp", "preco", "volume"])

    df = pd.DataFrame(precos, columns=["timestamp_raw", "preco", "volume"])
    df["preco"] = df["preco"].astype(str).str.replace(",", ".").astype(float)
    df["volume"] = pd.to_numeric(df["volume"], errors="coerce").fillna(0).astype(int)
    try:
        df["timestamp"] = df["timestamp_raw"].apply(parse_timestamp_steam)
    except Exception:  # noqa: BLE001
        return pd.DataFrame(columns=["timestamp", "preco", "volume"])
    return df[["timestamp", "preco", "volume"]]


async def obter_preco_atual(
    client,
    appid: int,
    market_hash_name: str,
    *,
    currency: int = 986,
    rate: float = 1.0,
) -> tuple[float, float]:
    """Retorna (lowest_price, median_price) atuais em moeda local. (0,0) se
    não disponível."""
    params = {
        "appid": appid,
        "market_hash_name": market_hash_name,
        "currency": currency,
    }
    url = f"{BASE_URL}/priceoverview/"
    try:
        await rate_limit_async(rate)
        data = await _request_json(client, url, params)
    except MercadoError as exc:
        LOG.debug("Preço atual indisponível para %s: %s", market_hash_name, exc)
        return 0.0, 0.0
    if not isinstance(data, dict) or not data.get("success"):
        return 0.0, 0.0
    lowest = parse_preco_steam(data.get("lowest_price", ""))
    median = parse_preco_steam(data.get("median_price", ""))
    return lowest, median


def gerar_url_listagem(appid: int, market_hash_name: str) -> str:
    """Wrapper sobre utils.url_listing para importação centralizada."""
    return url_listing(appid, market_hash_name)


async def iterar_itens_para_analise(
    client,
    appid: int,
    *,
    limite: int = 1000,
    currency: int = 986,
    pagina_tamanho: int = 10,
    rate: float = 1.5,
) -> AsyncIterator[ItemPopular]:
    """Yield cada ItemPopular coletado. Útil para pipelines."""
    for item in await listar_itens_populares(
        client,
        appid,
        limite=limite,
        currency=currency,
        pagina_tamanho=pagina_tamanho,
        rate=rate,
    ):
        yield item


def resolver_currency(moeda: str) -> int:
    """Aceita 'brl', 'usd' ou código numérico Steam."""
    m = moeda.lower().strip()
    if m in MOEDAS:
        return MOEDAS[m]
    try:
        return int(m)
    except ValueError as exc:
        raise ValueError(f"Moeda inválida: {moeda!r}") from exc
