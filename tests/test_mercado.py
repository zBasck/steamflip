"""Testes para a busca de itens populares (categoria + paginação) na API
assíncrona com pysteamauth.
"""

from __future__ import annotations

import asyncio
import json
import unittest
from unittest.mock import AsyncMock, patch

from steamflip.mercado import (
    _categorias_para_appid,
    listar_itens_populares,
    obter_historico,
    obter_preco_atual,
)


def _resposta(total_count: int, n_resultados: int) -> dict:
    """Monta uma resposta fake no formato da API /search/render/."""
    resultados = []
    for i in range(n_resultados):
        resultados.append(
            {
                "name": f"Item {i}",
                "hash_name": f"Item {i}",
                "sell_listings": 50,
                "sell_price_text": "R$ 1,00",
                "median_price_text": "R$ 1,10",
            }
        )
    return {"total_count": total_count, "results": resultados}


class TestCategoriasParaAppid(unittest.TestCase):
    def test_cs2_recebe_categorias(self):
        cats = _categorias_para_appid(730)
        self.assertIn("category_730_ItemSet[]", cats)
        self.assertEqual(cats["category_730_ItemSet[]"], "")

    def test_dota2_nao_recebe_categorias(self):
        cats = _categorias_para_appid(570)
        self.assertEqual(cats, {})

    def test_tf2_nao_recebe_categorias(self):
        cats = _categorias_para_appid(440)
        self.assertEqual(cats, {})


def _client_mock_com_respostas(respostas: list) -> AsyncMock:
    """Cria um cliente pysteamauth falso que devolve cada resposta em sequência."""
    client = AsyncMock()

    async def _request(url, method="GET", params=None):
        return respostas.pop(0)

    client.request.side_effect = _request
    return client


class TestListarItensPopulares(unittest.TestCase):
    def _patch_rate_limit(self):
        return patch("steamflip.mercado.rate_limit_async", AsyncMock())

    def _run(self, coro):
        return asyncio.run(coro)

    def test_dota2_nao_envia_categorias_cs2(self):
        with self._patch_rate_limit():
            client = _client_mock_com_respostas(
                [_resposta(total_count=10, n_resultados=10)]
            )
            self._run(
                listar_itens_populares(client, 570, limite=100, pagina_tamanho=10, rate=0)
            )
        chamada = client.request.call_args
        params = chamada.kwargs.get("params") or chamada.args[1]
        self.assertEqual(params["appid"], 570)
        self.assertNotIn("category_730_ItemSet[]", params)
        self.assertNotIn("category_730_Tournament[]", params)

    def test_cs2_envia_categorias(self):
        with self._patch_rate_limit():
            client = _client_mock_com_respostas(
                [_resposta(total_count=10, n_resultados=10)]
            )
            self._run(
                listar_itens_populares(client, 730, limite=100, pagina_tamanho=10, rate=0)
            )
        chamada = client.request.call_args
        params = chamada.kwargs.get("params") or chamada.args[1]
        self.assertEqual(params["appid"], 730)
        self.assertIn("category_730_ItemSet[]", params)
        self.assertIn("category_730_Tournament[]", params)

    def test_pagina_incompleta_para_loop(self):
        with self._patch_rate_limit():
            client = _client_mock_com_respostas(
                [_resposta(total_count=99999, n_resultados=7)]
            )
            itens = self._run(
                listar_itens_populares(
                    client, 730, limite=1000, pagina_tamanho=10, rate=0
                )
            )
        self.assertEqual(len(itens), 7)
        self.assertEqual(client.request.call_count, 1)

    def test_total_count_alto_nao_causa_loop_infinito(self):
        paginas = [
            _resposta(total_count=99999, n_resultados=10),
            _resposta(total_count=99999, n_resultados=10),
            _resposta(total_count=99999, n_resultados=10),
            _resposta(total_count=99999, n_resultados=4),
        ]
        with self._patch_rate_limit():
            client = _client_mock_com_respostas(paginas)
            itens = self._run(
                listar_itens_populares(
                    client, 730, limite=1000, pagina_tamanho=10, rate=0
                )
            )
        self.assertEqual(len(itens), 34)
        self.assertLessEqual(client.request.call_count, 4)

    def test_limite_respeitado(self):
        paginas = [_resposta(total_count=500, n_resultados=10) for _ in range(5)]
        with self._patch_rate_limit():
            client = _client_mock_com_respostas(paginas)
            itens = self._run(
                listar_itens_populares(
                    client, 730, limite=50, pagina_tamanho=10, rate=0
                )
            )
        self.assertEqual(len(itens), 50)

    def test_resposta_vazia_encerra(self):
        with self._patch_rate_limit():
            client = _client_mock_com_respostas(
                [_resposta(total_count=10, n_resultados=0)]
            )
            itens = self._run(
                listar_itens_populares(
                    client, 730, limite=100, pagina_tamanho=10, rate=0
                )
            )
        self.assertEqual(len(itens), 0)
        self.assertEqual(client.request.call_count, 1)

    def test_pagina_tamanho_forcado_para_max_10(self):
        paginas = [
            _resposta(total_count=20, n_resultados=10),
            _resposta(total_count=20, n_resultados=5),
        ]
        with self._patch_rate_limit():
            client = _client_mock_com_respostas(paginas)
            self._run(
                listar_itens_populares(
                    client, 730, limite=100, pagina_tamanho=100, rate=0
                )
            )
        for c in client.request.call_args_list:
            params = c.kwargs.get("params") or c.args[1]
            self.assertLessEqual(int(params["count"]), 10)

    def test_paginacao_avanca_de_10_em_10(self):
        paginas = [
            _resposta(total_count=99999, n_resultados=10),
            _resposta(total_count=99999, n_resultados=10),
            _resposta(total_count=99999, n_resultados=3),
        ]
        with self._patch_rate_limit():
            client = _client_mock_com_respostas(paginas)
            self._run(
                listar_itens_populares(
                    client, 730, limite=100, pagina_tamanho=10, rate=0
                )
            )
        starts = [
            (c.kwargs.get("params") or c.args[1])["start"]
            for c in client.request.call_args_list
        ]
        self.assertEqual(starts, [0, 10, 20])


class TestObterHistorico(unittest.TestCase):
    def _run(self, coro):
        return asyncio.run(coro)

    def test_historico_valido(self):
        client = _client_mock_com_respostas(
            [
                {
                    "success": True,
                    "prices": [
                        ["Jul 01 2026 01: +0", "1,50", "10"],
                        ["Jul 02 2026 01: +0", "1,40", "5"],
                    ],
                }
            ]
        )
        with patch("steamflip.mercado.rate_limit_async", AsyncMock()):
            df = self._run(obter_historico(client, 570, "X"))
        self.assertEqual(len(df), 2)
        self.assertAlmostEqual(df["preco"].iloc[0], 1.5)
        self.assertEqual(int(df["volume"].iloc[1]), 5)

    def test_historico_vazio_quando_success_false(self):
        client = _client_mock_com_respostas([{"success": False}])
        with patch("steamflip.mercado.rate_limit_async", AsyncMock()):
            df = self._run(obter_historico(client, 570, "X"))
        self.assertTrue(df.empty)

    def test_historico_vazio_quando_erro(self):
        client = AsyncMock()
        client.request.side_effect = RuntimeError("boom")
        with patch("steamflip.mercado.rate_limit_async", AsyncMock()):
            df = self._run(obter_historico(client, 570, "X"))
        self.assertTrue(df.empty)


class TestObterPrecoAtual(unittest.TestCase):
    def _run(self, coro):
        return asyncio.run(coro)

    def test_preco_valido(self):
        client = _client_mock_com_respostas(
            [
                {
                    "success": True,
                    "lowest_price": "R$ 1,99",
                    "median_price": "R$ 2,10",
                }
            ]
        )
        with patch("steamflip.mercado.rate_limit_async", AsyncMock()):
            lowest, median = self._run(obter_preco_atual(client, 570, "X"))
        self.assertAlmostEqual(lowest, 1.99)
        self.assertAlmostEqual(median, 2.10)

    def test_preco_vazio_quando_erro(self):
        client = AsyncMock()
        client.request.side_effect = RuntimeError("boom")
        with patch("steamflip.mercado.rate_limit_async", AsyncMock()):
            lowest, median = self._run(obter_preco_atual(client, 570, "X"))
        self.assertEqual((lowest, median), (0.0, 0.0))


if __name__ == "__main__":
    unittest.main()
