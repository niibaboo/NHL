#!/usr/bin/env python3
import os, math, requests
from datetime import datetime
BASE="https://api-web.nhle.com/v1"
H={"User-Agent":"Mozilla/5.0"}
def fetch(u): return requests.get(u, headers=H, timeout=20).json()
def pois(k,lam): return math.exp(-lam)*lam**k/math.factorial(k)
def over_prob(line,lam):
    thr=math.floor(line)+1
    return 1-sum(pois(i,lam) for i in range(thr))

try:
  sd=fetch(f"{BASE}/standings/now")
  standings={r["teamAbbrev"]["default"]:r for r in sd["standings"]}
  avg_h=sum(t["homeGoalsFor"] for t in standings.values())/sum(t["homeGamesPlayed"] for t in standings.values())
  avg_r=sum(t["roadGoalsFor"] for t in standings.values())/sum(t["roadGamesPlayed"] for t in standings.values())
  def pred(home,away):
    h=standings[home]; a=standings[away]
    lh=min(max((h["homeGoalsFor"]/max(h["homeGamesPlayed"],1) * a["roadGoalsAgainst"]/max(a["roadGamesPlayed"],1))/avg_r,0.5),6)
    la=min(max((a["roadGoalsFor"]/max(a["roadGamesPlayed"],1) * h["homeGoalsAgainst"]/max(h["homeGamesPlayed"],1))/avg_h,0.5),6)
    return lh,la,lh+la
  sched=fetch(f"{BASE}/schedule/now")
  games=[]
  for wk in sched.get("gameWeek",[]):
    for g in wk.get("games",[]): games.append(g)
  if games:
    first=games[0]["startTimeUTC"][:10]
    games=[g for g in games if g["startTimeUTC"].startswith(first)]
except: games=[]; standings={}

def get_props(team, opp, is_home):
  try:
    if team not in standings or opp not in standings: return []
    lh,la,_=pred(opp if not is_home else team, team if not is_home else opp) if team in standings and opp in standings else (3,3,6)
    team_lam = lh if is_home else la
    season_gf = standings[team]["goalFor"]/max(standings[team]["gamesPlayed"],1)
    pace = team_lam/max(season_gf,0.1)
    shot_fac = 1+0.5*(pace-1)
    data=fetch(f"{BASE}/club-stats/{team}/now")
    props=[]
    for p in data.get("skaters",[]):
      gp=p.get("gamesPlayed",0)
      if gp<10: continue
      gpg=p["goals"]/gp; ppg=p["points"]/gp; spg=p["shots"]/gp
      lam_g=gpg*pace; lam_p=ppg*pace; lam_s=spg*shot_fac
      props.append({
        "name": f"{p['firstName']['default']} {p['lastName']['default']}",
        "pos": p.get("positionCode",""),
        "any": 1-pois(0,lam_g),
        "pts": 1-pois(0,lam_p),
        "sog": lam_s,
        "o1": over_prob(1.5,lam_s),
        "o2": over_prob(2.5,lam_s)
      })
    props.sort(key=lambda x:x["any"], reverse=True)
    return props[:5]
  except: return []

cards=""
for g in games:
  try:
    home=g["homeTeam"]["abbrev"]; away=g["awayTeam"]["abbrev"]
    lh,la,tot=pred(home,away)
    o55=1-sum(pois(i,tot) for i in range(6))
    props_h=get_props(home,away,True)
    props_a=get_props(away,home,False)
    def render_props(lst):
      return "".join([f"<div style='display:flex;justify-content:space-between;font-size:13px;padding:4px 0;border-bottom:1px solid #1e3a6a'><span>{x['name']} ({x['pos']})</span><span>Goal {x['any']*100:.0f}% | 1+Pt {x['pts']*100:.0f}% | SOG {x['sog']:.1f} O1.5 {x['o1']*100:.0f}% O2.5 {x['o2']*100:.0f}%</span></div>" for x in lst])
    cards+=f"""
    <div style="background:#0f1e3a;border:1px solid #1e3a6a;border-radius:12px;padding:16px;margin:16px 0">
      <h3>{away} @ {home} — Total {tot:.2f}</h3>
      <p>Proj: {away} {la:.2f} - {lh:.2f} {home} | O5.5 {o55*100:.0f}% / U5.5 {(1-o55)*100:.0f}%</p>
      <details style="margin-top:10px"><summary style="cursor:pointer;color:#4ea1ff">{home} Player Props (Top 5)</summary>{render_props(props_h) or 'No data'}</details>
      <details style="margin-top:8px"><summary style="cursor:pointer;color:#4ea1ff">{away} Player Props (Top 5)</summary>{render_props(props_a) or 'No data'}</details>
    </div>"""
  except Exception as e: print(e); pass

html=f"""<!DOCTYPE html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Blue Line - NHL Props</title>
<style>body{{background:#081229;color:#fff;font-family:system-ui;padding:20px}}h1{{color:#4ea1ff}}details{{background:#0a1730;border-radius:8px;padding:8px}}</style></head>
<body><h1>🔵 Blue Line — With Props</h1><p>Last Updated: {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')} | Games: {len(games)}</p>{cards or '<p>Off-season</p>'}<hr><p style="font-size:11px;color:#8aa">Poisson model | club-stats now | Research only</p></body></html>"""

with open("index.html","w") as f: f.write(html)
print(f"Wrote with props for {len(games)} games")
