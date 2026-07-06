# steamflip

Analisador de oportunidades de revenda no mercado Steam. Coleta os itens
mais populares por volume, baixa o histórico de preços, aplica filtros
conservadores e gera um Excel com link clicável, preço-alvo e lucro
estimado para cada item que passou em todos os critérios.

Usa **login real com `pysteamauth`** (username + senha + `shared_secret`
do maFile do SDA), exatamente como os scripts de referência. O login
gera o código 2FA automaticamente — você não precisa confirmar no app
do celular a cada execução.

## Como usar

### 1. Configure suas credenciais (local, fora do Git)

```bash
cp steamflip/config.py steamflip/config_local.py
```

Edite `steamflip/config_local.py` com seu usuário, senha e caminho do
maFile (o `.gitignore` blinda esse arquivo):

```python
STEAM_USERNAME = "justnucker"
STEAM_PASSWORD = "H3tucd52!!"
MAFILE_PATH = os.path.join("maFiles", "justnucker.maFile")
```

O `config.py` no repositório tem placeholders; o `config_local.py`
sobrescreve em runtime quando existir.

### 2. Coloque o maFile na pasta correta

O `maFile` é gerado pelo **Steam Desktop Authenticator (SDA)**:

1. Instale: <https://github.com/Jessecar96/SteamDesktopAuthenticator>
2. Adicione sua conta via QR ou arquivo de login.
3. O arquivo fica em `maFiles/<account_name>.maFile` por padrão.

> O `maFile` contém credenciais 2FA. **Nunca** comite a pasta `maFiles/`.
> O `.gitignore` já blinda.

### 3. Rode o bot

```bash
python -m steamflip oportunidades --jogo dota2 cs2 --top 100
```

O bot faz login automaticamente, busca os itens, baixa o histórico de
preços, aplica os filtros e gera o Excel. Log detalhado por item:

```
14:23:11 [INFO] === Dota 2 (appid=570) ===
14:23:11 [INFO] Buscando populares appid=570 página=1 start=0
14:23:13 [INFO] Total coletado para appid=570: 30 itens
14:23:14 [INFO] [dota2] 1/30 — Chest of Endless Days | preço atual: R$ 0,03 | ✗ descartado (histórico de apenas 41d (<90d))
14:23:45 [INFO] [dota2] 2/30 — International 2025 Loading Screen | preço atual: R$ 12,40 | ✓ OPORTUNIDADE (desconto 18% vs média 30d, vol 7d=234, CV=0.21)
```

## Instalação

```bash
git clone https://github.com/zBasck/steamflip.git
cd steamflip
python -m venv .venv
source .venv/bin/activate   # Linux/macOS
# ou
.venv\Scripts\activate      # Windows

pip install -e .
```

## Comandos úteis

```bash
# Ajuda
python -m steamflip --help
python -m steamflip oportunidades --help

# Dota 2: 50 itens, taxa Steam 15%, margem alvo 10% líquido
python -m steamflip oportunidades --jogo dota2 --top 50 \
    --taxa-steam 0.15 --margem 0.10

# Vários jogos em uma execução
python -m steamflip oportunidades --jogo dota2 cs2 tf2 --top 200

# Saída em arquivo customizado
python -m steamflip oportunidades --jogo dota2 --top 100 \
    --saida relatorio_dota_2026-07-06.xlsx

# Debug com log verboso
python -m steamflip oportunidades --jogo dota2 --top 10 -v
```

## Filtros aplicados

Por padrão, um item só entra no relatório se **todos** forem satisfeitos:

| Filtro | Por quê |
|---|---|
| Histórico ≥ 90 dias | Itens novos são instáveis; preço médio ainda está formando |
| Volume 7d ≥ 20 | Exige liquidez real (você vai conseguir vender) |
| Preço atual ≤ média 30d × (1 − 12%) | Desconto real, não ruído |
| Preço atual < percentil 85 dos últimos 90d | Não estamos comprando no topo do range |
| Preço atual ≤ média 7d | Evita item em queda livre que "parece" barato |
| CV 30d ≤ 40% | Evita volatilidade extrema mascarando "desconto" |
| Preço atual ≥ percentil 5 30d × 0.95 | Evita crash |
| Preço atual ≥ R$ 0,50 (configurável) | Evita centavos sem liquidez |

Ajustáveis via flags: `--desconto-min`, `--volume-min`, `--dias-historico`,
`--estabilidade-max`, `--margem`, `--taxa-steam`, `--preco-minimo`.

## Estrutura do projeto

```
steamflip/
├── __init__.py            # carrega config_local.py se existir
├── __main__.py            # entry point (`python -m steamflip`)
├── main.py                # CLI
├── main_pipeline.py       # orquestração assíncrona
├── auth.py                # login com pysteamauth
├── mercado.py             # cliente HTTP do mercado Steam (assíncrono)
├── analise.py             # filtros e cálculo de preço-alvo
├── relatorio.py           # geração do Excel
├── config.py              # template (placeholders)
├── config_local.py        # (NÃO COMITADO) credenciais reais
└── utils.py               # parsers, retry, logging
tests/
└── test_*.py
```

## Segurança

- O `.maFile` contém credenciais 2FA (`shared_secret` + `identity_secret`).
  **Nunca** comite a pasta `maFiles/` nem o `config_local.py`. O `.gitignore`
  já blinda ambos.
- Logs do bot **nunca** imprimem `shared_secret`, `identity_secret`,
  tokens ou senha. Apenas o `account_name`.
- Use `chmod 600 maFiles/*.maFile` no Linux/macOS.
- A automação de leitura do mercado é tolerada pela Valve. A automação
  de **compra/venda** viola os Termos de Serviço e pode levar a ban da
  conta. Este bot só lê — você decide o que comprar/vender manualmente.

## Licença

Uso pessoal. Sem garantias. Você é responsável por usar dentro dos
Termos de Serviço da Steam.
