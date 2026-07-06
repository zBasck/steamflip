"""Pipeline de execução assíncrona: login -> coleta -> análise -> Excel.

Usa o cliente autenticado do pysteamauth (igual os arquivos de referência)
para destravar /pricehistory/ e /priceoverview/.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

from .analise import ResultadoAnalise, analisar_item
from .auth import AuthError, fazer_login
from .config import Execucao, JOGOS
from .mercado import (
    MercadoError,
    listar_itens_populares,
    obter_historico,
    obter_preco_atual,
    resolver_currency,
)
from .relatorio import AbaRelatorio, gerar_excel
from .utils import configurar_logging

LOG = logging.getLogger("steamflip")


async def _processar_item(
    client,
    appid: int,
    hash_name: str,
    preco_atual_hint: float,
    moeda: int,
    execucao: Execucao,
) -> tuple[pd.DataFrame, float]:
    """Coleta histórico e preço atual. Retorna (df, preco_atual)."""
    df = await obter_historico(
        client,
        appid,
        hash_name,
        currency=moeda,
        rate=execucao.rate_limit_segundos,
    )
    preco_lowest, _ = await obter_preco_atual(
        client,
        appid,
        hash_name,
        currency=moeda,
        rate=execucao.rate_limit_segundos,
    )
    preco = preco_lowest or preco_atual_hint
    return df, preco


def _log_decisao_item(jogo: str, i: int, total: int, item, resultado) -> None:
    """Loga o resultado detalhado de um item (preço atual + decisão)."""
    nome = item.market_hash_name
    preco = resultado.preco_atual
    preco_str = f"R$ {preco:.2f}" if preco > 0 else "indisponível"

    if resultado.comprar:
        prefixo = "✓ OPORTUNIDADE"
        detalhe = (
            f"desconto {resultado.desconto_pct:.0%} vs média 30d, "
            f"vol 7d={resultado.volume_7d}, CV={resultado.coef_variacao_30d:.2f}"
        )
    else:
        prefixo = "✗ descartado"
        detalhe = resultado.motivo

    LOG.info(
        "[%s] %d/%d — %s | preço atual: %s | %s (%s)",
        jogo,
        i,
        total,
        nome,
        preco_str,
        prefixo,
        detalhe,
    )


async def executar_pipeline(execucao: Execucao) -> Path:
    """Roda o pipeline completo (login + coleta + análise) e devolve o
    caminho do Excel gerado."""
    try:
        client = await fazer_login()
    except AuthError as exc:
        raise MercadoError(f"Falha no login: {exc}") from exc

    currency = resolver_currency(execucao.moeda)
    abas: list[AbaRelatorio] = []

    for jogo in execucao.jogos:
        info = JOGOS[jogo]
        appid = info["appid"]
        LOG.info("=== %s (appid=%s) ===", info["nome"], appid)

        try:
            populares = await listar_itens_populares(
                client,
                appid,
                limite=execucao.top,
                currency=currency,
                pagina_tamanho=execucao.pagina_tamanho,
                rate=execucao.rate_limit_segundos,
            )
        except MercadoError as exc:
            LOG.error("Falha ao listar populares de %s: %s", jogo, exc)
            abas.append(AbaRelatorio(jogo=jogo, resultados=[]))
            continue

        resultados: list[ResultadoAnalise] = []
        total = len(populares)
        for i, item in enumerate(populares, start=1):
            try:
                df, preco = await _processar_item(
                    client,
                    appid,
                    item.market_hash_name,
                    item.preco_lowest,
                    currency,
                    execucao,
                )
            except MercadoError as exc:
                LOG.debug("Item %s pulado: %s", item.market_hash_name, exc)
                continue

            r = analisar_item(
                item.market_hash_name,
                appid,
                df,
                preco,
                execucao.criterios,
            )
            _log_decisao_item(jogo, i, total, item, r)
            if r.comprar:
                resultados.append(r)

        LOG.info(
            "[%s] oportunidades encontradas: %d de %d itens",
            jogo,
            len(resultados),
            total,
        )
        abas.append(AbaRelatorio(jogo=jogo, resultados=resultados))

    caminho = gerar_excel(abas, moeda=execucao.moeda, saida=execucao.saida)
    return caminho
