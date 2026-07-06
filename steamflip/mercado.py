"""Cliente HTTP para os endpoints públicos do mercado Steam.

Não usa autenticação. Cada função retorna dados normalizados ou levanta
MercadoError em caso de falha.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Iterator

import pandas as pd
import requests

from .config import MOEDAS
from .utils import (
    criar_sessao,
    parse_preco_steam,
    parse_timestamp_steam,
    rate_limit,
    url_listing,
)

LOG = logging.getLogger("steamflip")

BASE_URL = "https://steamcommunity.com/market"

# URL alternativa de search (algumas instâncias CDN retornam HTML).
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


def _get_json(
    sessao: requests.Session,
    url: str,
    params: dict,
    timeout: float = 30.0,
) -> dict | list:
    """Faz GET e devolve o JSON decodificado. Levanta MercadoError se a
    resposta não for JSON válido."""
    try:
        resp = sessao.get(url, params=params, timeout=timeout)
    except requests.RequestException as exc:
        raise MercadoError(f"Falha HTTP em {url}: {exc}") from exc

    if resp.status_code != 200:
        raise MercadoError(
            f"Status {resp.status_code} em {url} (params={params})"
        )

    texto = resp.text
    if not texto:
        raise MercadoError(f"Resposta vazia em {url}")

    # Às vezes o endpoint devolve HTML de erro (rate limit, manutenção).
    head = texto.lstrip()[:200].lower()
    if head.startswith("<!doctype") or head.startswith("<html"):
        raise MercadoError(
            f"Resposta HTML em {url} (provável rate limit). "
            f"Status {resp.status_code}."
        )

    try:
        return json.loads(texto)
    except json.JSONDecodeError as exc:
        raise MercadoError(f"JSON inválido em {url}: {exc}") from exc




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
    """Devolve os parâmetros de categoria aceitos para o appid informado.

    Para CS2 (730), inclui os filtros de categoria que o mercado usa para
    skins/cases/stickers. Para qualquer outro appid, devolve {} (a Steam
    rejeita esses parâmetros com HTTP 400).
    """
    if appid == 730:
        return {chave: "" for chave in _CATEGORIAS_CS2}
    return {}


def listar_itens_populares(
    sessao: requests.Session,
    appid: int,
    *,
    limite: int = 1000,
    currency: int = 986,
    pagina_tamanho: int = 10,
    rate: float = 1.5,
) -> list[ItemPopular]:
    """Lista os itens mais populares de um app por volume/quantidade de
    listagens ativas (proxy de popularidade). Faz paginação até atingir
    `limite` ou não haver mais resultados.

    Observação: o endpoint público do mercado Steam trava ``pagesize`` em
    10 quando não há cookie de sessão autenticado, ignorando o valor de
    ``count`` enviado. Por isso o default aqui é 10 e o avanço de página
    é de 10 em 10. O parâmetro ``pagina_tamanho`` é mantido por
    compatibilidade, mas é forçado para o mínimo entre o valor pedido e
    10 — o que garante que ``start`` sempre avance corretamente entre
    páginas.
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
        rate_limit(rate)
        data = _get_json(sessao, SEARCH_URL, params)

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

        # Critério principal: a Steam devolveu uma página incompleta
        # (não há mais itens únicos além desse ponto). Isso protege contra
        # total_count inflado (ex.: CS2 reporta 34k+ listagens somadas).
        if len(resultados) < pagina_tamanho:
            break

        # Salvaguarda: se total_count for menor do que já percorremos, parar.
        total = int(data.get("total_count", 0)) if isinstance(data, dict) else 0
        if total and start + pagina_tamanho >= total:
            break

        start += pagina_tamanho

    LOG.info("Total coletado para appid=%s: %d itens", appid, len(itens))
    return itens


def obter_historico(
    sessao: requests.Session,
    appid: int,
    market_hash_name: str,
    *,
    currency: int = 986,
    rate: float = 1.0,
) -> pd.DataFrame:
    """Baixa o histórico de preços de um item.

    Retorna DataFrame com colunas: timestamp (datetime), preco (float),
    volume (int). Vazio em caso de erro ou item sem histórico.
    """
    params = {
        "appid": appid,
        "market_hash_name": market_hash_name,
        "currency": currency,
    }
    url = f"{BASE_URL}/pricehistory/"
    try:
        rate_limit(rate)
        data = _get_json(sessao, url, params)
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


def obter_preco_atual(
    sessao: requests.Session,
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
        rate_limit(rate)
        data = _get_json(sessao, url, params)
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


def iterar_itens_para_analise(
    sessao: requests.Session,
    appid: int,
    *,
    limite: int = 1000,
    currency: int = 986,
    pagina_tamanho: int = 100,
    rate: float = 1.5,
) -> Iterator[ItemPopular]:
    """Yield cada ItemPopular coletado. Útil para pipelines."""
    for item in listar_itens_populares(
        sessao,
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
