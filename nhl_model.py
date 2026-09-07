#!/usr/bin/env python3
import math, requests
from datetime import datetime
BASE="https://api-web.nhle.com/v1"
H={"User-Agent":"Mozilla/5.0"}
def fetch(u): return requests.get(u, headers=H, timeout=20).json()
def pois(k,lam): return math.exp(-lam)*lam**k/math.factorial(k)
def over_prob(line,lam):
    thr=math.floor(line)+1
    return 1-sum(pois(i,lam) for i in range(thr))

# standings
try:
  sd=fetch(f"{BASE}/standings/now")
  standings={r["teamAbbrev"]["default"]:r for r in sd["standings"]}
  avg_h=sum(t["homeGoalsFor"] for t in standings.values())/sum(t["homeGamesPlayed"] for t in standings.values())
  avg_r=sum(t["roadGoalsFor"] for t in standings.values())/sum(t["roadGamesPlayed"] for t in standings.values())
  def pred(home,away):
    h=standings[home]; a=standings[away]
    lh=min(max((h["homeGoalsFor"]/max(h["homeGamesPlayed"],1) * a["roadGoalsAgainst"]/max(a["roadGamesPlayed"],1))/avg_r,0.5),6)
    la=min(max((a["roadGoalsFor"]/max(a["roadGamesPlayed"],1) * h["homeGoalsAgainst"]/max(h["homeGamesPlayed"],1))/avg_h,0.5),6)
    return lh,la
  sched=fetch(f"{BASE}/schedule/now")
  games=[]
  for wk in sched.get("gameWeek",[]):
    for g in wk.get("games",[]): games.append(g)
  if games:
    first=games[0]["startTimeUTC"][:10]
    games=[g for g in games if g["startTimeUTC"].startswith(first)]
except Exception as e:
  print(e); games=[]; standings={}

def get_props(team, opp, is_home):
  try:
    if team not in standings: return []
    lh,la=pred(opp if not is_home else team, team if not is_home else opp) if opp in standings and team in standings else (3,3)
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
    lh,la=pred(home,away)
    tot=lh+la
    o55=1-sum(pois(i,tot) for i in range(6))
    # win probs
    ph=0; pa=0; pt=0
    for i in range(0,10):
      for j in range(0,10):
        p=pois(i,lh)*pois(j,la)
        if i>j: ph+=p
        elif j>i: pa+=p
        else: pt+=p
    # correct score top 9
    scores=[]
    for i in range(0,7):
      for j in range(0,7):
        scores.append(((j,i), pois(j,la)*pois(i,lh)))
    scores.sort(key=lambda x:x[1], reverse=True)
    top9=scores[:9]

    props_h=get_props(home,away,True)
    props_a=get_props(away,home,False)
    def render_props(lst):
      return "".join([f"<div style='display:flex;justify-content:space-between;gap:12px;font-size:13px;padding:6px 0;border-bottom:1px solid #1e3a6a'><span style='min-width:120px'>{x['name']} ({x['pos']})</span><span style='text-align:right'>Goal {x['any']*100:.0f}% | 1+Pt {x['pts']*100:.0f}% | SOG {x['sog']:.1f} O1.5 {x['o1']*100:.0f}% O2.5 {x['o2']*100:.0f}%</span></div>" for x in lst])

    def render_scores():
      html_sc=""
      for (a,h),p in top9:
        html_sc+=f"<div style='background:#0a1730;border-radius:8px;padding:8px;text-align:center'><div style='font-size:12px;color:#8aa'>{away} {a}-{h} {home}</div><div style='font-weight:700;margin-top:2px'>{p*100:.1f}%</div></div>"
      return html_sc

    win_bar=f"""
    <div style="margin:10px 0 6px 0">
      <div style="display:flex;justify-content:space-between;font-size:12px;margin-bottom:4px"><span>{away} {pa*100:.0f}%</span><span>Tie {pt*100:.0f}%</span><span>{home} {ph*100:.0f}%</span></div>
      <div style="display:flex;height:10px;border-radius:999px;overflow:hidden;background:#0a1730">
        <div style="width:{pa*100:.1f}%;background:#ff4d5a"></div>
        <div style="width:{pt*100:.1f}%;background:#5a5f7a"></div>
        <div style="width:{ph*100:.1f}%;background:#4ea1ff"></div>
      </div>
    </div>"""

    cards+=f"""
    <div style="background:#0f1e3a;border:1px solid #1e3a6a;border-radius:14px;padding:16px;margin:18px 0">
      <h3 style="margin:0 0 4px 0">{away} @ {home} — Total {tot:.2f}</h3>
      <p style="margin:0;color:#b7c5e6;font-size:13px">Proj: {away} {la:.2f} - {lh:.2f} {home} | O5.5 {o55*100:.0f}% / U5.5 {(1-o55)*100:.0f}%</p>
      {win_bar}
      <div style="margin-top:12px"><div style="font-size:12px;color:#8aa;margin-bottom:6px">Correct Score (Regulation)</div><div style="display:grid;grid-template-columns:repeat(3,1fr);gap:6px">{render_scores()}</div></div>
      <details style="margin-top:12px"><summary style="cursor:pointer;color:#4ea1ff;font-size:13px">{home} Props Top 5</summary><div style="margin-top:8px">{render_props(props_h) or 'No data'}</div></details>
      <details style="margin-top:8px"><summary style="cursor:pointer;color:#4ea1ff;font-size:13px">{away} Props Top 5</summary><div style="margin-top:8px">{render_props(props_a) or 'No data'}</div></details>
    </div>"""
  except Exception as e: print(e); continue

html=f"""<!DOCTYPE html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Blue Line — Win Bar + Correct Score + Props</title>
<style>body{{background:#081229;color:#fff;font-family:-apple-system,system-ui,sans-serif;padding:16px;max-width:800px;margin:0 auto}}h1{{color:#4ea1ff;font-size:22px}}</style></head>
<body><h1>🔵 Blue Line — Win Bar + Correct Score + Props</h1><p style="color:#8aa;font-size:12px">Last Updated: {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')} | Games: {len(games)} | Model: Poisson Dixon-Coles style</p>{cards or '<p>No games today — model ready.</p>'}<hr style="border-color:#1e3a6a;margin-top:24px"><p style="font-size:11px;color:#5a6a8a">Research only. No betting advice. Data: api-web.nhle.com</p></body></html>"""

with open("index.html","w") as f: f.write(html)
print(f"Done {len(games)} games")
