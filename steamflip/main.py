"""CLI: `python -m steamflip oportunidades --jogo dota2 cs2`."""

from __future__ import annotations

import argparse
import logging
import sys
from typing import Iterable

from . import __version__
from .analise import analisar_item
from .config import Criterios, Execucao, JOGOS
from .main_pipeline import executar_pipeline
from .utils import configurar_logging

LOG = logging.getLogger("steamflip")


def construir_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="steamflip",
        description=(
            "Analisador de oportunidades de revenda no mercado Steam. "
            "Gera um Excel com link e preço-alvo por item. Use --mafile "
            "para acesso autenticado (necessário para histórico de preços)."
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
        default=100,
        help="Tamanho da página na busca pública (10-100).",
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
    p_op.add_argument(
        "--mafile",
        default=None,
        help=(
            "Caminho para um .maFile do SDA. Habilita o acesso autenticado ao "
            "mercado (necessário para /pricehistory/ e /priceoverview/). "
            "Se não informado, o bot roda sem login e esses endpoints podem "
            "retornar HTTP 400."
        ),
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
        mafile_path=args.mafile,
    )


def cli(argv: list[str] | None = None) -> int:
    parser = construir_parser()
    args = parser.parse_args(argv)
    configurar_logging(verbose=getattr(args, "verbose", False))

    if args.comando == "oportunidades":
        try:
            execucao = _args_para_execucao(args)
            execucao.validar()
        except ValueError as exc:
            LOG.error(str(exc))
            return 2

        caminho = executar_pipeline(execucao)
        LOG.info("Pronto. Arquivo: %s", caminho)
        return 0

    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(cli())
