# 🏆 LoL Flex Tracker

Monitora a atividade dos jogadores **Challenger, Grão-Mestre e Mestre** na **Ranqueada Flex (BR1)**, detectando jogos pela variação de LP a cada 5 minutos.

---

## Como funciona

```
cron-job.org (a cada 5 min)
    → dispara GitHub Actions via API
        → collector.py (3 chamadas à API, ~5 segundos)
            → detecta variações de LP
                → commita apenas os deltas
                    → Streamlit Cloud atualiza o dashboard
```

**Detecção de jogos por LP:** a cada 5 minutos o collector compara o LP atual de cada jogador com o estado anterior. Se mudou, um jogo aconteceu naquele intervalo.

---

## Estratégia de armazenamento

O problema comum em versões anteriores era o arquivo de LP crescer indefinidamente (salvar todos os ~2.000 jogadores a cada run = ~1 GB/mês). Esta versão resolve isso com dois arquivos de papéis distintos:

| Arquivo | Estratégia | Tamanho |
|---------|-----------|---------|
| `player_current.csv` | Sobrescrito a cada run — sempre ~2.000 linhas | ~150 KB fixo |
| `lp_changes.csv` | Append só quando LP muda | ~3 MB/mês |
| `snapshots.csv` | Append 1 linha por run (agregado) | ~2 MB/mês |

---

## Estrutura de arquivos

```
lol-flex-tracker/
├── .github/workflows/
│   └── main.yml              ← workflow (disparo a cada 5 min)
├── data/
│   ├── player_current.csv    ← estado atual de todos os jogadores (sobrescrito)
│   ├── lp_changes.csv        ← histórico de variações de LP (append só quando muda)
│   └── snapshots.csv         ← agregado por ciclo (append)
├── collector.py              ← coleta LP dos 3 tiers (3 chamadas à API)
├── dashboard.py              ← dashboard Streamlit (4 abas)
├── requirements.txt
└── README.md
```

### Colunas dos CSVs

**`player_current.csv`** — sobrescrito a cada run
| Coluna | Descrição |
|--------|-----------|
| `puuid` | ID único do jogador |
| `tier` | challenger / gm / master |
| `lp` | League Points atual |
| `wins` / `losses` | Vitórias e derrotas na season |
| `last_updated_utc` | Timestamp da última atualização |

**`lp_changes.csv`** — append somente quando LP muda
| Coluna | Descrição |
|--------|-----------|
| `timestamp_utc` | Momento da detecção |
| `puuid` | ID do jogador |
| `tier` | challenger / gm / master |
| `old_lp` | LP antes |
| `new_lp` | LP depois |
| `lp_delta` | Diferença (positivo = vitória, negativo = derrota) |

**`snapshots.csv`** — uma linha por ciclo de 5 min
| Coluna | Descrição |
|--------|-----------|
| `timestamp_utc` | Momento da coleta |
| `total_tracked` | Total de jogadores verificados |
| `challenger_count` / `gm_count` / `master_count` | Quantidade por tier |
| `games_detected_by_lp` | Jogadores com LP diferente do ciclo anterior |
| `lp_wins_detected` | Subconjunto: LP subiu (vitória provável) |
| `lp_losses_detected` | Subconjunto: LP caiu (derrota provável) |

---

## Pré-requisitos

- Conta no **GitHub**
- Conta no **Streamlit Community Cloud** — https://share.streamlit.io
- Conta no **cron-job.org** — https://cron-job.org
- **Personal API Key** da Riot — https://developer.riotgames.com

> A Personal API Key não expira. A chave de desenvolvimento expira a cada 24h e precisa ser trocada manualmente no secret do GitHub.

---

## Setup

### Passo 1 — Criar o repositório no GitHub

1. Acesse https://github.com/new
2. Nome sugerido: `lol-flex-tracker`
3. Faça upload de todos os arquivos mantendo a estrutura de pastas

### Passo 2 — Adicionar a API Key como secret

**Settings → Secrets and variables → Actions → New repository secret**

| Nome | Valor |
|------|-------|
| `RIOT_API_KEY` | Sua chave `RGAPI-...` |

### Passo 3 — Configurar o cron-job.org

1. Cadastre-se em https://cron-job.org
2. **Create cronjob:**

**Aba principal:**
| Campo | Valor |
|-------|-------|
| Title | `LoL Flex Tracker` |
| URL | `https://api.github.com/repos/SEU_USUARIO/lol-flex-tracker/actions/workflows/main.yml/dispatches` |
| Schedule | Every 5 minutes |

**Aba Advanced → Headers:**
| Key | Value |
|-----|-------|
| `Authorization` | `Bearer ghp_SEU_TOKEN_AQUI` |
| `Accept` | `application/vnd.github+json` |
| `Content-Type` | `application/json` |

**Aba Advanced → Request body:**
```json
{"ref":"main"}
```

**Aba Advanced → Request method:** `POST`

3. Salve e clique em **Test run** — deve retornar **204 No Content**

> O token é um **Personal Access Token** do GitHub (Settings → Developer settings → Tokens → escopo `workflow`). Diferente da API Key da Riot.

### Passo 4 — Hospedar o dashboard

1. Acesse https://share.streamlit.io → **New app**
2. Repository: `seu-usuario/lol-flex-tracker` | Branch: `main` | File: `dashboard.py`
3. **Deploy**

### Passo 5 — Primeira execução

**Actions → Coletar LP (5 min) → Run workflow**

Na primeira run o collector salva o estado inicial sem detectar mudanças (sem histórico anterior). A partir da segunda run (5 min depois) o heatmap começa a receber dados.

---

## Dashboard — 4 abas

| Aba | Conteúdo |
|-----|----------|
| 🔥 **Heatmap** | Mapa de calor em células de 5 min. Soma de jogos detectados nos últimos 30 min, deslocada -30 min (estima entrada na fila, não fim do jogo). Domingo no topo. |
| 📈 **Série Temporal** | Jogos detectados por hora, vitórias/derrotas inferidas, soma de 30 min com deslocamento |
| 👤 **Jogadores** | Estado atual de todos os rastreados com LP, winrate e distribuição por tier |
| 🗃️ **Dados Brutos** | Últimas mudanças de LP e estado atual completo |

---

## Manutenção

| Tarefa | Como fazer |
|--------|-----------|
| Verificar saúde | GitHub → Actions: deve haver um run a cada 5 min |
| Pausar coleta | cron-job.org → desativar o job |
| Rodar manualmente | GitHub → Actions → Run workflow |

---

## Migrando de uma versão anterior com `player_lp.csv`

Se você tem um repositório antigo com o `player_lp.csv` grande, **crie um repositório novo** e suba os arquivos deste ZIP — é a forma mais simples de começar limpo.

Se preferir limpar o histórico do repositório existente:
```bash
git filter-branch --force --index-filter \
  "git rm --cached --ignore-unmatch data/player_lp.csv" \
  --prune-empty --tag-name-filter cat -- --all
git push origin --force --all
```
⚠️ Operação destrutiva e irreversível — avise colaboradores antes.

---

## Limitações

- **Um delta por intervalo de 5 min:** se o jogador jogou 2 partidas em 5 min, o delta reflete o saldo líquido, não dois eventos separados
- **Deslocamento fixo de 30 min:** partidas de Flex duram em média 28–35 min; o deslocamento é uma estimativa, não exato
- **Buracos de dados:** se a API da Riot estiver fora ou a chave expirar, haverá lacuna naquele período
