#!/usr/bin/env python3
"""
Blue Line — NHL correct-score / total-goals / player-props predictor.

Sibling project to Corner Flag (football) and Deuce Point (tennis).
Pulls live data straight from the free, public NHL API (api-web.nhle.com) —
no API key needed — and turns it into a Poisson-based model for:

  * Team goals + total-goals over/under
  * A full correct-score grid per game
  * Player props: anytime goalscorer, 1+ points, shots-on-goal over/under

Run it stand-alone:

    pip3 install requests
    python3 nhl_model.py                  # today's/next slate, all games
    python3 nhl_model.py --date 2026-10-09
    python3 nhl_model.py --game TOR CAR    # single matchup, no schedule call
    python3 nhl_model.py --backtest TOR --n 15

NOTE ON DATA: the NHL "now" endpoints automatically fall back to the most
recently completed season's stats until the new season has a few games in
the books (e.g. in early Sept/Oct the "current" club stats are still last
season's final numbers). That's expected and the model just uses whatever
"now" returns — swap in a specific season string (YYYYYYYY, e.g. 20262027)
once you want to lock to the season in progress.
"""

import argparse
import math
import sys
from datetime import date

import requests

BASE = "https://api-web.nhle.com/v1"
HEADERS = {"User-Agent": "Mozilla/5.0 (Blue Line NHL predictor)"}


# --------------------------------------------------------------------------- #
# Fetching
# --------------------------------------------------------------------------- #

def fetch_json(url, retries=3):
    last_err = None
    for _ in range(retries):
        try:
            r = requests.get(url, headers=HEADERS, timeout=15)
            r.raise_for_status()
            return r.json()
        except Exception as e:  # noqa: BLE001 - want a clean retry loop
            last_err = e
    raise RuntimeError(f"Failed to fetch {url}: {last_err}")


def get_standings():
    """Returns {team_abbrev: standings_row_dict}."""
    data = fetch_json(f"{BASE}/standings/now")
    return {row["teamAbbrev"]["default"]: row for row in data["standings"]}


def get_club_stats(team_abbrev):
    """Returns (skaters_list, goalies_list) for a team, 'now' snapshot."""
    data = fetch_json(f"{BASE}/club-stats/{team_abbrev}/now")
    return data.get("skaters", []), data.get("goalies", [])


def get_schedule(date_str=None):
    """Returns list of game dicts for a date, or the next scheduled slate."""
    url = f"{BASE}/schedule/{date_str}" if date_str else f"{BASE}/schedule/now"
    data = fetch_json(url)
    games = []
    for week in data.get("gameWeek", []):
        for g in week.get("games", []):
            games.append(g)
    if date_str:
        games = [g for g in games if g.get("startTimeUTC", "").startswith(date_str)]
    else:
        # "now" schedule spans a week; keep just the first date that has games
        if games:
            first_date = games[0]["startTimeUTC"][:10]
            games = [g for g in games if g["startTimeUTC"].startswith(first_date)]
    return games


def get_club_schedule_season(team_abbrev):
    data = fetch_json(f"{BASE}/club-schedule-season/{team_abbrev}/now")
    return data.get("games", [])


def get_boxscore(game_id):
    return fetch_json(f"{BASE}/gamecenter/{game_id}/boxscore")


# --------------------------------------------------------------------------- #
# Team strength model
# --------------------------------------------------------------------------- #

class LeagueModel:
    """Builds home/road attack & defense strengths from standings, Dixon-Coles
    style but without the low-score correlation adjustment (kept simple, same
    spirit as the football correct-score model)."""

    def __init__(self, standings):
        self.standings = standings
        total_home_gf = sum(t["homeGoalsFor"] for t in standings.values())
        total_home_gp = sum(t["homeGamesPlayed"] for t in standings.values())
        total_road_gf = sum(t["roadGoalsFor"] for t in standings.values())
        total_road_gp = sum(t["roadGamesPlayed"] for t in standings.values())
        self.league_avg_home_gf = total_home_gf / total_home_gp
        self.league_avg_road_gf = total_road_gf / total_road_gp

    def team_rates(self, abbrev):
        t = self.standings[abbrev]
        return {
            "home_gf_pg": t["homeGoalsFor"] / max(t["homeGamesPlayed"], 1),
            "home_ga_pg": t["homeGoalsAgainst"] / max(t["homeGamesPlayed"], 1),
            "road_gf_pg": t["roadGoalsFor"] / max(t["roadGamesPlayed"], 1),
            "road_ga_pg": t["roadGoalsAgainst"] / max(t["roadGamesPlayed"], 1),
            "gf_pg": t["goalFor"] / max(t["gamesPlayed"], 1),
            "ga_pg": t["goalAgainst"] / max(t["gamesPlayed"], 1),
        }

    def game_lambdas(self, home_abbrev, away_abbrev):
        home = self.team_rates(home_abbrev)
        away = self.team_rates(away_abbrev)
        lambda_home = (home["home_gf_pg"] * away["road_ga_pg"]) / self.league_avg_road_gf
        lambda_away = (away["road_gf_pg"] * home["home_ga_pg"]) / self.league_avg_home_gf
        # Clamp to sane bounds so a tiny early-season sample can't blow up.
        lambda_home = min(max(lambda_home, 0.5), 6.0)
        lambda_away = min(max(lambda_away, 0.5), 6.0)
        return lambda_home, lambda_away

    def team_season_gf_pg(self, abbrev):
        return self.team_rates(abbrev)["gf_pg"]


# --------------------------------------------------------------------------- #
# Poisson helpers
# --------------------------------------------------------------------------- #

def poisson_pmf(k, lam):
    return math.exp(-lam) * lam ** k / math.factorial(k)


def poisson_cdf(k, lam):
    return sum(poisson_pmf(i, lam) for i in range(0, k + 1))


def poisson_over_prob(line, lam, max_k=25):
    """P(X > line) for a X.5 style line, e.g. line=5.5 -> P(goals >= 6)."""
    threshold = math.floor(line) + 1
    return 1 - poisson_cdf(threshold - 1, lam)


def score_grid(lambda_home, lambda_away, max_goals=9):
    grid = {}
    for h in range(max_goals + 1):
        for a in range(max_goals + 1):
            grid[(h, a)] = poisson_pmf(h, lambda_home) * poisson_pmf(a, lambda_away)
    return grid


def outcome_probs(grid):
    home_win = sum(p for (h, a), p in grid.items() if h > a)
    draw_reg = sum(p for (h, a), p in grid.items() if h == a)
    away_win = sum(p for (h, a), p in grid.items() if h < a)
    return home_win, draw_reg, away_win


# --------------------------------------------------------------------------- #
# Game-level predictions
# --------------------------------------------------------------------------- #

def predict_game(model: LeagueModel, home_abbrev, away_abbrev):
    lambda_home, lambda_away = model.game_lambdas(home_abbrev, away_abbrev)
    total_lambda = lambda_home + lambda_away
    grid = score_grid(lambda_home, lambda_away)
    home_win, draw_reg, away_win = outcome_probs(grid)
    top_scores = sorted(grid.items(), key=lambda kv: kv[1], reverse=True)[:5]

    lines = [4.5, 5.5, 6.5]
    ou = {line: poisson_over_prob(line, total_lambda) for line in lines}

    return {
        "home": home_abbrev,
        "away": away_abbrev,
        "lambda_home": lambda_home,
        "lambda_away": lambda_away,
        "total_lambda": total_lambda,
        "home_win_incl_ot": home_win + draw_reg * 0.55,  # rough OT/SO split
        "away_win_incl_ot": away_win + draw_reg * 0.45,
        "top_scores": top_scores,
        "over_under": ou,
    }


# --------------------------------------------------------------------------- #
# Player props
# --------------------------------------------------------------------------- #

def predict_player_props(model: LeagueModel, team_abbrev, opponent_abbrev,
                          is_home, top_n=10, min_games=10):
    lambda_home, lambda_away = model.game_lambdas(
        team_abbrev if is_home else opponent_abbrev,
        opponent_abbrev if is_home else team_abbrev,
    )
    team_game_lambda = lambda_home if is_home else lambda_away
    season_gf_pg = model.team_season_gf_pg(team_abbrev)
    pace_factor = team_game_lambda / max(season_gf_pg, 0.1)
    shots_factor = 1 + 0.5 * (pace_factor - 1)  # dampened: shot volume is stickier than goals

    skaters, _ = get_club_stats(team_abbrev)
    props = []
    for p in skaters:
        gp = p.get("gamesPlayed", 0)
        if gp < min_games:
            continue
        goals_pg = p["goals"] / gp
        points_pg = p["points"] / gp
        shots_pg = p["shots"] / gp

        lam_goal = goals_pg * pace_factor
        lam_point = points_pg * pace_factor
        lam_shot = shots_pg * shots_factor

        props.append({
            "name": f"{p['firstName']['default']} {p['lastName']['default']}",
            "position": p.get("positionCode", ""),
            "gp": gp,
            "goals_pg": goals_pg,
            "points_pg": points_pg,
            "shots_pg": shots_pg,
            "p_anytime_goal": 1 - poisson_pmf(0, lam_goal),
            "p_1plus_points": 1 - poisson_pmf(0, lam_point),
            "sog_over_1_5": poisson_over_prob(1.5, lam_shot),
            "sog_over_2_5": poisson_over_prob(2.5, lam_shot),
            "sog_expected": lam_shot,
        })

    props.sort(key=lambda x: x["p_anytime_goal"], reverse=True)
    return props[:top_n]


# --------------------------------------------------------------------------- #
# Backtest (season-average based — see module docstring for the caveat)
# --------------------------------------------------------------------------- #

def backtest_team(model: LeagueModel, team_abbrev, n_games=10):
    games = get_club_schedule_season(team_abbrev)
    played = [g for g in games if g.get("gameState") in ("OFF", "FINAL")]
    played = played[-n_games:]

    rows = []
    for g in played:
        home_ab = g["homeTeam"]["abbrev"]
        away_ab = g["awayTeam"]["abbrev"]
        actual_home = g["homeTeam"].get("score")
        actual_away = g["awayTeam"].get("score")
        if actual_home is None or actual_away is None:
            continue
        pred = predict_game(model, home_ab, away_ab)
        actual_total = actual_home + actual_away
        rows.append({
            "date": g.get("gameDate", ""),
            "matchup": f"{away_ab} @ {home_ab}",
            "actual": f"{actual_away}-{actual_home}",
            "pred_lambda_total": round(pred["total_lambda"], 2),
            "abs_error": round(abs(pred["total_lambda"] - actual_total), 2),
            "over_5_5_called_right": (
                (pred["over_under"][5.5] >= 0.5) == (actual_total > 5.5)
            ),
        })

    if not rows:
        return rows, {}
    mae = sum(r["abs_error"] for r in rows) / len(rows)
    hit_rate = sum(r["over_5_5_called_right"] for r in rows) / len(rows)
    return rows, {"mean_abs_error": round(mae, 3), "over_5_5_hit_rate": round(hit_rate, 3)}


# --------------------------------------------------------------------------- #
# CLI / pretty printing
# --------------------------------------------------------------------------- #

def print_game_prediction(pred):
    print(f"\n{pred['away']} @ {pred['home']}")
    print(f"  Projected score: {pred['away']} {pred['lambda_away']:.2f} - "
          f"{pred['lambda_home']:.2f} {pred['home']}  "
          f"(total {pred['total_lambda']:.2f})")
    print(f"  Win prob (incl. OT/SO): {pred['home']} "
          f"{pred['home_win_incl_ot']*100:.1f}%  |  {pred['away']} "
          f"{pred['away_win_incl_ot']*100:.1f}%")
    print("  Most likely scorelines:")
    for (h, a), p in pred["top_scores"]:
        print(f"    {pred['away']} {a}-{h} {pred['home']}: {p*100:.1f}%")
    print("  Total goals over/under:")
    for line, p in pred["over_under"].items():
        print(f"    O{line}: {p*100:.1f}%   U{line}: {(1-p)*100:.1f}%")


def print_player_props(team, opponent, props):
    print(f"\n  Player props — {team} vs {opponent}:")
    for p in props:
        print(f"    {p['name']:<22} ({p['position']})  "
              f"Anytime goal: {p['p_anytime_goal']*100:5.1f}%  "
              f"1+ pts: {p['p_1plus_points']*100:5.1f}%  "
              f"SOG proj: {p['sog_expected']:.1f}  "
              f"O1.5 SOG: {p['sog_over_1_5']*100:5.1f}%  "
              f"O2.5 SOG: {p['sog_over_2_5']*100:5.1f}%")


def main():
    ap = argparse.ArgumentParser(description="Blue Line — NHL predictor")
    ap.add_argument("--date", help="YYYY-MM-DD (defaults to next scheduled slate)")
    ap.add_argument("--game", nargs=2, metavar=("HOME", "AWAY"),
                     help="Predict a single matchup by team abbrev, e.g. --game TOR CAR")
    ap.add_argument("--props", action="store_true", help="Include player props per game")
    ap.add_argument("--backtest", metavar="TEAM", help="Backtest a team's last N games")
    ap.add_argument("--n", type=int, default=10, help="Games to use for --backtest")
    args = ap.parse_args()

    print("Fetching standings...")
    standings = get_standings()
    model = LeagueModel(standings)

    if args.backtest:
        rows, summary = backtest_team(model, args.backtest.upper(), args.n)
        print(f"\nBacktest — {args.backtest.upper()} last {len(rows)} games")
        for r in rows:
            print(f"  {r['date']}  {r['matchup']:<12} actual {r['actual']:<7} "
                  f"pred total {r['pred_lambda_total']:<5} "
                  f"abs err {r['abs_error']:<5} "
                  f"O/U5.5 right: {r['over_5_5_called_right']}")
        print(f"\n  Mean abs error (total goals): {summary.get('mean_abs_error')}")
        print(f"  Over/Under 5.5 hit rate:      {summary.get('over_5_5_hit_rate')}")
        return

    if args.game:
        home, away = [t.upper() for t in args.game]
        pred = predict_game(model, home, away)
        print_game_prediction(pred)
        if args.props:
            print_player_props(home, away, predict_player_props(model, home, away, True))
            print_player_props(away, home, predict_player_props(model, away, home, False))
        return

    print("Fetching schedule...")
    games = get_schedule(args.date)
    if not games:
        print("No games found for that date.")
        return

    for g in games:
        home = g["homeTeam"]["abbrev"]
        away = g["awayTeam"]["abbrev"]
        try:
            pred = predict_game(model, home, away)
        except KeyError:
            print(f"\n{away} @ {home}: skipped (no standings data yet)")
            continue
        print_game_prediction(pred)
        if args.props:
            print_player_props(home, away, predict_player_props(model, home, away, True))
            print_player_props(away, home, predict_player_props(model, away, home, False))


if __name__ == "__main__":
    if sys.version_info < (3, 7):
        print("Needs Python 3.7+")
        sys.exit(1)
    try:
        main()
    except RuntimeError as e:
        print(f"Error: {e}")
        sys.exit(1)
