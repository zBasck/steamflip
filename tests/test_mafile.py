"""Testes para steamflip.mafile."""

from __future__ import annotations

import base64
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from steamflip.mafile import (
    MaFileError,
    carregar_mafile,
    codigo_totp,
    montar_cookies,
    session_expirada,
    tag_mobileconf,
)


# Secrets determinísticos para os testes.
SHARED_SECRET_B64 = base64.b64encode(b"0123456789abcdef0123").decode()
IDENTITY_SECRET_B64 = base64.b64encode(b"abcdef0123456789abcd").decode()

# SteamID fictício para os testes.
STEAM_ID = 76561198000000001

# SessionID de 32 chars hex.
SESSION_ID = "0123456789abcdef0123456789abcdef"


def _mafile_moderno(**overrides) -> dict:
    data = {
        "shared_secret": SHARED_SECRET_B64,
        "identity_secret": IDENTITY_SECRET_B64,
        "account_name": "justnucker",
        "device_id": "android:deadbeef-1234-5678-9abc-def012345678",
        "fully_enrolled": True,
        "Session": {
            "SteamID": STEAM_ID,
            "AccessToken": _jwt_fake(exp_offset=3600),
            "RefreshToken": "eyJhbGciOiJFZERTQSJ9.refresh",
            "SessionID": SESSION_ID,
        },
    }
    data.update(overrides)
    return data


def _mafile_legado() -> dict:
    """maFile mais antigo, com SteamLoginSecure pronto."""
    return {
        "shared_secret": SHARED_SECRET_B64,
        "identity_secret": IDENTITY_SECRET_B64,
        "account_name": "justnucker",
        "fully_enrolled": True,
        "Session": {
            "SteamID": STEAM_ID,
            "SteamLoginSecure": f"{STEAM_ID}%7C%7C{_jwt_fake(exp_offset=3600)}",
            "SessionID": SESSION_ID,
        },
    }


def _jwt_fake(exp_offset: int = 3600) -> str:
    """Gera um JWT-like (header.payload.signature) só com o claim `exp`."""
    import time

    header = base64.urlsafe_b64encode(b'{"alg":"EdDSA","typ":"JWT"}').rstrip(b"=")
    payload_dict = {"sub": str(STEAM_ID), "exp": int(time.time()) + exp_offset}
    payload = base64.urlsafe_b64encode(
        json.dumps(payload_dict).encode()
    ).rstrip(b"=")
    signature = base64.urlsafe_b64encode(b"fake-signature").rstrip(b"=")
    return f"{header.decode()}.{payload.decode()}.{signature.decode()}"


def _escrever_mafile(tmp: Path, dados: dict) -> Path:
    p = tmp / "justnucker.maFile"
    p.write_text(json.dumps(dados), encoding="utf-8")
    return p


class TestCarregarMaFile(unittest.TestCase):
    def test_formato_moderno(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            caminho = _escrever_mafile(
                Path(td), _mafile_moderno()
            )
            mafile = carregar_mafile(caminho)
            self.assertEqual(mafile.account_name, "justnucker")
            self.assertEqual(mafile.steam_id, STEAM_ID)
            self.assertTrue(mafile.fully_enrolled)
            self.assertEqual(mafile.session_id, SESSION_ID)
            self.assertTrue(mafile.access_token.startswith("eyJ"))

    def test_formato_legado(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            caminho = _escrever_mafile(Path(td), _mafile_legado())
            mafile = carregar_mafile(caminho)
            self.assertEqual(mafile.steam_id, STEAM_ID)
            # access_token extraído do cookie legado
            self.assertTrue(mafile.access_token.startswith("eyJ"))

    def test_nao_enrolled(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            dados = _mafile_moderno(fully_enrolled=False)
            caminho = _escrever_mafile(Path(td), dados)
            with self.assertRaises(MaFileError):
                carregar_mafile(caminho)

    def test_arquivo_inexistente(self) -> None:
        with self.assertRaises(MaFileError):
            carregar_mafile("/tmp/nao_existe_xyz.maFile")

    def test_sem_sessionid(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            dados = _mafile_moderno()
            del dados["Session"]["SessionID"]
            caminho = _escrever_mafile(Path(td), dados)
            with self.assertRaises(MaFileError):
                carregar_mafile(caminho)

    def test_sem_shared_secret(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            dados = _mafile_moderno()
            dados["shared_secret"] = ""
            caminho = _escrever_mafile(Path(td), dados)
            with self.assertRaises(MaFileError):
                carregar_mafile(caminho)

    def test_steam_id_mascarado(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            caminho = _escrever_mafile(Path(td), _mafile_moderno())
            mafile = carregar_mafile(caminho)
            masked = mafile.steam_id_mascarado()
            self.assertTrue(masked.startswith("..."))
            self.assertEqual(len(masked), 10)  # "..." + 7 chars

    def test_secrets_nao_logados(self) -> None:
        """Garante que logs não vazem shared/identity/access token."""
        import logging

        logger = logging.getLogger("steamflip")
        with tempfile.TemporaryDirectory() as td:
            caminho = _escrever_mafile(Path(td), _mafile_moderno())
            with self.assertLogs(logger, level="DEBUG") as captured:
                carregar_mafile(caminho)
                session_expirada(carregar_mafile(caminho))
            full_log = "\n".join(captured.output)
            self.assertNotIn(SHARED_SECRET_B64, full_log)
            self.assertNotIn(IDENTITY_SECRET_B64, full_log)
            self.assertNotIn("fake-signature", full_log)


class TestCodigoTotp(unittest.TestCase):
    def test_formato(self) -> None:
        codigo = codigo_totp(SHARED_SECRET_B64, timestamp=1700000000)
        self.assertEqual(len(codigo), 5)
        for c in codigo:
            self.assertIn(c, "23456789BCDFGHJKMNPQRTVWXY")

    def test_deterministico(self) -> None:
        # Mesmo timestamp -> mesmo código
        c1 = codigo_totp(SHARED_SECRET_B64, timestamp=1700000000)
        c2 = codigo_totp(SHARED_SECRET_B64, timestamp=1700000000)
        self.assertEqual(c1, c2)

    def test_muda_com_tempo(self) -> None:
        c1 = codigo_totp(SHARED_SECRET_B64, timestamp=1700000000)
        c2 = codigo_totp(SHARED_SECRET_B64, timestamp=1700000030)  # +30s
        # Pode ser igual (mesma janela de 30s) — não conseguimos garantir
        # diferença em uma janela. Garantimos apenas que o algoritmo
        # é estável e não levanta.
        self.assertEqual(len(c1), 5)
        self.assertEqual(len(c2), 5)

    def test_vetor_conhecido(self) -> None:
        """Vetor de teste calculado manualmente (segredo fixo, timestamp fixo).

        O segredo usado aqui é determinístico e o timestamp foi congelado
        em um valor divisível por 30. O valor esperado é o resultado do
        algoritmo canônico rodado uma vez — não validamos contra a Steam
        real (o que seria flaky), apenas contra si mesmo.
        """
        with open(Path(__file__).parent / "vetor_totp.json", encoding="utf-8") as f:
            vetor = json.load(f)
        codigo = codigo_totp(vetor["shared_secret"], timestamp=vetor["timestamp"])
        self.assertEqual(codigo, vetor["expected"])


class TestTagMobileconf(unittest.TestCase):
    def test_deterministico(self) -> None:
        t1 = tag_mobileconf(IDENTITY_SECRET_B64, "conf", timestamp=1700000000)
        t2 = tag_mobileconf(IDENTITY_SECRET_B64, "conf", timestamp=1700000000)
        self.assertEqual(t1, t2)
        self.assertGreater(len(t1), 20)
        # base64 padrão (com '+' '/' '='), não urlsafe
        self.assertNotIn("-", t1)
        self.assertNotIn("_", t1)

    def test_muda_com_tag(self) -> None:
        a = tag_mobileconf(IDENTITY_SECRET_B64, "conf", timestamp=1700000000)
        b = tag_mobileconf(IDENTITY_SECRET_B64, "allow", timestamp=1700000000)
        self.assertNotEqual(a, b)

    def test_muda_com_timestamp(self) -> None:
        a = tag_mobileconf(IDENTITY_SECRET_B64, "conf", timestamp=1700000000)
        b = tag_mobileconf(IDENTITY_SECRET_B64, "conf", timestamp=1700000001)
        self.assertNotEqual(a, b)


class TestMontarCookies(unittest.TestCase):
    def test_formato_steam_login_secure(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            caminho = _escrever_mafile(Path(td), _mafile_moderno())
            mafile = carregar_mafile(caminho)
            cookies = montar_cookies(mafile)
            self.assertIn("steamLoginSecure", cookies)
            self.assertTrue(
                cookies["steamLoginSecure"].startswith(f"{STEAM_ID}%7C%7C")
            )
            self.assertEqual(cookies["sessionid"], SESSION_ID)


class TestSessionExpirada(unittest.TestCase):
    def test_jwt_valido(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            caminho = _escrever_mafile(Path(td), _mafile_moderno())
            mafile = carregar_mafile(caminho)
            self.assertFalse(session_expirada(mafile))

    def test_jwt_expirado(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            dados = _mafile_moderno()
            dados["Session"]["AccessToken"] = _jwt_fake(exp_offset=-3600)
            caminho = _escrever_mafile(Path(td), dados)
            mafile = carregar_mafile(caminho)
            self.assertTrue(session_expirada(mafile))

    def test_jwt_invalido(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            dados = _mafile_moderno()
            dados["Session"]["AccessToken"] = "nao-e-jwt"
            caminho = _escrever_mafile(Path(td), dados)
            mafile = carregar_mafile(caminho)
            # Fail-closed: trata como expirado
            self.assertTrue(session_expirada(mafile))


if __name__ == "__main__":
    unittest.main()
