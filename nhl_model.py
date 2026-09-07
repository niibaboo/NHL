# REPLACE your entire nhl_model.py with this
#!/usr/bin/env python3
import os, json, math, requests
from datetime import datetime

BASE = "https://api-web.nhle.com/v1"
HEADERS = {"User-Agent": "Mozilla/5.0"}

def fetch(u): return requests.get(u, headers=HEADERS, timeout=15).json()

def poisson(k, lam): return math.exp(-lam) * lam**k / math.factorial(k)

# --- fetch ---
standings_data = fetch(f"{BASE}/standings/now")
standings = {r["teamAbbrev"]["default"]: r for r in standings_data["standings"]}

total_home_gf = sum(t["homeGoalsFor"] for t in standings.values())
total_home_gp = sum(t["homeGamesPlayed"] for t in standings.values())
total_road_gf = sum(t["roadGoalsFor"] for t in standings.values())
total_road_gp = sum(t["roadGamesPlayed"] for t in standings.values())
avg_home = total_home_gf/total_home_gp
avg_road = total_road_gf/total_road_gp

def predict(home, away):
    h = standings[home]; a = standings[away]
    h_gf = h["homeGoalsFor"]/max(h["homeGamesPlayed"],1)
    h_ga = h["homeGoalsAgainst"]/max(h["homeGamesPlayed"],1)
    a_gf = a["roadGoalsFor"]/max(a["roadGamesPlayed"],1)
    a_ga = a["roadGoalsAgainst"]/max(a["roadGamesPlayed"],1)
    lam_h = min(max((h_gf * a_ga)/avg_road,0.5),6.0)
    lam_a = min(max((a_gf * h_ga)/avg_home,0.5),6.0)
    total = lam_h + lam_a
    # top scores
    grid = []
    for hh in range(7):
        for aa in range(7):
            p = poisson(hh,lam_h)*poisson(aa,lam_a)
            grid.append(((hh,aa),p))
    grid = sorted(grid,key=lambda x:x[1],reverse=True)[:3]
    over55 = 1 - sum(poisson(i,total) for i in range(6))
    return lam_h, lam_a, total, over55, grid

# schedule - next slate
sched = fetch(f"{BASE}/schedule/now")
games = []
for wk in sched.get("gameWeek",[]):
    for g in wk.get("games",[]):
        games.append(g)
if games:
    first = games[0]["startTimeUTC"][:10]
    games = [g for g in games if g["startTimeUTC"].startswith(first)]

# --- build HTML ---
os.makedirs("docs", exist_ok=True) if os.path.exists("docs") else None
# we write to both root and docs for Pages compatibility
html_cards = ""
for g in games:
    home = g["homeTeam"]["abbrev"]; away = g["awayTeam"]["abbrev"]
    try:
        lh, la, tot, o55, top = predict(home,away)
        top_str = ", ".join([f"{away} {a}-{h} {home} ({p*100:.1f}%)" for (h,a),p in top])
    except: continue
    html_cards += f"""
    <div style="background:#0f1e3a;border:1px solid #1e3a6a;border-radius:12px;padding:16px;margin:12px 0">
      <h3>{away} @ {home} — Total {tot:.2f}</h3>
      <p>Proj: {away} {la:.2f} - {lh:.2f} {home}</p>
      <p>O5.5: {o55*100:.1f}% | U5.5: {(1-o55)*100:.1f}%</p>
      <p style="font-size:13px;color:#8aa">Most likely: {top_str}</p>
    </div>
    """

final_html = f"""
<!DOCTYPE html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Blue Line - NHL</title>
<style>body{{background:#081229;color:white;font-family:system-ui;padding:20px}} h1{{color:#4ea1ff}}</style></head>
<body>
<h1>🔵 Blue Line</h1>
<p>Live NHL projections — baked from NHL API at build time (no browser CORS issue)</p>
<p>Last Updated: {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')} | Games: {len(games)}</p>
{html_cards if html_cards else "<p>No games today — showing next slate fallback.</p><p>Data: NHL public API. Poisson model on home/road GF/GA.</p>"}
<hr><p style="font-size:11px;color:#8aa">Data: api-web.nhle.com | Model: Independent Poisson | For research only</p>
</body></html>
"""

with open("index.html","w") as f: f.write(final_html)
if os.path.exists("docs"):
    with open("docs/index.html","w") as f: f.write(final_html)

print(f"Generated index.html with {len(games)} games")
