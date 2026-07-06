"""Configuração e parâmetros do projeto.

Todos os valores aqui podem ser sobrescritos via flags de CLI (ver main.py).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# Mapeamento de apelidos amigáveis -> appid Steam.
JOGOS: dict[str, dict[str, Any]] = {
    "dota2": {
        "appid": 570,
        "nome": "Dota 2",
        "url_slug": "dota-2",
    },
    "cs2": {
        "appid": 730,
        "nome": "Counter-Strike 2",
        "url_slug": "counter-strike-2",
    },
    "tf2": {
        "appid": 440,
        "nome": "Team Fortress 2",
        "url_slug": "team-fortress-2",
    },
}

# Moedas suportadas por apelido. Os códigos numéricos são os do mercado Steam.
MOEDAS: dict[str, int] = {
    "brl": 986,
    "usd": 1,
    "eur": 3,
    "gbp": 2,
    "ars": 34,
    "clp": 25,
    "mxn": 19,
}

# Símbolos usados na exibição (não impactam a precisão numérica da planilha).
SIMBOLO_MOEDA: dict[str, str] = {
    "brl": "R$",
    "usd": "$",
    "eur": "€",
    "gbp": "£",
    "ars": "AR$",
    "clp": "CLP$",
    "mxn": "MX$",
}


@dataclass
class Criterios:
    """Parâmetros da análise de oportunidade.

    Os defaults abaixo foram calibrados para serem conservadores — o objetivo
    é gerar **poucas** oportunidades, mas com boa taxa de acerto.
    """

    # Janela mínima de histórico exigido, em dias.
    dias_historico_min: int = 90
    # Vendas mínimas nos últimos 7 dias (liquidez).
    volume_7d_min: int = 20
    # Desconto mínimo em relação à média móvel de 30 dias. 0.12 = 12%.
    desconto_min: float = 0.12
    # Percentil máximo aceitável do preço atual em relação aos últimos 90d.
    # 0.85 = "o preço precisa estar abaixo dos 15% mais altos dos últimos 90d".
    percentil_max: float = 0.85
    # Coeficiente de variação máximo nos últimos 30d (desvio / média).
    estabilidade_cv_max: float = 0.40
    # Janela curta para tendência (dias) — exige preço atual <= média desta janela.
    tendencia_janela: int = 7
    # Se o preço atual for 5%+ mais alto que o percentil 5 dos últimos 30d,
    # o desconto pode ser ilusório (subiu rápido e voltou). Exigimos isso.
    exigir_preco_acima_p5_30d: bool = True
    # Margem líquida alvo (após taxa Steam). 0.08 = 8% de lucro líquido.
    margem_alvo: float = 0.08
    # Taxa Steam sobre vendas. Steam cobra ~13% no jogo base + taxa de mercado.
    taxa_steam: float = 0.13
    # Preço mínimo do item em BRL para entrar no relatório (evita centavos).
    preco_minimo: float = 0.50


@dataclass
class Execucao:
    """Estado de uma execução CLI: jogos, moeda, critérios e parâmetros HTTP."""

    jogos: list[str] = field(default_factory=list)
    top: int = 1000
    moeda: str = "brl"
    pagina_tamanho: int = 10
    rate_limit_segundos: float = 1.5
    criterios: Criterios = field(default_factory=Criterios)
    saida: str | None = None
    verbose: bool = False
    # Caminho para um .maFile SDA. Se None, roda sem login.
    mafile_path: str | None = None

    def validar(self) -> None:
        if not self.jogos:
            raise ValueError("Informe ao menos um jogo via --jogo.")
        for j in self.jogos:
            if j.lower() not in JOGOS:
                raise ValueError(
                    f"Jogo desconhecido: {j!r}. Válidos: {sorted(JOGOS)}"
                )
        if self.top <= 0:
            raise ValueError("--top deve ser positivo.")
        if self.moeda.lower() not in MOEDAS:
            raise ValueError(
                f"Moeda desconhecida: {self.moeda!r}. Válidas: {sorted(MOEDAS)}"
            )
        if not (0 < self.criterios.desconto_min < 1):
            raise ValueError("--desconto-min deve estar entre 0 e 1.")
        if not (0 < self.criterios.margem_alvo < 1):
            raise ValueError("--margem deve estar entre 0 e 1.")
        if not (0 < self.criterios.taxa_steam < 1):
            raise ValueError("--taxa-steam deve estar entre 0 e 1.")
        if not (0 < self.criterios.percentil_max < 1):
            raise ValueError("percentil_max deve estar entre 0 e 1.")
        if self.pagina_tamanho < 1 or self.pagina_tamanho > 100:
            # O mercado público trava em 10 sem cookie de login, então
            # valores > 10 não fazem diferença prática — aceitamos para
            # compatibilidade, mas o cliente força o mínimo.
            raise ValueError("--pagina-tamanho deve estar entre 1 e 100.")
        if self.mafile_path is not None:
            from pathlib import Path
            if not Path(self.mafile_path).is_file():
                raise ValueError(
                    f"maFile não encontrado: {self.mafile_path}"
                )
