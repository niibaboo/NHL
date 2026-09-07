# Blue Line — NHL Predictor

Sibling project to Corner Flag (football) and Deuce Point (tennis). Two pieces:

## 1. `blue_line.html` — live web app (deploy to GitHub Pages)

Single self-contained file, mobile-friendly. Pulls live standings, schedule
and club stats straight from the free public NHL API in the browser — no
backend, no build step, no API key.

**Deploy:**
1. Push `blue_line.html` to a GitHub repo (rename to `index.html` if you want
   it at the root of your Pages site, e.g. `yourname.github.io`).
2. In the repo: Settings → Pages → Deploy from branch → `main` / `/root`.
3. Visit `https://yourname.github.io/<repo>/` (or the root, if you renamed it).

It shows, for the selected day's slate:
- Projected team goals + total-goals over/under (4.5 / 5.5 / 6.5)
- Win probability bar (regulation + a rough OT/SO split of ties)
- Top 5 most likely final scorelines
- Player props per team: anytime goalscorer %, 1+ points %, and shots-on-goal
  projection with Over 1.5 / Over 2.5 probabilities

If `api-web.nhle.com` ever blocks a direct browser request (CORS), the app
automatically retries through a public CORS proxy — no action needed, but if
both a direct call and the proxies are down you'll see a plain-language error
instead of a silent blank screen.

## 2. `nhl_model.py` — Python script (terminal / backtesting)

```
pip3 install requests
python3 nhl_model.py                    # today's/next slate, all games
python3 nhl_model.py --date 2026-10-09
python3 nhl_model.py --game TOR CAR --props
python3 nhl_model.py --backtest TOR --n 15
```

The `--backtest` flag pulls a team's last N completed games and compares the
model's total-goals projection (built from **current** season averages —
not a true walk-forward backtest) against what actually happened, reporting
mean absolute error and an Over/Under 5.5 hit rate. Treat it as a sanity
check on calibration, not a rigorous historical validation.

## The model, in one paragraph

Team goal expectancy is an independent Poisson model (same family as Corner
Flag's correct-score model): a team's home attack rate combined with the
opponent's road defense rate, scaled against the league's home/road scoring
average, and mirrored for the away side. That gives a full score-grid and
over/under. Player props scale each skater's season per-game goals/points
rate by how the game's projected team total compares to that team's season
average (i.e. tougher or softer matchup than usual), with shot volume
dampened at half that adjustment since shot rates move less than scoring
does with opponent quality.

## Data notes

- Endpoints used: `/v1/standings/now`, `/v1/schedule/{date}`,
  `/v1/club-stats/{team}/now`, `/v1/club-schedule-season/{team}/now`,
  `/v1/gamecenter/{id}/boxscore` (backtest only).
- The NHL "now" endpoints fall back to the most recently completed season
  until the new season has games in the books — expected behavior in the
  preseason/very early season, not a bug.
- Player props require a minimum of 10 games played to filter out small
  sample-size noise from call-ups and injury returns.
