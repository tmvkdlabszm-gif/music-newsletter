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
import json, os, sys, time, html, datetime, urllib.request, urllib.parse, urllib.error
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


def card_html(r, kind):
    title = html.escape(r.get("title", ""))
    channel = html.escape(r.get("channel", ""))
    theme = html.escape(r.get("theme", ""))
    url = html.escape(r.get("url", "#"))
    thumb = html.escape(r.get("thumbnail", ""))
    meta = f"조회 {fmt(r.get('views'))} · 👍 {fmt(r.get('likes'))}"
    if kind == "trending":
        meta = f"📈 +{fmt(r.get('delta'))} · 조회 {fmt(r.get('views'))}"
    elif kind == "recent":
        meta = f"{html.escape(r.get('published',''))} · 조회 {fmt(r.get('views'))}"
    thumb_tag = f'<img src="{thumb}" loading="lazy" alt="">' if thumb else ""
    return f"""<a class="card" href="{url}" target="_blank" rel="noopener">
      <div class="thumb">{thumb_tag}<span class="tag">{theme}</span></div>
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
            cards = "\n".join(card_html(r, key) for r in rows)
        else:
            note = "내일부터 데이터가 쌓입니다 (전일 대비 계산)" if key == "trending" else "아직 항목이 없습니다"
            cards = f'<p class="empty">{note}</p>'
        panels += f'<section class="panel{active}" id="panel-{key}">{cards}</section>'

    date_str = TODAY.isoformat()
    return f"""<!doctype html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>🎵 데일리 뮤직 뉴스레터 · {date_str}</title>
<style>
  :root {{ color-scheme: dark; }}
  * {{ box-sizing: border-box; }}
  body {{ margin:0; font-family:-apple-system,BlinkMacSystemFont,"Apple SD Gothic Neo",sans-serif;
    background:#0f1115; color:#e7e9ee; }}
  header {{ padding:24px 20px 8px; }}
  h1 {{ font-size:20px; margin:0 0 2px; }}
  .sub {{ color:#8b90a0; font-size:13px; }}
  .tabs {{ display:flex; gap:8px; padding:12px 20px; position:sticky; top:0;
    background:#0f1115; border-bottom:1px solid #1e2230; z-index:5; }}
  .tabbtn {{ background:#1a1e29; color:#c7ccda; border:1px solid #262b3a; border-radius:999px;
    padding:8px 14px; font-size:14px; cursor:pointer; }}
  .tabbtn.active {{ background:#3a6df0; color:#fff; border-color:#3a6df0; }}
  .panel {{ display:none; padding:16px 20px 40px; }}
  .panel.active {{ display:grid; grid-template-columns:repeat(auto-fill,minmax(240px,1fr)); gap:16px; }}
  .card {{ background:#151925; border:1px solid #222838; border-radius:14px; overflow:hidden;
    text-decoration:none; color:inherit; transition:transform .08s, border-color .08s; }}
  .card:hover {{ transform:translateY(-2px); border-color:#3a6df0; }}
  .thumb {{ position:relative; aspect-ratio:16/9; background:#0b0d12; }}
  .thumb img {{ width:100%; height:100%; object-fit:cover; display:block; }}
  .tag {{ position:absolute; left:8px; bottom:8px; background:rgba(0,0,0,.7);
    padding:3px 8px; border-radius:8px; font-size:11px; }}
  .body {{ padding:10px 12px 14px; }}
  .title {{ font-size:14px; font-weight:600; line-height:1.35;
    display:-webkit-box; -webkit-line-clamp:2; -webkit-box-orient:vertical; overflow:hidden; }}
  .channel {{ color:#9aa0b2; font-size:12px; margin-top:4px; }}
  .meta {{ font-size:12px; margin-top:6px; color:#7e8498; }}
  .empty {{ color:#7e8498; font-size:14px; grid-column:1/-1; }}
  footer {{ color:#5b6173; font-size:12px; padding:0 20px 28px; }}
  @media (max-width: 600px) {{
    body {{ overflow-x:hidden; }}
    header {{ padding:18px 14px 6px; }}
    h1 {{ font-size:18px; }}
    .sub {{ font-size:12px; }}
    .tabs {{ padding:10px 12px; gap:6px; overflow-x:auto; -webkit-overflow-scrolling:touch; }}
    .tabbtn {{ flex:0 0 auto; padding:10px 16px; font-size:14px; }}
    .panel.active {{ grid-template-columns:1fr; gap:10px; padding:12px 12px 32px; }}
    .card {{ display:flex; flex-direction:row; align-items:stretch; }}
    .thumb {{ width:42%; max-width:160px; flex:0 0 auto; }}
    .body {{ flex:1; min-width:0; padding:9px 11px; }}
    .title {{ font-size:14px; -webkit-line-clamp:3; }}
    .channel {{ font-size:12px; }}
    .tag {{ font-size:10px; left:6px; bottom:6px; padding:2px 6px; }}
  }}
</style></head><body>
<header>
  <h1>🎵 데일리 뮤직 뉴스레터</h1>
  <div class="sub">{date_str} · 키워드 인기 영상 · 이번 달 누적 {fmt(total_videos)}개 수집</div>
</header>
<nav class="tabs">{btns}</nav>
{panels}
<footer>YouTube via Apify · 매일 자동 생성 · 카드를 누르면 영상으로 이동</footer>
<script>
  document.querySelectorAll('.tabbtn').forEach(b => b.addEventListener('click', () => {{
    const t = b.dataset.tab;
    document.querySelectorAll('.tabbtn').forEach(x => x.classList.toggle('active', x===b));
    document.querySelectorAll('.panel').forEach(p =>
      p.classList.toggle('active', p.id === 'panel-'+t));
  }}));
</script></body></html>"""


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


if __name__ == "__main__":
    main()
