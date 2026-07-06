"""Pipeline de execução: coleta -> análise -> geração do Excel.

Separado de main.py para manter main.py focado em parsing de CLI.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

from .analise import ResultadoAnalise, analisar_item
from .config import Execucao, JOGOS
from .mafile import (
    MaFile,
    MaFileError,
    carregar_mafile,
    montar_cookies,
    session_expirada,
)
from .mercado import (
    MercadoError,
    listar_itens_populares,
    obter_historico,
    obter_preco_atual,
    resolver_currency,
)
from .relatorio import AbaRelatorio, gerar_excel
from .utils import criar_sessao, rate_limit

LOG = logging.getLogger("steamflip")


def _processar_item(
    sessao,
    appid: int,
    hash_name: str,
    preco_atual_hint: float,
    moeda: int,
    execucao: Execucao,
) -> tuple[pd.DataFrame, float]:
    """Coleta histórico e preço atual. Retorna (df, preco_atual)."""
    df = obter_historico(
        sessao,
        appid,
        hash_name,
        currency=moeda,
        rate=execucao.rate_limit_segundos,
    )
    # preço atual: prefere o lowest da priceoverview, mas se já veio no
    # resultado de populares com valor, usa como fallback.
    preco_lowest, _ = obter_preco_atual(
        sessao,
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


def _carregar_sessao(execucao: Execucao) -> tuple[object, MaFile | None]:
    """Cria a sessão HTTP, autenticada se houver maFile."""
    mafile: MaFile | None = None
    cookies: dict[str, str] | None = None

    if execucao.mafile_path:
        try:
            mafile = carregar_mafile(execucao.mafile_path)
        except MaFileError as exc:
            raise MercadoError(f"Falha ao carregar maFile: {exc}") from exc

        if session_expirada(mafile):
            raise MercadoError(
                f"Sessão Steam para '{mafile.account_name}' está expirada ou "
                f"inválida. Abra o SDA, clique 'Login Again' na conta, salve o "
                f"maFile e rode o bot de novo."
            )

        cookies = montar_cookies(mafile)
        sessao = criar_sessao(cookies=cookies)
        LOG.info(
            "✓ maFile carregado: %s (SteamID %s) — modo autenticado.",
            mafile.account_name,
            mafile.steam_id_mascarado(),
        )
    else:
        sessao = criar_sessao()
        LOG.warning(
            "Rodando SEM login (--mafile não informado). "
            "/pricehistory/ e /priceoverview/ podem retornar HTTP 400."
        )

    return sessao, mafile


def executar_pipeline(execucao: Execucao) -> Path:
    """Roda o pipeline completo e devolve o caminho do Excel gerado."""
    sessao, _mafile = _carregar_sessao(execucao)
    currency = resolver_currency(execucao.moeda)
    abas: list[AbaRelatorio] = []

    for jogo in execucao.jogos:
        info = JOGOS[jogo]
        appid = info["appid"]
        LOG.info("=== %s (appid=%s) ===", info["nome"], appid)

        try:
            populares = listar_itens_populares(
                sessao,
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
                df, preco = _processar_item(
                    sessao,
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
