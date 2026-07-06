"""Testes unitários da lógica de análise."""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

from steamflip.analise import analisar_item
from steamflip.config import Criterios


def _df_historico(precos, volumes=None, *, fim=None, passo_horas=24):
    """Constrói um DataFrame de histórico a partir de uma série de preços."""
    fim = fim or datetime.now()
    n = len(precos)
    timestamps = [fim - timedelta(hours=passo_horas * (n - 1 - i)) for i in range(n)]
    if volumes is None:
        volumes = [10] * n
    return pd.DataFrame(
        {
            "timestamp": pd.to_datetime(timestamps),
            "preco": precos,
            "volume": volumes,
        }
    )


class TestAnalise(unittest.TestCase):
    def setUp(self) -> None:
        self.criterios = Criterios()

    def test_item_novo_e_descartado(self) -> None:
        """Item com menos de 90 dias de histórico deve ser descartado."""
        agora = datetime(2026, 6, 1)
        precos = [10.0] * 30
        df = _df_historico(precos, fim=agora)
        r = analisar_item("X", 730, df, 9.0, self.criterios, agora=agora)
        self.assertFalse(r.comprar)
        self.assertIn("histórico", r.motivo)

    def test_item_em_alta_sobe_e_descartado_queda(self) -> None:
        """Item com média 7d abaixo do preço atual = tendência de queda."""
        agora = datetime(2026, 6, 1)
        precos_30 = [10.0] * 30
        precos_7 = [5.0] * 7
        ts = [agora - timedelta(days=37 - i) for i in range(37)]
        df = pd.DataFrame(
            {
                "timestamp": pd.to_datetime(ts),
                "preco": precos_30 + precos_7,
                "volume": [10] * 37,
            }
        )
        r = analisar_item("Y", 730, df, 7.5, self.criterios, agora=agora)
        self.assertFalse(r.comprar)
        self.assertTrue("tendência" in r.motivo or "queda" in r.motivo)

    def test_item_volatil_e_descartado(self) -> None:
        """Itens com CV > 0.40 são descartados."""
        agora = datetime(2026, 6, 1)
        np.random.seed(1)
        precos = list(np.random.normal(loc=10.0, scale=8.0, size=120))
        precos = [max(0.5, p) for p in precos]
        ts = [agora - timedelta(days=120 - i) for i in range(120)]
        df = pd.DataFrame(
            {
                "timestamp": pd.to_datetime(ts),
                "preco": precos,
                "volume": [50] * 120,
            }
        )
        r = analisar_item("Z", 730, df, 9.0, self.criterios, agora=agora)
        self.assertFalse(r.comprar)
        self.assertIn("volatilidade", r.motivo)

    def test_item_com_oportunidade_real(self) -> None:
        """Item com volatilidade moderada, volume, descontado e sem queda deve passar."""
        agora = datetime(2026, 6, 1)
        np.random.seed(2)
        # CV ~20% (realista para itens do Steam).
        precos_estaveis = list(np.random.normal(loc=10.0, scale=2.0, size=110))
        precos_estaveis = [max(1.0, p) for p in precos_estaveis]
        ts = [agora - timedelta(days=110 - i) for i in range(110)]
        df = pd.DataFrame(
            {
                "timestamp": pd.to_datetime(ts),
                "preco": precos_estaveis,
                "volume": [10] * 110,
            }
        )
        preco_atual = 8.0  # ~20% abaixo da média
        r = analisar_item("OK", 730, df, preco_atual, self.criterios, agora=agora)
        self.assertTrue(r.comprar)
        self.assertGreater(r.preco_alvo, preco_atual)
        self.assertGreater(r.lucro_estimado, 0)

    def test_preco_alvo_inclui_taxa_steam(self) -> None:
        """Verifica a fórmula: alvo = compra * (1+margem) / (1-taxa)"""
        agora = datetime(2026, 6, 1)
        precos = [10.0 + 0.01 * i for i in range(110)]
        ts = [agora - timedelta(days=110 - i) for i in range(110)]
        df = pd.DataFrame(
            {
                "timestamp": pd.to_datetime(ts),
                "preco": precos,
                "volume": [10] * 110,
            }
        )
        preco_atual = 8.0
        r = analisar_item("ALVO", 730, df, preco_atual, self.criterios, agora=agora)
        if r.comprar:
            esperado = round(8.0 * (1 + 0.08) / (1 - 0.13), 2)
            self.assertLess(abs(r.preco_alvo - esperado), 0.05)
            liquido = r.preco_alvo * (1 - 0.13) - 8.0
            self.assertLess(abs(r.lucro_estimado - round(liquido, 2)), 0.05)

    def test_volume_insuficiente_descarta(self) -> None:
        """Sem volume 7d mínimo, descartar."""
        agora = datetime(2026, 6, 1)
        precos = [10.0] * 110
        volumes = [1] * 110
        ts = [agora - timedelta(days=110 - i) for i in range(110)]
        df = pd.DataFrame(
            {
                "timestamp": pd.to_datetime(ts),
                "preco": precos,
                "volume": volumes,
            }
        )
        r = analisar_item("LOW", 730, df, 8.0, self.criterios, agora=agora)
        self.assertFalse(r.comprar)
        self.assertIn("volume", r.motivo)

    def test_preco_minimo_descarta(self) -> None:
        """Itens muito baratos são descartados para evitar centavos."""
        agora = datetime(2026, 6, 1)
        precos = [1.0] * 110
        ts = [agora - timedelta(days=110 - i) for i in range(110)]
        df = pd.DataFrame(
            {
                "timestamp": pd.to_datetime(ts),
                "preco": precos,
                "volume": [50] * 110,
            }
        )
        r = analisar_item("CHEAP", 730, df, 0.20, self.criterios, agora=agora)
        self.assertFalse(r.comprar)


if __name__ == "__main__":
    unittest.main()
