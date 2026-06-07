#!/usr/bin/env python3
"""
데일리 뮤직 뉴스레터 빌더 (독립 실행, 외부 패키지 0).

키워드별로 YouTube 인기 영상을 Apify로 하루 1번 수집하고(최신순),
history.json에 누적해 3개 뷰(최근/전체/뜨는중)를 추가 비용 없이 계산한 뒤
의존성 없는 단일 HTML(index.html + archive/날짜.html)로 렌더한다.

사용:
  python3 build.py            # 평소 실행 (Apify 수집 + 렌더)
  python3 build.py --once     # 동일 (수동 트리거 명시용)
  python3 build.py --dry      # Apify 호출 없이 기존 history로 렌더만

토큰: ~/.config/music-newsletter/.env 의 APIFY_TOKEN (또는 환경변수).
"""
import json, os, sys, time, html, datetime, subprocess, urllib.request, urllib.parse, urllib.error
from pathlib import Path

HERE = Path(__file__).resolve().parent
KEYWORDS = HERE / "keywords.json"
HISTORY = HERE / "history.json"
STATE = HERE / "state.json"
INDEX = HERE / "index.html"
ARCHIVE = HERE / "archive"
LOG = HERE / "build.log"
ENV = Path.home() / ".config" / "music-newsletter" / ".env"

ACTOR = "streamers~youtube-scraper"
TODAY = datetime.date.today()
DRY = "--dry" in sys.argv


def log(msg):
    line = f"{datetime.datetime.now().isoformat(timespec='seconds')} | {msg}"
    print(line)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def load_json(path, default):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def save_json(path, data):
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def get_token():
    tok = os.environ.get("APIFY_TOKEN")
    if tok:
        return tok.strip()
    if ENV.exists():
        for ln in ENV.read_text(encoding="utf-8").splitlines():
            ln = ln.strip()
            if ln.startswith("APIFY_TOKEN"):
                return ln.split("=", 1)[1].strip().strip('"').strip("'")
    return None


# ---------- Apify fetch ----------
def fetch_keyword(token, query, max_results):
    """Apify 액터를 동기 실행하고 데이터셋 아이템을 바로 받는다."""
    url = (f"https://api.apify.com/v2/acts/{ACTOR}/run-sync-get-dataset-items"
           f"?token={urllib.parse.quote(token)}")
    payload = {
        "searchQueries": [query],
        "maxResults": max_results,
        "maxResultsShorts": 0,
        "maxResultStreams": 0,
        "sortingOrder": "date",
        "downloadSubtitles": False,
    }
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=300) as resp:
        return json.loads(resp.read().decode("utf-8"))


def parse_pub_date(item):
    d = (item.get("date") or "")[:10]
    try:
        return datetime.date.fromisoformat(d)
    except ValueError:
        return None


# ---------- history / ranking ----------
def update_history(history, items, theme):
    today = TODAY.isoformat()
    for it in items:
        vid = it.get("id")
        if not vid:
            continue
        views = it.get("viewCount") or 0
        rec = history.get(vid)
        if rec:
            rec["prev_views"] = rec.get("views", views)
            rec["views"] = views
            rec["last_seen"] = today
            rec["likes"] = it.get("likes") or rec.get("likes") or 0
        else:
            history[vid] = {
                "title": it.get("title") or "(제목 없음)",
                "channel": it.get("channelName") or "",
                "url": it.get("url") or f"https://www.youtube.com/watch?v={vid}",
                "thumbnail": it.get("thumbnailUrl") or "",
                "published": (it.get("date") or "")[:10],
                "theme": theme,
                "first_seen": today,
                "last_seen": today,
                "views": views,
                "prev_views": None,
                "likes": it.get("likes") or 0,
            }


def rank_views(history, recent_days):
    rows = []
    for vid, r in history.items():
        r = dict(r, id=vid)
        rows.append(r)

    # 🔥 전체 인기
    all_time = sorted(rows, key=lambda r: r.get("views") or 0, reverse=True)[:5]

    # 🆕 최근 인기 (업로드 ≤ recent_days)
    cutoff = TODAY - datetime.timedelta(days=recent_days)
    def is_recent(r):
        try:
            return datetime.date.fromisoformat(r["published"]) >= cutoff
        except (ValueError, KeyError):
            return False
    recent = sorted([r for r in rows if is_recent(r)],
                    key=lambda r: r.get("views") or 0, reverse=True)[:5]

    # 📈 뜨는 중 (전일 대비 증가량)
    trend = []
    for r in rows:
        pv = r.get("prev_views")
        if pv is not None:
            delta = (r.get("views") or 0) - pv
            if delta > 0:
                trend.append(dict(r, delta=delta))
    trending = sorted(trend, key=lambda r: r["delta"], reverse=True)[:5]

    return {"recent": recent, "all_time": all_time, "trending": trending}


# ---------- render ----------
def fmt(n):
    try:
        return f"{int(n):,}"
    except (ValueError, TypeError):
        return "0"


def card_html(r, kind, rank):
    title = html.escape(r.get("title", ""))
    channel = html.escape(r.get("channel", ""))
    theme = html.escape(r.get("theme", ""))
    url = html.escape(r.get("url", "#"))
    thumb = html.escape(r.get("thumbnail", ""))
    if kind == "trending":
        meta = f"<b>+{fmt(r.get('delta'))}</b> 조회수 · 누적 {fmt(r.get('views'))}"
    elif kind == "recent":
        meta = f"{html.escape(r.get('published',''))} · 조회 {fmt(r.get('views'))}"
    else:
        meta = f"조회 {fmt(r.get('views'))} · 👍 {fmt(r.get('likes'))}"
    thumb_tag = (f'<img src="{thumb}" loading="lazy" alt="{title} 썸네일">'
                 if thumb else '<div class="noimg">🎵</div>')
    return f"""<a class="card" style="--i:{rank}" href="{url}" target="_blank" rel="noopener">
      <div class="thumb">{thumb_tag}
        <span class="rank">{rank}</span>
        <span class="play"><svg viewBox="0 0 24 24" width="22" height="22" fill="currentColor"><path d="M8 5v14l11-7z"/></svg></span>
        <span class="tag">{theme}</span>
      </div>
      <div class="body"><div class="title">{title}</div>
        <div class="channel">{channel}</div><div class="meta">{meta}</div></div>
    </a>"""


def render(views, total_videos):
    tabs = [("recent", "🆕 최근 인기"), ("all_time", "🔥 전체 인기"), ("trending", "📈 뜨는 중")]
    panels = ""
    btns = ""
    for i, (key, label) in enumerate(tabs):
        active = " active" if i == 0 else ""
        btns += f'<button class="tabbtn{active}" data-tab="{key}">{label}</button>'
        rows = views[key]
        if rows:
            cards = "\n".join(card_html(r, key, n) for n, r in enumerate(rows, 1))
        else:
            note = "내일부터 데이터가 쌓입니다 (전일 대비 계산)" if key == "trending" else "아직 항목이 없습니다"
            cards = f'<p class="empty">{note}</p>'
        panels += f'<section class="panel{active}" id="panel-{key}">{cards}</section>'

    date_str = TODAY.isoformat()
    favicon = ("data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'>"
               "<text y='.9em' font-size='90'>🎵</text></svg>")
    grain = ("data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' width='160' height='160'>"
             "<filter id='n'><feTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='2'/>"
             "</filter><rect width='100%25' height='100%25' filter='url(%23n)'/></svg>")
    return f"""<!doctype html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="description" content="매일 자동 정리되는 음악 키워드 인기 영상 — 최근·전체·뜨는 중 Top 5">
<meta property="og:title" content="데일리 뮤직 뉴스레터">
<meta property="og:description" content="키워드별 YouTube 인기 영상을 매일 한 페이지로">
<title>데일리 뮤직 뉴스레터 · {date_str}</title>
<link rel="icon" href="{favicon}">
<link rel="preconnect" href="https://cdn.jsdelivr.net">
<link rel="stylesheet" href="https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/static/pretendard.min.css">
<style>
  :root {{
    color-scheme: dark;
    --bg:#09090b; --surface:#141417; --line:rgba(255,255,255,.07);
    --text:#ededf0; --muted:#9a9aa6;
    --accent:#e0a458; --accent-weak:rgba(224,164,88,.14);
    --spring:cubic-bezier(.16,1,.3,1);
  }}
  * {{ box-sizing:border-box; }}
  html {{ scroll-behavior:smooth; }}
  body {{
    margin:0; color:var(--text); min-height:100dvh;
    font-family:Pretendard,-apple-system,BlinkMacSystemFont,"Apple SD Gothic Neo",sans-serif;
    word-break:keep-all; -webkit-font-smoothing:antialiased;
    background:
      radial-gradient(1100px 600px at 12% -10%, rgba(224,164,88,.12), transparent 60%),
      radial-gradient(900px 500px at 115% 0%, rgba(255,255,255,.04), transparent 55%),
      var(--bg);
    background-attachment:fixed;
  }}
  body::after {{ content:""; position:fixed; inset:0; pointer-events:none; z-index:0;
    opacity:.04; background-image:url("{grain}"); }}
  header, .navbar, main, footer {{ position:relative; z-index:1; }}
  .wrap {{ max-width:1180px; margin:0 auto; padding:0 20px; }}
  header {{ padding:40px 0 18px; }}
  h1 {{ margin:0; font-size:clamp(26px,4vw,40px); font-weight:700; letter-spacing:-.02em;
    line-height:1.15; text-wrap:balance;
    background:linear-gradient(92deg,#fff 30%,var(--accent)); -webkit-background-clip:text;
    background-clip:text; color:transparent; }}
  .sub {{ color:var(--muted); font-size:14px; margin-top:8px; font-variant-numeric:tabular-nums; }}
  .navbar {{ position:sticky; top:0; z-index:40; margin-top:14px;
    backdrop-filter:blur(14px); -webkit-backdrop-filter:blur(14px);
    background:rgba(9,9,11,.72); border-top:1px solid var(--line); border-bottom:1px solid var(--line); }}
  .tabs {{ display:flex; gap:8px; max-width:1180px; margin:0 auto; padding:12px 20px;
    overflow-x:auto; -webkit-overflow-scrolling:touch; scrollbar-width:none; }}
  .tabs::-webkit-scrollbar {{ display:none; }}
  .tabbtn {{ flex:0 0 auto; background:transparent; color:var(--muted);
    border:1px solid var(--line); border-radius:999px; padding:9px 16px; font:inherit;
    font-size:14px; font-weight:500; cursor:pointer; transition:all .3s var(--spring); }}
  .tabbtn:hover {{ color:var(--text); border-color:rgba(255,255,255,.18); }}
  .tabbtn.active {{ background:var(--accent-weak); color:var(--accent);
    border-color:rgba(224,164,88,.4); }}
  main {{ display:block; }}
  .panel {{ display:none; }}
  .panel.active {{ display:grid; max-width:1180px; margin:0 auto;
    grid-template-columns:repeat(auto-fill,minmax(260px,1fr)); gap:18px; padding:28px 20px 64px; }}
  @keyframes fadeUp {{ from {{ opacity:0; transform:translateY(16px); }} to {{ opacity:1; transform:none; }} }}
  .panel.active .card {{ animation:fadeUp .5s var(--spring) both; animation-delay:calc(var(--i) * 60ms); }}
  .card {{ position:relative; display:block; background:var(--surface); border:1px solid var(--line);
    border-radius:18px; overflow:hidden; text-decoration:none; color:inherit;
    box-shadow:inset 0 1px 0 rgba(255,255,255,.04), 0 12px 30px -16px rgba(0,0,0,.8);
    transition:transform .4s var(--spring), border-color .3s var(--spring), box-shadow .4s var(--spring); }}
  .card:hover {{ transform:translateY(-5px); border-color:rgba(224,164,88,.45);
    box-shadow:inset 0 1px 0 rgba(255,255,255,.06), 0 22px 44px -18px rgba(224,164,88,.28); }}
  .card:active {{ transform:translateY(-2px) scale(.99); }}
  .thumb {{ position:relative; aspect-ratio:16/9; background:#0c0c0f; overflow:hidden; }}
  .thumb img {{ width:100%; height:100%; object-fit:cover; display:block;
    transition:transform .5s var(--spring); }}
  .card:hover .thumb img {{ transform:scale(1.05); }}
  .thumb::after {{ content:""; position:absolute; inset:0;
    background:linear-gradient(to top, rgba(0,0,0,.55), transparent 45%); }}
  .noimg {{ width:100%; height:100%; display:grid; place-items:center; font-size:34px; opacity:.5; }}
  .rank {{ position:absolute; top:8px; left:10px; z-index:2; font-size:22px; font-weight:700;
    line-height:1; color:#fff; font-variant-numeric:tabular-nums;
    text-shadow:0 2px 8px rgba(0,0,0,.7); }}
  .play {{ position:absolute; inset:0; margin:auto; width:48px; height:48px; z-index:2;
    display:grid; place-items:center; border-radius:999px; color:#0a0a0a;
    background:rgba(255,255,255,.92); opacity:0; transform:scale(.8);
    transition:all .35s var(--spring); }}
  .card:hover .play {{ opacity:1; transform:scale(1); }}
  .tag {{ position:absolute; left:10px; bottom:10px; z-index:2; font-size:11px; font-weight:500;
    padding:4px 9px; border-radius:999px; color:#f2f2f4;
    background:rgba(20,20,23,.7); border:1px solid rgba(255,255,255,.12);
    backdrop-filter:blur(6px); -webkit-backdrop-filter:blur(6px); }}
  .body {{ padding:13px 14px 16px; }}
  .title {{ font-size:15px; font-weight:600; line-height:1.4; text-wrap:balance;
    display:-webkit-box; -webkit-line-clamp:2; -webkit-box-orient:vertical; overflow:hidden; }}
  .channel {{ color:var(--muted); font-size:12.5px; margin-top:6px; }}
  .meta {{ font-size:12.5px; margin-top:8px; color:var(--muted); font-variant-numeric:tabular-nums; }}
  .meta b {{ color:var(--accent); font-weight:600; }}
  .empty {{ color:var(--muted); font-size:14px; grid-column:1/-1; padding:32px 0; text-align:center; }}
  footer {{ color:#62626d; font-size:12.5px; padding:0 0 40px; }}
  @media (max-width: 600px) {{
    body {{ overflow-x:hidden; }}
    header {{ padding:28px 0 12px; }}
    .panel.active {{ grid-template-columns:1fr; gap:12px; padding:18px 16px 44px; }}
    .wrap {{ padding:0 16px; }}
    .tabs {{ padding:11px 16px; gap:7px; }}
    .card {{ display:flex; flex-direction:row; align-items:stretch; }}
    .thumb {{ width:44%; max-width:170px; flex:0 0 auto; }}
    .body {{ flex:1; min-width:0; padding:11px 13px; align-self:center; }}
    .title {{ font-size:14px; -webkit-line-clamp:3; }}
    .play {{ width:38px; height:38px; }}
    .rank {{ font-size:18px; }}
  }}
  @media (prefers-reduced-motion: reduce) {{
    html {{ scroll-behavior:auto; }}
    .panel.active .card {{ animation:none; }}
    * {{ transition:none !important; }}
  }}
</style></head><body>
<header><div class="wrap">
  <h1>🎵 데일리 뮤직 뉴스레터</h1>
  <div class="sub">{date_str} · 키워드 인기 영상 · 이번 달 누적 {fmt(total_videos)}개 수집</div>
</div></header>
<nav class="navbar"><div class="tabs">{btns}</div></nav>
<main>{panels}</main>
<footer><div class="wrap">YouTube via Apify · 매일 아침 자동 생성 · 카드를 누르면 영상으로 이동</div></footer>
<script>
  const panels = document.querySelectorAll('.panel');
  document.querySelectorAll('.tabbtn').forEach(b => b.addEventListener('click', () => {{
    const t = b.dataset.tab;
    document.querySelectorAll('.tabbtn').forEach(x => x.classList.toggle('active', x === b));
    panels.forEach(p => {{
      const on = p.id === 'panel-' + t;
      p.classList.toggle('active', on);
      if (on) p.querySelectorAll('.card').forEach(c => {{
        c.style.animation = 'none'; void c.offsetWidth; c.style.animation = '';
      }});
    }});
  }}));
</script></body></html>"""


# ---------- git push (GitHub Pages 자동 배포) ----------
def git_push():
    def g(*args):
        return subprocess.run(["/usr/bin/git", "-C", str(HERE), *args],
                              capture_output=True, text=True)
    if g("rev-parse", "--git-dir").returncode != 0:
        return  # git 저장소 아님 → 조용히 생략
    try:
        g("add", "-A")
        c = g("-c", "user.email=tmvkdlabszm@gmail.com", "-c", "user.name=tmvkdlabszm-gif",
              "commit", "-m", f"newsletter {TODAY.isoformat()}")
        if c.returncode != 0:
            log("git: 변경 없음 → 푸시 생략")
            return
        p = g("push", "origin", "main")
        if p.returncode == 0:
            log("git: 푸시 완료 → GitHub Pages 갱신됨")
        else:
            log(f"git push 실패: {(p.stderr or p.stdout).strip()[:200]}")
    except Exception as e:
        log(f"git_push 예외: {e}")


# ---------- main ----------
def main():
    cfg = load_json(KEYWORDS, {})
    themes = cfg.get("themes", {})
    max_results = int(cfg.get("max_results_per_keyword", 8))
    recent_days = int(cfg.get("recent_days", 7))
    budget = int(cfg.get("monthly_video_budget", 1200))

    history = load_json(HISTORY, {})
    state = load_json(STATE, {})
    month = TODAY.strftime("%Y-%m")
    if state.get("month") != month:
        state = {"month": month, "count": 0}

    fetched = 0
    if not DRY:
        token = get_token()
        if not token:
            log("APIFY_TOKEN 없음 → 수집 생략, 기존 history로 렌더만 진행")
        else:
            keywords = [(kw, theme) for theme, kws in themes.items() for kw in kws]
            for kw, theme in keywords:
                if state["count"] + max_results > budget:
                    log(f"월 예산({budget}) 도달 → '{kw}' 이후 수집 중단")
                    break
                try:
                    items = fetch_keyword(token, kw, max_results)
                    update_history(history, items, theme)
                    got = len(items)
                    fetched += got
                    state["count"] += got
                    log(f"수집: '{kw}' [{theme}] {got}개 (월 누적 {state['count']})")
                    time.sleep(1)
                except urllib.error.HTTPError as e:
                    log(f"수집 실패 '{kw}': HTTP {e.code} {e.reason}")
                except Exception as e:
                    log(f"수집 실패 '{kw}': {e}")
            save_json(HISTORY, history)
            save_json(STATE, state)

    views = rank_views(history, recent_days)
    page = render(views, state.get("count", 0))
    INDEX.write_text(page, encoding="utf-8")
    ARCHIVE.mkdir(exist_ok=True)
    (ARCHIVE / f"{TODAY.isoformat()}.html").write_text(page, encoding="utf-8")
    log(f"렌더 완료: 최근 {len(views['recent'])} · 전체 {len(views['all_time'])} · "
        f"뜨는중 {len(views['trending'])} (이번 실행 수집 {fetched}개)")
    git_push()


if __name__ == "__main__":
    main()
