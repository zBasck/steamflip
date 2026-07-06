"""Testes de utilitários."""

from __future__ import annotations

import unittest

from steamflip.utils import (
    com_retry,
    criar_sessao,
    em_partes,
    parse_preco_steam,
    slugify_appid,
    url_listing,
)


class TestUtils(unittest.TestCase):
    def test_parse_preco_brl(self) -> None:
        self.assertEqual(parse_preco_steam("R$ 12,34"), 12.34)
        self.assertEqual(parse_preco_steam("R$ 1.234,56"), 1234.56)
        self.assertEqual(parse_preco_steam("$12.34"), 12.34)
        self.assertEqual(parse_preco_steam("--"), 0.0)
        self.assertEqual(parse_preco_steam(""), 0.0)
        self.assertEqual(parse_preco_steam(None), 0.0)

    def test_slugify_appid(self) -> None:
        self.assertEqual(slugify_appid("dota2"), 570)
        self.assertEqual(slugify_appid("CS2"), 730)
        with self.assertRaises(ValueError):
            slugify_appid("fortnite")

    def test_url_listing(self) -> None:
        url = url_listing(730, "AWP | Asiimov (Field-Tested)")
        self.assertTrue(url.startswith("https://steamcommunity.com/market/listings/730/"))
        self.assertIn("AWP", url)

    def test_em_partes(self) -> None:
        partes = list(em_partes(range(7), tamanho=3))
        self.assertEqual(partes, [[0, 1, 2], [3, 4, 5], [6]])

    def test_com_retry_sucesso(self) -> None:
        contador = {"n": 0}

        def f():
            contador["n"] += 1
            return 42

        self.assertEqual(com_retry(f, tentativas=3), 42)
        self.assertEqual(contador["n"], 1)

    def test_com_retry_erro(self) -> None:
        contador = {"n": 0}

        def f():
            contador["n"] += 1
            raise RuntimeError("boom")

        with self.assertRaises(RuntimeError):
            com_retry(f, tentativas=2, espera=0.0)
        self.assertEqual(contador["n"], 2)

    def test_criar_sessao(self) -> None:
        s = criar_sessao()
        self.assertIn("User-Agent", s.headers)

    def test_criar_sessao_com_cookies(self) -> None:
        cookies = {"steamLoginSecure": "123%7C%7Cabc", "sessionid": "deadbeef"}
        s = criar_sessao(cookies=cookies)
        # Cookies são aplicados a ambos os domínios Steam.
        comunidade = s.cookies.get("steamLoginSecure", domain="steamcommunity.com")
        store = s.cookies.get("steamLoginSecure", domain="store.steampowered.com")
        self.assertEqual(comunidade, "123%7C%7Cabc")
        self.assertEqual(store, "123%7C%7Cabc")
        self.assertEqual(
            s.cookies.get("sessionid", domain="steamcommunity.com"), "deadbeef"
        )


if __name__ == "__main__":
    unittest.main()
