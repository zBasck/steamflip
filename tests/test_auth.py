"""Testes para o módulo de autenticação (pysteamauth)."""

from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from steamflip.auth import AuthError, _ler_shared_secret, fazer_login


class TestLerSharedSecret(unittest.TestCase):
    def test_ler_mafile_valido(self):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".maFile", delete=False, encoding="utf-8"
        ) as f:
            json.dump({"shared_secret": "abc123"}, f)
            caminho = f.name
        try:
            self.assertEqual(_ler_shared_secret(caminho), "abc123")
        finally:
            Path(caminho).unlink()

    def test_erro_se_arquivo_nao_existe(self):
        with self.assertRaises(AuthError) as ctx:
            _ler_shared_secret("/caminho/inexistente.maFile")
        self.assertIn("não encontrado", str(ctx.exception))

    def test_erro_se_json_invalido(self):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".maFile", delete=False, encoding="utf-8"
        ) as f:
            f.write("{json corrompido")
            caminho = f.name
        try:
            with self.assertRaises(AuthError) as ctx:
                _ler_shared_secret(caminho)
            self.assertIn("JSON corrompido", str(ctx.exception))
        finally:
            Path(caminho).unlink()

    def test_erro_se_sem_shared_secret(self):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".maFile", delete=False, encoding="utf-8"
        ) as f:
            json.dump({"account_name": "x"}, f)
            caminho = f.name
        try:
            with self.assertRaises(AuthError) as ctx:
                _ler_shared_secret(caminho)
            self.assertIn("shared_secret", str(ctx.exception))
        finally:
            Path(caminho).unlink()


class TestFazerLogin(unittest.TestCase):
    def _criar_mafile_tmp(self) -> str:
        f = tempfile.NamedTemporaryFile(
            mode="w", suffix=".maFile", delete=False, encoding="utf-8"
        )
        json.dump({"shared_secret": "fake_secret"}, f)
        f.close()
        return f.name

    def _run(self, coro):
        return asyncio.run(coro)

    def test_login_sucesso(self):
        caminho = self._criar_mafile_tmp()
        try:
            mock_client = MagicMock()
            mock_client.login_to_steam = AsyncMock()

            with patch("steamflip.auth.Steam", return_value=mock_client) as steam_cls:
                client = self._run(
                    fazer_login(
                        username="user", password="pass", mafile_path=caminho
                    )
                )

            steam_cls.assert_called_once_with(
                login="user", password="pass", shared_secret="fake_secret"
            )
            mock_client.login_to_steam.assert_awaited_once()
            self.assertIs(client, mock_client)
        finally:
            Path(caminho).unlink()

    def test_login_falha_steam_error(self):
        from pysteamauth.errors import SteamError

        caminho = self._criar_mafile_tmp()
        try:
            mock_client = MagicMock()
            mock_client.login_to_steam = AsyncMock(
                side_effect=SteamError(5, "senha errada")
            )

            with patch("steamflip.auth.Steam", return_value=mock_client):
                with self.assertRaises(AuthError) as ctx:
                    self._run(
                        fazer_login(
                            username="user",
                            password="wrong",
                            mafile_path=caminho,
                        )
                    )
            self.assertIn("senha errada", str(ctx.exception))
        finally:
            Path(caminho).unlink()

    def test_login_falha_generica(self):
        caminho = self._criar_mafile_tmp()
        try:
            mock_client = MagicMock()
            mock_client.login_to_steam = AsyncMock(
                side_effect=RuntimeError("falha inesperada")
            )

            with patch("steamflip.auth.Steam", return_value=mock_client):
                with self.assertRaises(AuthError) as ctx:
                    self._run(
                        fazer_login(
                            username="user",
                            password="pass",
                            mafile_path=caminho,
                        )
                    )
            self.assertIn("inesperada", str(ctx.exception))
        finally:
            Path(caminho).unlink()


if __name__ == "__main__":
    unittest.main()
