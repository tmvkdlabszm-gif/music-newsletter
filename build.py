#!/usr/bin/env python3
"""
데일리 뮤직 뉴스레터 빌더 — 멀티 플랫폼 (TikTok · Instagram · Reddit).

플랫폼별 키워드로 하루 1번 인기 게시물을 Apify로 수집하고, history.json에 누적해
3개 뷰(최근/전체/뜨는중)를 추가 비용 없이 계산한 뒤, supanova 스타일의 단일 HTML로
렌더한다. 결과는 GitHub Pages로 자동 푸시된다.

사용:
  python3 build.py          # 평소 실행 (수집 + 렌더 + 푸시)
  python3 build.py --once   # 동일 (수동 트리거 명시용)
  python3 build.py --dry    # 수집 없이 기존 history로 렌더만

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

TODAY = datetime.date.today()
DRY = "--dry" in sys.argv

# 플랫폼 정의: 액터 ID, 단가($/결과), 실행 시작비($), 인기 지표 라벨, 보조 지표 라벨, 탭 이모지
PLATFORMS = {
    "tiktok":    {"actor": "clockworks~tiktok-scraper", "unit": 0.0037, "start": 0.001,
                  "score": "재생", "second": "좋아요", "label": "TikTok", "emoji": "🎵"},
    "instagram": {"actor": "apify~instagram-scraper",   "unit": 0.0027, "start": 0.0,
                  "score": "좋아요", "second": "댓글", "label": "Instagram", "emoji": "📸"},
    "reddit":    {"actor": "harshmaur~reddit-scraper",  "unit": 0.002,  "start": 0.02,
                  "score": "업보트", "second": "댓글", "label": "Reddit", "emoji": "👽"},
}
VIEWS = [("recent", "🆕 최근 인기"), ("all_time", "🔥 전체 인기"), ("trending", "📈 뜨는 중")]


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
            if ln.strip().startswith("APIFY_TOKEN"):
                return ln.split("=", 1)[1].strip().strip('"').strip("'")
    return None


def first(d, *keys, default=None):
    for k in keys:
        v = d.get(k)
        if v not in (None, "", []):
            return v
    return default


def to_date(val):
    """ISO 문자열 또는 epoch(초)를 YYYY-MM-DD로."""
    if val in (None, ""):
        return ""
    try:
        if isinstance(val, (int, float)) or (isinstance(val, str) and val.isdigit()):
            return datetime.datetime.utcfromtimestamp(int(val)).date().isoformat()
        return str(val)[:10]
    except (ValueError, OSError):
        return ""


# ---------- Apify 호출 ----------
def run_actor(token, actor, payload):
    url = (f"https://api.apify.com/v2/acts/{actor}/run-sync-get-dataset-items"
           f"?token={urllib.parse.quote(token)}")
    req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"),
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=300) as resp:
        return json.loads(resp.read().decode("utf-8"))


# ---------- 플랫폼별 어댑터: 원시 결과 → 표준 아이템 ----------
def norm_tiktok(it):
    am = it.get("authorMeta") or {}
    vm = it.get("videoMeta") or {}
    return {
        "id": "tiktok:" + str(first(it, "id", "webVideoUrl", default="")),
        "platform": "tiktok",
        "title": first(it, "text", default="(제목 없음)"),
        "channel": first(am, "nickName", "name", default=""),
        "url": first(it, "webVideoUrl", default="#"),
        "thumbnail": first(vm, "coverUrl", "originalCoverUrl") or "",
        "published": to_date(first(it, "createTimeISO", "createTime")),
        "score": int(first(it, "playCount", default=0) or 0),
        "second": int(first(it, "diggCount", default=0) or 0),
    }


def norm_instagram(it):
    return {
        "id": "instagram:" + str(first(it, "id", "shortCode", "url", default="")),
        "platform": "instagram",
        "title": first(it, "caption", default="(캡션 없음)"),
        "channel": first(it, "ownerUsername", default=""),
        "url": first(it, "url", default="#"),
        "thumbnail": first(it, "displayUrl", "thumbnailUrl") or "",
        "published": to_date(first(it, "timestamp")),
        "score": int(first(it, "likesCount", "videoViewCount", "videoPlayCount", default=0) or 0),
        "second": int(first(it, "commentsCount", default=0) or 0),
    }


def norm_reddit(it):
    comm = first(it, "communityName", "subreddit", "parsedCommunityName", default="")
    comm = comm if str(comm).startswith("r/") else ("r/" + str(comm) if comm else "Reddit")
    return {
        "id": "reddit:" + str(first(it, "id", "postId", "url", default="")),
        "platform": "reddit",
        "title": first(it, "title", default="(제목 없음)"),
        "channel": comm,
        "url": first(it, "url", "link", default="#"),
        "thumbnail": first(it, "thumbnailUrl", "thumbnail", "image") or "",
        "published": to_date(first(it, "createdAt", "created", "createdAtUtc")),
        "score": int(first(it, "upVotes", "score", "ups", default=0) or 0),
        "second": int(first(it, "numberOfComments", "numComments", "commentsCount", default=0) or 0),
    }


def payload_for(platform, kw, n):
    if platform == "tiktok":
        return {"searchQueries": [kw], "searchSection": "/video", "resultsPerPage": n}
    if platform == "instagram":
        tag = kw.lstrip("#").replace(" ", "")
        return {"directUrls": [f"https://www.instagram.com/explore/tags/{tag}/"],
                "resultsType": "posts", "resultsLimit": n}
    if platform == "reddit":
        return {"searchTerms": [kw], "searchPosts": True, "searchSort": "top",
                "searchTime": "month", "maxPostsCount": n}
    return {}


NORMALIZERS = {"tiktok": norm_tiktok, "instagram": norm_instagram, "reddit": norm_reddit}


def fetch(token, platform, kw, n):
    raw = run_actor(token, PLATFORMS[platform]["actor"], payload_for(platform, kw, n))
    norm = NORMALIZERS[platform]
    out = []
    for it in raw:
        try:
            row = norm(it)
            if row["id"] and row["id"] != f"{platform}:":
                out.append(row)
        except Exception:
            continue
    return out


# ---------- history / ranking ----------
def update_history(history, items):
    today = TODAY.isoformat()
    for it in items:
        rec = history.get(it["id"])
        if rec:
            rec["prev_score"] = rec.get("score", it["score"])
            rec["score"] = it["score"]
            rec["second"] = it["second"]
            rec["last_seen"] = today
        else:
            it = dict(it, first_seen=today, last_seen=today, prev_score=None)
            history[it["id"]] = it


def rank_platform(history, platform, recent_days):
    rows = [dict(r) for r in history.values() if r.get("platform") == platform]
    all_time = sorted(rows, key=lambda r: r.get("score") or 0, reverse=True)[:5]

    cutoff = TODAY - datetime.timedelta(days=recent_days)
    def is_recent(r):
        try:
            return datetime.date.fromisoformat(r["published"]) >= cutoff
        except (ValueError, KeyError, TypeError):
            return False
    recent = sorted([r for r in rows if is_recent(r)],
                    key=lambda r: r.get("score") or 0, reverse=True)[:5]

    trend = []
    for r in rows:
        pv = r.get("prev_score")
        if pv is not None and (r.get("score") or 0) - pv > 0:
            trend.append(dict(r, delta=(r["score"] - pv)))
    trending = sorted(trend, key=lambda r: r["delta"], reverse=True)[:5]
    return {"recent": recent, "all_time": all_time, "trending": trending}


# ---------- render ----------
def fmt(n):
    try:
        return f"{int(n):,}"
    except (ValueError, TypeError):
        return "0"


def card_html(r, kind, rank):
    p = PLATFORMS[r["platform"]]
    title = html.escape(r.get("title", "") or "")
    channel = html.escape(r.get("channel", "") or "")
    url = html.escape(r.get("url", "#") or "#")
    thumb = html.escape(r.get("thumbnail", "") or "")
    if kind == "trending":
        meta = f"<b>+{fmt(r.get('delta'))}</b> {p['score']} · 누적 {fmt(r.get('score'))}"
    elif kind == "recent":
        meta = f"{html.escape(r.get('published',''))} · {p['score']} {fmt(r.get('score'))}"
    else:
        meta = f"{p['score']} {fmt(r.get('score'))} · 💬 {fmt(r.get('second'))}"
    thumb_tag = (f'<img src="{thumb}" loading="lazy" alt="{title}" '
                 f'onerror="this.parentNode.classList.add(&quot;broken&quot;)">'
                 if thumb else '')
    return f"""<a class="card" style="--i:{rank}" href="{url}" target="_blank" rel="noopener">
      <div class="thumb">{thumb_tag}<span class="ph">{p['emoji']}</span>
        <span class="rank">{rank}</span>
        <span class="play"><svg viewBox="0 0 24 24" width="22" height="22" fill="currentColor"><path d="M8 5v14l11-7z"/></svg></span>
        <span class="tag">{p['emoji']} {html.escape(p['label'])}</span>
      </div>
      <div class="body"><div class="title">{title}</div>
        <div class="channel">{channel}</div><div class="meta">{meta}</div></div>
    </a>"""


def render(ranks, spent, budget):
    btns, blocks = "", ""
    for i, (pid, p) in enumerate(PLATFORMS.items()):
        act = " active" if i == 0 else ""
        btns += f'<button class="tabbtn{act}" data-pf="{pid}">{p["emoji"]} {p["label"]}</button>'
        sections = ""
        idx = 0
        for vkey, vlabel in VIEWS:
            rows = ranks[pid][vkey]
            if rows:
                cards = ""
                for r in rows:
                    idx += 1
                    cards += card_html(r, vkey, idx)
            else:
                note = ("내일부터 데이터가 쌓입니다 (전일 대비 계산)"
                        if vkey == "trending" else "아직 항목이 없습니다")
                cards = f'<p class="empty">{note}</p>'
            sections += f'<h2 class="vhead">{vlabel}</h2><div class="row">{cards}</div>'
        blocks += f'<section class="platform{act}" id="pf-{pid}">{sections}</section>'

    date_str = TODAY.isoformat()
    favicon = ("data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'>"
               "<text y='.9em' font-size='90'>🎵</text></svg>")
    grain = ("data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' width='160' height='160'>"
             "<filter id='n'><feTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='2'/>"
             "</filter><rect width='100%25' height='100%25' filter='url(%23n)'/></svg>")
    return f"""<!doctype html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="description" content="매일 자동 정리되는 음악 인기 게시물 — TikTok·Instagram·Reddit">
<meta property="og:title" content="데일리 뮤직 뉴스레터">
<title>데일리 뮤직 뉴스레터 · {date_str}</title>
<link rel="icon" href="{favicon}">
<link rel="preconnect" href="https://cdn.jsdelivr.net">
<link rel="stylesheet" href="https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/static/pretendard.min.css">
<style>
  :root {{
    color-scheme:dark;
    --bg:#09090b; --surface:#141417; --line:rgba(255,255,255,.07);
    --text:#ededf0; --muted:#9a9aa6; --accent:#e0a458; --accent-weak:rgba(224,164,88,.14);
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
  .tabbtn {{ flex:0 0 auto; background:transparent; color:var(--muted); border:1px solid var(--line);
    border-radius:999px; padding:9px 16px; font:inherit; font-size:14px; font-weight:500;
    cursor:pointer; transition:all .3s var(--spring); }}
  .tabbtn:hover {{ color:var(--text); border-color:rgba(255,255,255,.18); }}
  .tabbtn.active {{ background:var(--accent-weak); color:var(--accent); border-color:rgba(224,164,88,.4); }}
  .platform {{ display:none; max-width:1180px; margin:0 auto; padding:8px 20px 64px; }}
  .platform.active {{ display:block; }}
  .vhead {{ font-size:15px; font-weight:600; color:var(--text); margin:28px 2px 14px;
    padding-bottom:8px; border-bottom:1px solid var(--line); }}
  .row {{ display:grid; grid-template-columns:repeat(auto-fill,minmax(260px,1fr)); gap:18px; }}
  @keyframes fadeUp {{ from {{ opacity:0; transform:translateY(16px); }} to {{ opacity:1; transform:none; }} }}
  .platform.active .card {{ animation:fadeUp .5s var(--spring) both; animation-delay:calc(var(--i) * 45ms); }}
  .card {{ position:relative; display:block; background:var(--surface); border:1px solid var(--line);
    border-radius:18px; overflow:hidden; text-decoration:none; color:inherit;
    box-shadow:inset 0 1px 0 rgba(255,255,255,.04), 0 12px 30px -16px rgba(0,0,0,.8);
    transition:transform .4s var(--spring), border-color .3s var(--spring), box-shadow .4s var(--spring); }}
  .card:hover {{ transform:translateY(-5px); border-color:rgba(224,164,88,.45);
    box-shadow:inset 0 1px 0 rgba(255,255,255,.06), 0 22px 44px -18px rgba(224,164,88,.28); }}
  .card:active {{ transform:translateY(-2px) scale(.99); }}
  .thumb {{ position:relative; aspect-ratio:16/9; background:#0c0c0f; overflow:hidden;
    display:grid; place-items:center; }}
  .thumb img {{ position:relative; z-index:1; width:100%; height:100%; object-fit:cover; display:block;
    transition:transform .5s var(--spring); }}
  .card:hover .thumb img {{ transform:scale(1.05); }}
  .ph {{ position:absolute; font-size:34px; opacity:.4; z-index:0; }}
  .thumb.broken img {{ display:none; }}
  .thumb::after {{ content:""; position:absolute; inset:0; z-index:1;
    background:linear-gradient(to top, rgba(0,0,0,.55), transparent 45%); }}
  .rank {{ position:absolute; top:8px; left:10px; z-index:3; font-size:22px; font-weight:700;
    line-height:1; color:#fff; font-variant-numeric:tabular-nums; text-shadow:0 2px 8px rgba(0,0,0,.7); }}
  .play {{ position:absolute; inset:0; margin:auto; width:48px; height:48px; z-index:3; display:grid;
    place-items:center; border-radius:999px; color:#0a0a0a; background:rgba(255,255,255,.92);
    opacity:0; transform:scale(.8); transition:all .35s var(--spring); }}
  .card:hover .play {{ opacity:1; transform:scale(1); }}
  .tag {{ position:absolute; left:10px; bottom:10px; z-index:3; font-size:11px; font-weight:500;
    padding:4px 9px; border-radius:999px; color:#f2f2f4; background:rgba(20,20,23,.7);
    border:1px solid rgba(255,255,255,.12); backdrop-filter:blur(6px); }}
  .body {{ padding:13px 14px 16px; }}
  .title {{ font-size:15px; font-weight:600; line-height:1.4; text-wrap:balance;
    display:-webkit-box; -webkit-line-clamp:2; -webkit-box-orient:vertical; overflow:hidden; }}
  .channel {{ color:var(--muted); font-size:12.5px; margin-top:6px; }}
  .meta {{ font-size:12.5px; margin-top:8px; color:var(--muted); font-variant-numeric:tabular-nums; }}
  .meta b {{ color:var(--accent); font-weight:600; }}
  .empty {{ color:var(--muted); font-size:14px; padding:10px 2px 4px; }}
  footer {{ color:#62626d; font-size:12.5px; padding:0 0 40px; }}
  @media (max-width:600px) {{
    body {{ overflow-x:hidden; }}
    header {{ padding:28px 0 12px; }}
    .platform {{ padding:6px 16px 44px; }}
    .wrap {{ padding:0 16px; }}
    .tabs {{ padding:11px 16px; gap:7px; }}
    .row {{ grid-template-columns:1fr; gap:12px; }}
    .card {{ display:flex; flex-direction:row; align-items:stretch; }}
    .thumb {{ width:44%; max-width:170px; flex:0 0 auto; }}
    .body {{ flex:1; min-width:0; padding:11px 13px; align-self:center; }}
    .title {{ font-size:14px; -webkit-line-clamp:3; }}
    .play {{ width:38px; height:38px; }}
    .rank {{ font-size:18px; }}
  }}
  @media (prefers-reduced-motion:reduce) {{
    html {{ scroll-behavior:auto; }} .platform.active .card {{ animation:none; }}
    * {{ transition:none !important; }}
  }}
</style></head><body>
<header><div class="wrap">
  <h1>🎵 데일리 뮤직 뉴스레터</h1>
  <div class="sub">{date_str} · TikTok · Instagram · Reddit · 이번 달 ${spent:.2f} / ${budget:.2f}</div>
</div></header>
<nav class="navbar"><div class="tabs">{btns}</div></nav>
<main>{blocks}</main>
<footer><div class="wrap">Apify 수집 · 매일 아침 자동 생성 · 카드를 누르면 원본으로 이동</div></footer>
<script>
  const pfs = document.querySelectorAll('.platform');
  document.querySelectorAll('.tabbtn').forEach(b => b.addEventListener('click', () => {{
    const t = b.dataset.pf;
    document.querySelectorAll('.tabbtn').forEach(x => x.classList.toggle('active', x === b));
    pfs.forEach(p => {{
      const on = p.id === 'pf-' + t;
      p.classList.toggle('active', on);
      if (on) p.querySelectorAll('.card').forEach(c => {{
        c.style.animation = 'none'; void c.offsetWidth; c.style.animation = '';
      }});
    }});
  }}));
</script></body></html>"""


# ---------- git push ----------
def git_push():
    def g(*a):
        return subprocess.run(["/usr/bin/git", "-C", str(HERE), *a], capture_output=True, text=True)
    if g("rev-parse", "--git-dir").returncode != 0:
        return
    try:
        g("add", "-A")
        c = g("-c", "user.email=tmvkdlabszm@gmail.com", "-c", "user.name=tmvkdlabszm-gif",
              "commit", "-m", f"newsletter {TODAY.isoformat()}")
        if c.returncode != 0:
            log("git: 변경 없음 → 푸시 생략"); return
        p = g("push", "origin", "main")
        log("git: 푸시 완료 → GitHub Pages 갱신됨" if p.returncode == 0
            else f"git push 실패: {(p.stderr or p.stdout).strip()[:200]}")
    except Exception as e:
        log(f"git_push 예외: {e}")


# ---------- main ----------
def main():
    cfg = load_json(KEYWORDS, {})
    pf_cfg = cfg.get("platforms", {})
    recent_days = int(cfg.get("recent_days", 7))
    budget = float(cfg.get("monthly_budget_usd", 4.5))

    history = load_json(HISTORY, {})
    state = load_json(STATE, {})
    month = TODAY.strftime("%Y-%m")
    if state.get("month") != month:
        state = {"month": month, "spent": 0.0}

    fetched = 0
    if not DRY:
        token = get_token()
        if not token:
            log("APIFY_TOKEN 없음 → 수집 생략, 기존 history로 렌더만 진행")
        else:
            for pid in PLATFORMS:
                conf = pf_cfg.get(pid, {})
                kws = conf.get("keywords", [])
                n = int(conf.get("max_results", 8))
                unit, start = PLATFORMS[pid]["unit"], PLATFORMS[pid]["start"]
                for kw in kws:
                    est = start + unit * n
                    if state["spent"] + est > budget:
                        log(f"월 예산(${budget}) 도달 → {pid}/'{kw}' 이후 수집 중단")
                        break
                    try:
                        items = fetch(token, pid, kw, n)
                        update_history(history, items)
                        got = len(items)
                        fetched += got
                        state["spent"] += start + unit * got
                        log(f"수집: {pid} · '{kw}' {got}개 (누적 ${state['spent']:.2f})")
                        time.sleep(1)
                    except urllib.error.HTTPError as e:
                        log(f"수집 실패 {pid}/'{kw}': HTTP {e.code} {e.reason}")
                    except Exception as e:
                        log(f"수집 실패 {pid}/'{kw}': {e}")
            save_json(HISTORY, history)
            save_json(STATE, state)

    ranks = {pid: rank_platform(history, pid, recent_days) for pid in PLATFORMS}
    page = render(ranks, state.get("spent", 0.0), budget)
    INDEX.write_text(page, encoding="utf-8")
    ARCHIVE.mkdir(exist_ok=True)
    (ARCHIVE / f"{TODAY.isoformat()}.html").write_text(page, encoding="utf-8")
    summary = " · ".join(
        f"{PLATFORMS[p]['label']} {sum(len(ranks[p][v]) for v,_ in VIEWS)}" for p in PLATFORMS)
    log(f"렌더 완료: {summary} (이번 실행 수집 {fetched}개)")
    git_push()


if __name__ == "__main__":
    main()
