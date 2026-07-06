"""CLI: `python -m steamflip oportunidades --jogo dota2 cs2`.

Faz login com pysteamauth (username + senha + shared_secret do maFile)
e roda a pipeline autenticada.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys

from . import __version__
from .config import Criterios, Execucao, JOGOS
from .main_pipeline import executar_pipeline
from .mercado import MercadoError
from .utils import configurar_logging

LOG = logging.getLogger("steamflip")


def construir_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="steamflip",
        description=(
            "Analisador de oportunidades de revenda no mercado Steam. "
            "Faz login autenticado via pysteamauth (necessita maFile do "
            "SDA com shared_secret) para destravar /pricehistory/."
        ),
    )
    parser.add_argument(
        "--version", action="version", version=f"steamflip {__version__}"
    )

    sub = parser.add_subparsers(dest="comando", required=True)

    p_op = sub.add_parser(
        "oportunidades",
        help="Buscar oportunidades de compra e gerar Excel.",
    )
    p_op.add_argument(
        "--jogo",
        "--jogos",
        dest="jogos",
        nargs="+",
        required=True,
        choices=sorted(JOGOS),
        help="Um ou mais jogos: dota2, cs2, tf2.",
    )
    p_op.add_argument(
        "--top", type=int, default=1000, help="Quantos itens analisar por jogo."
    )
    p_op.add_argument(
        "--moeda",
        default="brl",
        help="Código da moeda: brl, usd, eur, ... ou número do currency code Steam.",
    )
    p_op.add_argument(
        "--saida", default=None, help="Caminho do arquivo .xlsx de saída."
    )
    p_op.add_argument(
        "--pagina-tamanho",
        type=int,
        default=10,
        help="Tamanho da página na busca (1-100, mercado trava em 10).",
    )
    p_op.add_argument(
        "--rate-limit",
        type=float,
        default=1.5,
        help="Delay base em segundos entre chamadas HTTP.",
    )
    p_op.add_argument(
        "--desconto-min", type=float, default=0.12, help="Desconto mínimo vs média 30d (0-1)."
    )
    p_op.add_argument(
        "--volume-min", type=int, default=20, help="Vendas mínimas nos últimos 7 dias."
    )
    p_op.add_argument(
        "--dias-historico", type=int, default=90, help="Histórico mínimo em dias."
    )
    p_op.add_argument(
        "--estabilidade-max",
        type=float,
        default=0.40,
        help="Coeficiente de variação máximo nos últimos 30d (0-1).",
    )
    p_op.add_argument(
        "--margem",
        type=float,
        default=0.08,
        help="Margem líquida alvo após taxa Steam (0-1).",
    )
    p_op.add_argument(
        "--taxa-steam",
        type=float,
        default=0.13,
        help="Taxa Steam sobre vendas (0-1).",
    )
    p_op.add_argument(
        "--preco-minimo",
        type=float,
        default=0.50,
        help="Preço mínimo em moeda local para entrar no relatório.",
    )
    p_op.add_argument(
        "--verbose", "-v", action="store_true", help="Logs detalhados."
    )
    return parser


def _args_para_execucao(args: argparse.Namespace) -> Execucao:
    return Execucao(
        jogos=[j.lower() for j in args.jogos],
        top=args.top,
        moeda=args.moeda,
        pagina_tamanho=args.pagina_tamanho,
        rate_limit_segundos=args.rate_limit,
        criterios=Criterios(
            dias_historico_min=args.dias_historico,
            volume_7d_min=args.volume_min,
            desconto_min=args.desconto_min,
            estabilidade_cv_max=args.estabilidade_max,
            margem_alvo=args.margem,
            taxa_steam=args.taxa_steam,
            preco_minimo=args.preco_minimo,
        ),
        saida=args.saida,
        verbose=args.verbose,
    )


async def _async_cli(args: argparse.Namespace) -> int:
    if args.comando == "oportunidades":
        try:
            execucao = _args_para_execucao(args)
            execucao.validar()
        except ValueError as exc:
            LOG.error(str(exc))
            return 2

        try:
            caminho = await executar_pipeline(execucao)
        except MercadoError as exc:
            LOG.error("Falha no pipeline: %s", exc)
            return 3
        LOG.info("Pronto. Arquivo: %s", caminho)
        return 0

    return 1


def cli(argv: list[str] | None = None) -> int:
    parser = construir_parser()
    args = parser.parse_args(argv)
    configurar_logging(verbose=getattr(args, "verbose", False))
    return asyncio.run(_async_cli(args))


if __name__ == "__main__":
    sys.exit(cli())
