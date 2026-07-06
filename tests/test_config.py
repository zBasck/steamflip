"""Testes de configuração e validação."""

from __future__ import annotations

import unittest

from steamflip.config import Criterios, Execucao


class TestExecucao(unittest.TestCase):
    def test_valida_ok(self) -> None:
        e = Execucao(jogos=["dota2"], top=100, moeda="brl")
        e.validar()  # não deve levantar

    def test_sem_jogo_falha(self) -> None:
        e = Execucao(jogos=[], top=100, moeda="brl")
        with self.assertRaisesRegex(ValueError, "ao menos um jogo"):
            e.validar()

    def test_jogo_invalido_falha(self) -> None:
        e = Execucao(jogos=["fortnite"], top=100, moeda="brl")
        with self.assertRaisesRegex(ValueError, "Jogo desconhecido"):
            e.validar()

    def test_moeda_invalida_falha(self) -> None:
        e = Execucao(jogos=["dota2"], top=100, moeda="xyz")
        with self.assertRaisesRegex(ValueError, "Moeda desconhecida"):
            e.validar()

    def test_desconto_invalido_falha(self) -> None:
        e = Execucao(
            jogos=["dota2"],
            top=100,
            moeda="brl",
            criterios=Criterios(desconto_min=1.5),
        )
        with self.assertRaisesRegex(ValueError, "desconto-min"):
            e.validar()

    def test_margem_invalida_falha(self) -> None:
        e = Execucao(
            jogos=["dota2"],
            top=100,
            moeda="brl",
            criterios=Criterios(margem_alvo=0.0),
        )
        with self.assertRaisesRegex(ValueError, "margem"):
            e.validar()


if __name__ == "__main__":
    unittest.main()
