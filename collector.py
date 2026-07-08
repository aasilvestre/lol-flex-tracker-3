"""
Coleta um snapshot dos jogadores Challenger/Grão-Mestre/Mestre da fila Flex (BR1):
  - Registra o LP atual de cada jogador e compara com o snapshot anterior
    para detectar jogos que ocorreram no intervalo entre coletas.
  - Roda a cada 5 minutos (via GitHub Actions + cron-job.org).
  - Não usa a Spectator API — apenas a League API para leitura de LP.

Arquivos gerados/atualizados:
  data/snapshots.csv   — uma linha por ciclo (agregado)
  data/player_lp.csv   — uma linha por jogador por ciclo (histórico de LP)
"""

import csv
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

API_KEY = os.environ.get("RIOT_API_KEY", "")
if not API_KEY:
    raise SystemExit("Variável RIOT_API_KEY não definida.")

PLATFORM = "br1"
QUEUE    = "RANKED_FLEX_SR"

CALL_DELAY = 1.3  # segundos entre chamadas (respeita rate limit)

BASE_URL = f"https://{PLATFORM}.api.riotgames.com"

DATA_DIR           = Path(__file__).parent / "data"
SNAPSHOTS_CSV      = DATA_DIR / "snapshots.csv"
PLAYER_CURRENT_CSV = DATA_DIR / "player_current.csv"   # sobrescrito a cada run (~2k linhas sempre)
LP_CHANGES_CSV     = DATA_DIR / "lp_changes.csv"       # append só quando LP muda (~pequeníssimo)

SNAPSHOTS_HEADER = [
    "timestamp_utc",
    "total_tracked",
    "challenger_count",
    "gm_count",
    "master_count",
    "games_detected_by_lp",
    "lp_wins_detected",
    "lp_losses_detected",
]
PLAYER_CURRENT_HEADER = ["puuid", "tier", "lp", "wins", "losses", "last_updated_utc"]
LP_CHANGES_HEADER     = ["timestamp_utc", "puuid", "tier", "old_lp", "new_lp", "lp_delta"]

session = requests.Session()
session.headers.update({"X-Riot-Token": API_KEY})
start_time = time.time()


def elapsed() -> str:
    s = int(time.time() - start_time)
    return f"{s // 60}m{s % 60:02d}s"


def get_with_retry(url: str, max_retries: int = 6) -> requests.Response:
    for attempt in range(max_retries):
        resp = session.get(url)
        if resp.status_code in (200, 404):
            return resp
        if resp.status_code == 429:
            wait = int(resp.headers.get("Retry-After", "10")) + 2
            print(f"  [{elapsed()}] Rate limit — aguardando {wait}s...", flush=True)
            time.sleep(wait)
            continue
        if resp.status_code in (500, 502, 503, 504):
            print(f"  [{elapsed()}] HTTP {resp.status_code} transitório, tentativa {attempt+1}/{max_retries}...", flush=True)
            time.sleep(3 * (attempt + 1))
            continue
        print(f"  [{elapsed()}] HTTP {resp.status_code} inesperado: {url}", flush=True)
        return resp
    raise RuntimeError(f"Falha após {max_retries} tentativas: {url}")


def fetch_league(tier_url: str) -> list[dict]:
    resp = get_with_retry(tier_url)
    resp.raise_for_status()
    time.sleep(CALL_DELAY)
    return resp.json().get("entries", [])


def ensure_csvs():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if not SNAPSHOTS_CSV.exists():
        with SNAPSHOTS_CSV.open("w", newline="") as f:
            csv.writer(f).writerow(SNAPSHOTS_HEADER)
    if not LP_CHANGES_CSV.exists():
        with LP_CHANGES_CSV.open("w", newline="") as f:
            csv.writer(f).writerow(LP_CHANGES_HEADER)


def load_current() -> dict[str, dict]:
    """Lê o estado atual de cada jogador (player_current.csv)."""
    if not PLAYER_CURRENT_CSV.exists():
        return {}
    with PLAYER_CURRENT_CSV.open(newline="") as f:
        return {row["puuid"]: row for row in csv.DictReader(f)}


def save_current(rows: list[dict]):
    """Sobrescreve player_current.csv — sempre ~2.000 linhas, nunca cresce."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = PLAYER_CURRENT_CSV.with_suffix(".tmp")
    with tmp.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=PLAYER_CURRENT_HEADER, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    tmp.replace(PLAYER_CURRENT_CSV)


def append_changes(changes: list[dict]):
    """Acrescenta ao lp_changes.csv — só quando LP muda (~poucos KB/dia)."""
    if not changes:
        return
    with LP_CHANGES_CSV.open("a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=LP_CHANGES_HEADER, extrasaction="ignore")
        w.writerows(changes)


def save_snapshot(ts: str, total: int,
                  n_chall: int, n_gm: int, n_master: int,
                  games_lp: int, wins_lp: int, losses_lp: int):
    with SNAPSHOTS_CSV.open("a", newline="") as f:
        csv.writer(f).writerow([
            ts, total, n_chall, n_gm, n_master,
            games_lp, wins_lp, losses_lp,
        ])


def main():
    ensure_csvs()

    print(f"[{elapsed()}] Buscando listas Challenger + Grão-Mestre + Mestre (Flex BR)...", flush=True)
    challengers = fetch_league(f"{BASE_URL}/lol/league/v4/challengerleagues/by-queue/{QUEUE}")
    gm_players  = fetch_league(f"{BASE_URL}/lol/league/v4/grandmasterleagues/by-queue/{QUEUE}")
    masters     = fetch_league(f"{BASE_URL}/lol/league/v4/masterleagues/by-queue/{QUEUE}")

    total = len(challengers) + len(gm_players) + len(masters)
    print(
        f"[{elapsed()}] Challenger: {len(challengers)} | GM: {len(gm_players)} | "
        f"Mestre: {len(masters)} | Total: {total}",
        flush=True,
    )

    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")

    prev = load_current()
    is_first_run = not bool(prev)
    if is_first_run:
        print(f"[{elapsed()}] Primeira execução — sem estado anterior.", flush=True)
    else:
        print(f"[{elapsed()}] Estado anterior: {len(prev)} jogadores.", flush=True)

    all_players = (
        [(e, "challenger") for e in challengers]
        + [(e, "gm")         for e in gm_players]
        + [(e, "master")     for e in masters]
    )

    checked   = 0
    errors    = 0
    games_lp  = 0
    wins_lp   = 0
    losses_lp = 0
    new_rows: list[dict]  = []
    changes:  list[dict]  = []

    LOG_INTERVAL = 100

    for i, (entry, tier) in enumerate(all_players, start=1):
        puuid = entry.get("puuid")
        lp    = entry.get("leaguePoints", 0)

        if puuid is None:
            errors += 1
            continue

        wins   = entry.get("wins", 0)
        losses = entry.get("losses", 0)

        new_rows.append({
            "puuid":            puuid,
            "tier":             tier,
            "lp":               lp,
            "wins":             wins,
            "losses":           losses,
            "last_updated_utc": ts,
        })

        if not is_first_run and puuid in prev:
            old_lp = int(prev[puuid]["lp"])
            delta  = lp - old_lp
            if delta != 0:
                changes.append({
                    "timestamp_utc": ts,
                    "puuid":         puuid,
                    "tier":          tier,
                    "old_lp":        old_lp,
                    "new_lp":        lp,
                    "lp_delta":      delta,
                })
                if delta > 0:
                    games_lp += 1
                    wins_lp  += 1
                else:
                    games_lp  += 1
                    losses_lp += 1

        checked += 1

        if checked % LOG_INTERVAL == 0 or i == len(all_players):
            print(
                f"[{elapsed()}] {checked}/{total} ({checked/total*100:.0f}%) — "
                f"jogos detectados (LP): {games_lp} (+{wins_lp}W / -{losses_lp}L)",
                flush=True,
            )

    save_current(new_rows)
    append_changes(changes)
    save_snapshot(
        ts, checked,
        len(challengers), len(gm_players), len(masters),
        games_lp, wins_lp, losses_lp,
    )

    print(f"\n[{elapsed()}] ✅ Concluído!", flush=True)
    if not is_first_run:
        print(f"[{elapsed()}] Jogos detectados por LP: {games_lp} (+{wins_lp}W / -{losses_lp}L)", flush=True)
    print(f"[{elapsed()}] Erros/sem PUUID: {errors}", flush=True)
    print(f"[{elapsed()}] Snapshot salvo.", flush=True)


if __name__ == "__main__":
    main()
