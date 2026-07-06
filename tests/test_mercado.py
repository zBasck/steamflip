"""Testes para a busca de itens populares (categoria + paginação)."""

from __future__ import annotations

import json
import unittest
from unittest.mock import MagicMock, patch

from steamflip.mercado import (
    ItemPopular,
    MercadoError,
    _categorias_para_appid,
    listar_itens_populares,
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


class TestListarItensPopulares(unittest.TestCase):
    def _sessao_mock(self, paginas: list[dict]) -> MagicMock:
        """Sessão mock que devolve cada página em sequência."""
        sessao = MagicMock()
        responses = []

        class FakeResp:
            def __init__(self, data: dict):
                self._data = data
                self.status_code = 200
                self.text = json.dumps(data)

            def json(self):
                return self._data

        for pagina in paginas:
            responses.append(FakeResp(pagina))

        sessao.get.side_effect = responses
        return sessao

    def _patch_rate_limit(self):
        return patch("steamflip.mercado.rate_limit", lambda *a, **kw: None)

    def test_dota2_nao_envia_categorias_cs2(self):
        """Para appid=570 os parâmetros category_730_* não devem ser enviados."""
        with self._patch_rate_limit():
            sessao = self._sessao_mock([_resposta(total_count=10, n_resultados=10)])
            listar_itens_populares(
                sessao, 570, limite=100, pagina_tamanho=10, rate=0
            )
        chamada = sessao.get.call_args
        params = chamada.kwargs.get("params") or chamada.args[1]
        self.assertEqual(params["appid"], 570)
        self.assertNotIn("category_730_ItemSet[]", params)
        self.assertNotIn("category_730_Tournament[]", params)

    def test_cs2_envia_categorias(self):
        """Para appid=730 os parâmetros category_730_* devem ser enviados."""
        with self._patch_rate_limit():
            sessao = self._sessao_mock([_resposta(total_count=10, n_resultados=10)])
            listar_itens_populares(
                sessao, 730, limite=100, pagina_tamanho=10, rate=0
            )
        chamada = sessao.get.call_args
        params = chamada.kwargs.get("params") or chamada.args[1]
        self.assertEqual(params["appid"], 730)
        self.assertIn("category_730_ItemSet[]", params)
        self.assertIn("category_730_Tournament[]", params)

    def test_pagina_incompleta_para_loop(self):
        """Página com menos itens que count deve parar o loop imediatamente."""
        # Mesmo com total_count altíssimo (simulando CS2), uma página
        # incompleta já é suficiente para encerrar a paginação.
        with self._patch_rate_limit():
            sessao = self._sessao_mock(
                [_resposta(total_count=99999, n_resultados=7)]
            )
            itens = listar_itens_populares(
                sessao, 730, limite=1000, pagina_tamanho=10, rate=0
            )
        self.assertEqual(len(itens), 7)
        self.assertEqual(sessao.get.call_count, 1)

    def test_total_count_alto_nao_causa_loop_infinito(self):
        """total_count inflado (CS2 reporta 34k+) não deve gerar paginação indefinida."""
        # Simula 3 páginas cheias e uma incompleta — total_count gigante.
        paginas = [
            _resposta(total_count=99999, n_resultados=10),
            _resposta(total_count=99999, n_resultados=10),
            _resposta(total_count=99999, n_resultados=10),
            _resposta(total_count=99999, n_resultados=4),  # última incompleta
        ]
        with self._patch_rate_limit():
            sessao = self._sessao_mock(paginas)
            itens = listar_itens_populares(
                sessao, 730, limite=1000, pagina_tamanho=10, rate=0
            )
        # 3 páginas * 10 + 1 página * 4 = 34
        self.assertEqual(len(itens), 34)
        # Garantia principal: paginação parou, não iterou até o total_count.
        self.assertLessEqual(sessao.get.call_count, 4)

    def test_limite_respeitado(self):
        """Respeita o limite máximo de itens mesmo se a página vier completa."""
        # O mercado público trava em 10 sem login, então 5 páginas de 10
        # cobrem o limite pedido de 50.
        paginas = [_resposta(total_count=500, n_resultados=10) for _ in range(5)]
        with self._patch_rate_limit():
            sessao = self._sessao_mock(paginas)
            itens = listar_itens_populares(
                sessao, 730, limite=50, pagina_tamanho=10, rate=0
            )
        self.assertEqual(len(itens), 50)

    def test_resposta_vazia_encerra(self):
        """Lista vazia na resposta deve parar o loop sem erro."""
        with self._patch_rate_limit():
            sessao = self._sessao_mock(
                [_resposta(total_count=10, n_resultados=0)]
            )
            itens = listar_itens_populares(
                sessao, 730, limite=100, pagina_tamanho=10, rate=0
            )
        self.assertEqual(len(itens), 0)
        self.assertEqual(sessao.get.call_count, 1)

    def test_pagina_tamanho_forcado_para_max_10(self):
        """A Steam trava pagesize=10 sem login; o cliente força o clamp."""
        # 2 páginas de 10 são suficientes para validar o clamp.
        paginas = [
            _resposta(total_count=20, n_resultados=10),
            _resposta(total_count=20, n_resultados=5),  # última, incompleta
        ]
        with self._patch_rate_limit():
            sessao = self._sessao_mock(paginas)
            listar_itens_populares(
                sessao, 730, limite=100, pagina_tamanho=100, rate=0
            )
        # Cada chamada deve ter count <= 10, mesmo o caller pedindo 100.
        for c in sessao.get.call_args_list:
            params = c.kwargs.get("params") or c.args[1]
            self.assertLessEqual(int(params["count"]), 10)

    def test_paginacao_avanca_de_10_em_10(self):
        """Steam retorna 10 por página; o start precisa avançar de 10 em 10."""
        paginas = [
            _resposta(total_count=99999, n_resultados=10),
            _resposta(total_count=99999, n_resultados=10),
            _resposta(total_count=99999, n_resultados=3),  # fim
        ]
        with self._patch_rate_limit():
            sessao = self._sessao_mock(paginas)
            listar_itens_populares(
                sessao, 730, limite=100, pagina_tamanho=10, rate=0
            )
        # 3 chamadas de GET: starts esperados 0, 10, 20.
        starts = [
            (c.kwargs.get("params") or c.args[1])["start"]
            for c in sessao.get.call_args_list
        ]
        self.assertEqual(starts, [0, 10, 20])


if __name__ == "__main__":
    unittest.main()
