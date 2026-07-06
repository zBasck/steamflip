# steamflip

Analisador de oportunidades de revenda no mercado Steam. Coleta os itens
mais populares por volume, baixa o histórico de preços, aplica filtros
conservadores e gera um Excel com link clicável, preço-alvo e lucro
estimado para cada item que passou em todos os critérios.

## Modos de uso

### Sem login (limitado)

```bash
python -m steamflip oportunidades --jogo dota2 cs2 tf2 --top 100
```

- Funciona com endpoints públicos do mercado.
- **Limitação:** `/pricehistory/` e `/priceoverview/` retornam HTTP 400
  sem cookie de sessão. Você verá itens sendo analisados com "0
  oportunidades" mesmo com `--top` alto, porque o histórico vem vazio.
- Útil para testes rápidos ou se você só quer listar itens.

### Com login (recomendado)

```bash
python -m steamflip oportunidades --jogo dota2 cs2 \
    --mafile maFiles/justnucker.maFile --top 100
```

- Requer um `.maFile` gerado pelo **Steam Desktop Authenticator (SDA)**.
- Lê a `AccessToken` e `SessionID` embutidos e usa como cookies em
  `steamcommunity.com` e `store.steampowered.com`.
- Habilita `/pricehistory/`, que retorna a série temporal de preços
  dos últimos meses — base dos filtros.

## Como gerar o .maFile

1. Instale o SDA: <https://github.com/Jessecar96/SteamDesktopAuthenticator>
2. Adicione sua conta Steam via arquivo de login ou QR (autenticação inicial).
3. O maFile fica em `maFiles/<account_name>.maFile`.
4. **Mantenha a pasta `maFiles/` fora do controle de versão** (já está no
   `.gitignore`).

## Quando a sessão expira

A `AccessToken` no maFile é um JWT de curta duração (em geral algumas
horas). Quando expirar, o bot detecta e para com a mensagem:

> Sessão Steam para 'justnucker' está expirada ou inválida. Abra o SDA,
> clique 'Login Again' na conta, salve o maFile e rode o bot de novo.

**Por que não fazemos re-login automático?** Isso exigiria você me
mandar a senha da sua conta Steam em texto puro, o que é uma péssima
prática de segurança. Renovar pelo SDA leva 10 segundos.

## Instalação

```bash
git clone https://github.com/zBasck/steamflip.git
cd steamflip
python -m venv .venv
source .venv/bin/activate  # ou .venv\Scripts\Activate.ps1 no Windows
pip install -e .
```

## Comandos úteis

```bash
# Ajuda
python -m steamflip --help
python -m steamflip oportunidades --help

# Dota 2: 50 itens, taxa Steam 15%, margem alvo 10% líquido
python -m steamflip oportunidades --jogo dota2 --top 50 \
    --mafile maFiles/justnucker.maFile \
    --taxa-steam 0.15 --margem 0.10

# Vários jogos em uma execução
python -m steamflip oportunidades --jogo dota2 cs2 tf2 \
    --mafile maFiles/justnucker.maFile --top 200

# Saída em arquivo customizado
python -m steamflip oportunidades --jogo dota2 --top 100 \
    --mafile maFiles/justnucker.maFile \
    --saida relatorio_dota_2026-07-06.xlsx
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
├── __main__.py            # entry point (`python -m steamflip`)
├── main.py                # CLI
├── main_pipeline.py       # orquestração
├── mercado.py             # cliente HTTP do mercado Steam
├── analise.py             # filtros e cálculo de preço-alvo
├── mafile.py              # leitor de .maFile + TOTP + mobileconf
├── relatorio.py           # geração do Excel
├── config.py              # Criterios e Execucao
└── utils.py               # sessão HTTP, parsers, retry
tests/
└── test_*.py
```

## Segurança

- O `.maFile` contém credenciais 2FA (TOTP e identity_secret).
  **Nunca** comite a pasta `maFiles/`. O `.gitignore` já cobre.
- Logs do bot **nunca** imprimem `shared_secret`, `identity_secret`,
  `access_token` ou `refresh_token`. Apenas o `account_name` e o
  final do SteamID mascarado.
- Use o arquivo de permissões `chmod 600 maFiles/*.maFile` no Linux/macOS.
- A automação de leitura é tolerada pela Valve. A automação de
  **compra/venda** viola os Termos de Serviço e pode levar a ban da
  conta. Este bot só lê — você decide o que comprar/vender manualmente.

## Licença

Uso pessoal. Sem garantias. Você é responsável por usar dentro dos
Termos de Serviço da Steam.
