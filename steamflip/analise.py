"""Lógica de análise: aplica os filtros e calcula preço-alvo / lucro.

A ideia central é: receber o DataFrame de histórico + preço atual, e devolver
um dict com a decisão (comprar ou não), indicadores e o preço-alvo sugerido.
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any

import numpy as np
import pandas as pd

from .config import Criterios

LOG = logging.getLogger("steamflip")


@dataclass
class ResultadoAnalise:
    item: str
    appid: int
    comprar: bool
    motivo: str
    preco_atual: float
    media_30d: float
    mediana_30d: float
    min_30d: float
    max_30d: float
    min_90d: float
    max_90d: float
    percentil_85_90d: float
    percentil_5_30d: float
    media_7d: float
    volume_7d: int
    coef_variacao_30d: float
    dias_historico: int
    desconto_pct: float
    preco_alvo: float
    lucro_estimado: float
    lucro_pct: float
    extras: dict[str, Any] = field(default_factory=dict)

    def como_linha(self) -> dict[str, Any]:
        """Converte para um dict plano (uma linha do Excel)."""
        d = asdict(self)
        return d


def _janela(df: pd.DataFrame, dias: int, agora: datetime) -> pd.DataFrame:
    """Filtra o histórico para os últimos `dias` dias a partir de `agora`."""
    inicio = agora - pd.Timedelta(days=dias)
    return df[df["timestamp"] >= inicio]


def analisar_item(
    item: str,
    appid: int,
    df: pd.DataFrame,
    preco_atual: float,
    criterios: Criterios,
    *,
    agora: datetime | None = None,
) -> ResultadoAnalise:
    """Decide se `item` é uma oportunidade, dados seu histórico e preço atual.

    Critérios aplicados (todos devem passar):
      1. dias_historico >= dias_historico_min
      2. volume_7d >= volume_7d_min
      3. preco_atual <= media_30d * (1 - desconto_min)
      4. preco_atual <= percentil_85_90d * percentil_max (interpretado como
         "abaixo do percentil 85 do range 90d")
      5. preco_atual <= media_7d  (tendência de curto prazo não é de queda)
      6. coef_variacao_30d <= estabilidade_cv_max
      7. preco_atual >= percentil_5_30d  (o desconto não é ilusório)
      8. preco_atual >= preco_minimo
    """
    agora = agora or datetime.now()
    vazio = ResultadoAnalise(
        item=item,
        appid=appid,
        comprar=False,
        motivo="dados insuficientes",
        preco_atual=preco_atual,
        media_30d=0.0,
        mediana_30d=0.0,
        min_30d=0.0,
        max_30d=0.0,
        min_90d=0.0,
        max_90d=0.0,
        percentil_85_90d=0.0,
        percentil_5_30d=0.0,
        media_7d=0.0,
        volume_7d=0,
        coef_variacao_30d=0.0,
        dias_historico=0,
        desconto_pct=0.0,
        preco_alvo=0.0,
        lucro_estimado=0.0,
        lucro_pct=0.0,
    )

    if df.empty or preco_atual <= 0:
        vazio.motivo = "sem histórico ou preço atual indisponível"
        return vazio

    dias_hist = int((agora - df["timestamp"].min()).days)
    df_30 = _janela(df, 30, agora)
    df_7 = _janela(df, criterios.tendencia_janela, agora)
    df_90 = _janela(df, 90, agora)

    media_30d = float(df_30["preco"].mean()) if not df_30.empty else 0.0
    mediana_30d = float(df_30["preco"].median()) if not df_30.empty else 0.0
    min_30d = float(df_30["preco"].min()) if not df_30.empty else 0.0
    max_30d = float(df_30["preco"].max()) if not df_30.empty else 0.0
    min_90d = float(df_90["preco"].min()) if not df_90.empty else 0.0
    max_90d = float(df_90["preco"].max()) if not df_90.empty else 0.0
    p85_90d = float(np.percentile(df_90["preco"], 85)) if not df_90.empty else 0.0
    p5_30d = float(np.percentile(df_30["preco"], 5)) if not df_30.empty else 0.0
    media_7d = float(df_7["preco"].mean()) if not df_7.empty else 0.0
    volume_7d = int(df_7["volume"].sum())
    std_30d = float(df_30["preco"].std()) if not df_30.empty else 0.0
    cv_30d = (std_30d / media_30d) if media_30d > 0 else 0.0
    desconto = ((media_30d - preco_atual) / media_30d) if media_30d > 0 else 0.0

    def motivo_se(cond: bool, msg: str) -> str | None:
        return msg if not cond else None

    falhas: list[str] = []
    if dias_hist < criterios.dias_historico_min:
        falhas.append(
            f"histórico de apenas {dias_hist}d (<{criterios.dias_historico_min}d)"
        )
    if volume_7d < criterios.volume_7d_min:
        falhas.append(f"volume 7d={volume_7d} (<{criterios.volume_7d_min})")
    if media_30d <= 0 or desconto < criterios.desconto_min:
        falhas.append(
            f"desconto {desconto:.1%} (<{criterios.desconto_min:.0%})"
        )
    if p85_90d > 0 and preco_atual >= p85_90d:
        falhas.append("preço no topo do range 90d (>=percentil 85)")
    if media_7d > 0 and preco_atual > media_7d:
        falhas.append(
            f"tendência de queda: preço atual > média {criterios.tendencia_janela}d"
        )
    if cv_30d > criterios.estabilidade_cv_max:
        falhas.append(f"volatilidade alta: CV={cv_30d:.2f}")
    if (
        criterios.exigir_preco_acima_p5_30d
        and p5_30d > 0
        and preco_atual < p5_30d * 0.95
    ):
        falhas.append("preço muito abaixo do range recente (possível crash)")
    if preco_atual < criterios.preco_minimo:
        falhas.append(
            f"preço abaixo do mínimo R${criterios.preco_minimo:.2f}"
        )

    # Preço-alvo: queremos margem_alvo **líquida** após a taxa Steam.
    # Se vendemos por S, recebemos S * (1 - taxa). Para líquido L:
    # L = compra * (1 + margem_alvo) => S = L / (1 - taxa)
    # S = compra * (1 + margem_alvo) / (1 - taxa)
    preco_alvo = round(
        preco_atual * (1 + criterios.margem_alvo) / (1 - criterios.taxa_steam),
        2,
    )
    lucro = round(preco_alvo * (1 - criterios.taxa_steam) - preco_atual, 2)
    lucro_pct = round(lucro / preco_atual, 4) if preco_atual > 0 else 0.0

    if falhas:
        return ResultadoAnalise(
            item=item,
            appid=appid,
            comprar=False,
            motivo="; ".join(falhas),
            preco_atual=preco_atual,
            media_30d=media_30d,
            mediana_30d=mediana_30d,
            min_30d=min_30d,
            max_30d=max_30d,
            min_90d=min_90d,
            max_90d=max_90d,
            percentil_85_90d=p85_90d,
            percentil_5_30d=p5_30d,
            media_7d=media_7d,
            volume_7d=volume_7d,
            coef_variacao_30d=cv_30d,
            dias_historico=dias_hist,
            desconto_pct=desconto,
            preco_alvo=preco_alvo,
            lucro_estimado=lucro,
            lucro_pct=lucro_pct,
        )

    return ResultadoAnalise(
        item=item,
        appid=appid,
        comprar=True,
        motivo="todos os critérios atendidos",
        preco_atual=preco_atual,
        media_30d=media_30d,
        mediana_30d=mediana_30d,
        min_30d=min_30d,
        max_30d=max_30d,
        min_90d=min_90d,
        max_90d=max_90d,
        percentil_85_90d=p85_90d,
        percentil_5_30d=p5_30d,
        media_7d=media_7d,
        volume_7d=volume_7d,
        coef_variacao_30d=cv_30d,
        dias_historico=dias_hist,
        desconto_pct=desconto,
        preco_alvo=preco_alvo,
        lucro_estimado=lucro,
        lucro_pct=lucro_pct,
    )
