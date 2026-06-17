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
import json, os, sys, time, html, re, datetime, subprocess, urllib.request, urllib.parse, urllib.error
from pathlib import Path

HERE = Path(__file__).resolve().parent
KEYWORDS = HERE / "keywords.json"
HISTORY = HERE / "history.json"
STATE = HERE / "state.json"
INDEX = HERE / "index.html"
ARCHIVE = HERE / "archive"
LOG = HERE / "build.log"
SUMMARIES = HERE / "summaries.json"
SUMMARY_LOG = HERE / "summary_log.json"
ENV = Path.home() / ".config" / "music-newsletter" / ".env"
ANTHROPIC_MODEL = "claude-opus-4-8"

TODAY = datetime.date.today()
DRY = "--dry" in sys.argv

# 플랫폼 정의: 액터 ID, 단가($/결과), 실행 시작비($), 인기 지표 라벨, 보조 지표 라벨, 탭 이모지
PLATFORMS = {
    "tiktok":    {"actor": "clockworks~tiktok-scraper", "unit": 0.0037, "start": 0.001,
                  "score": "재생", "second": "좋아요", "label": "TikTok"},
    "instagram": {"actor": "apify~instagram-scraper",   "unit": 0.0027, "start": 0.0,
                  "score": "좋아요", "second": "댓글", "label": "Instagram"},
    "reddit":    {"actor": "harshmaur~reddit-scraper",  "unit": 0.002,  "start": 0.02,
                  "score": "업보트", "second": "댓글", "label": "Reddit"},
}
VIEWS = [("recent", "최근 인기"), ("all_time", "전체 인기"), ("trending", "뜨는 중")]

# ---- Carbon UI 아이콘 (단색 currentColor, viewBox 0 0 32 32) ----
# tiktok/reddit는 Carbon에 로고가 없어 music/forum으로 대체
PLATFORM_ICON = {
    "tiktok": '<svg class="tic" viewBox="0 0 32 32" fill="currentColor"><path d="M25,4H10A2.002,2.002,0,0,0,8,6V20.5563A3.9551,3.9551,0,0,0,6,20a4,4,0,1,0,4,4V12H25v8.5562A3.9545,3.9545,0,0,0,23,20a4,4,0,1,0,4,4V6A2.0023,2.0023,0,0,0,25,4ZM6,26a2,2,0,1,1,2-2A2.0023,2.0023,0,0,1,6,26Zm17,0a2,2,0,1,1,2-2A2.0027,2.0027,0,0,1,23,26ZM10,6H25v4H10Z"/></svg>',
    "instagram": '<svg class="tic" viewBox="0 0 32 32" fill="currentColor"><circle cx="22.406" cy="9.594" r="1.44"/><path d="M16,9.8378A6.1622,6.1622,0,1,0,22.1622,16,6.1622,6.1622,0,0,0,16,9.8378ZM16,20a4,4,0,1,1,4-4A4,4,0,0,1,16,20Z"/><path d="M16,6.1622c3.2041,0,3.5837.0122,4.849.07a6.6418,6.6418,0,0,1,2.2283.4132,3.9748,3.9748,0,0,1,2.2774,2.2774,6.6418,6.6418,0,0,1,.4132,2.2283c.0577,1.2653.07,1.6449.07,4.849s-.0122,3.5837-.07,4.849a6.6418,6.6418,0,0,1-.4132,2.2283,3.9748,3.9748,0,0,1-2.2774,2.2774,6.6418,6.6418,0,0,1-2.2283.4132c-1.2652.0577-1.6446.07-4.849.07s-3.5838-.0122-4.849-.07a6.6418,6.6418,0,0,1-2.2283-.4132,3.9748,3.9748,0,0,1-2.2774-2.2774,6.6418,6.6418,0,0,1-.4132-2.2283c-.0577-1.2653-.07-1.6449-.07-4.849s.0122-3.5837.07-4.849a6.6418,6.6418,0,0,1,.4132-2.2283A3.9748,3.9748,0,0,1,8.9227,6.6453a6.6418,6.6418,0,0,1,2.2283-.4132c1.2653-.0577,1.6449-.07,4.849-.07M16,4c-3.259,0-3.6677.0138-4.9476.0722A8.8068,8.8068,0,0,0,8.14,4.63,6.1363,6.1363,0,0,0,4.63,8.14a8.8068,8.8068,0,0,0-.5578,2.9129C4.0138,12.3323,4,12.741,4,16s.0138,3.6677.0722,4.9476A8.8074,8.8074,0,0,0,4.63,23.8605a6.1363,6.1363,0,0,0,3.51,3.51,8.8068,8.8068,0,0,0,2.9129.5578C12.3323,27.9862,12.741,28,16,28s3.6677-.0138,4.9476-.0722a8.8074,8.8074,0,0,0,2.9129-.5578,6.1363,6.1363,0,0,0,3.51-3.51,8.8074,8.8074,0,0,0,.5578-2.9129C27.9862,19.6677,28,19.259,28,16s-.0138-3.6677-.0722-4.9476A8.8068,8.8068,0,0,0,27.37,8.14a6.1363,6.1363,0,0,0-3.51-3.5095,8.8074,8.8074,0,0,0-2.9129-.5578C19.6677,4.0138,19.259,4,16,4Z"/></svg>',
    "reddit": '<svg class="tic" viewBox="0 0 32 32" fill="currentColor"><path d="M28,6H8C6.8,6,6,6.8,6,8v14c0,1.2,0.8,2,2,2h8v-2H8V8h20v14h-7.2L16,28.8l1.6,1.2l4.2-6H28c1.2,0,2-0.8,2-2V8C30,6.8,29.2,6,28,6z"/><path d="M4,18H2V5c0-1.7,1.3-3,3-3h13v2H5C4.4,4,4,4.4,4,5V18z"/></svg>',
}
VHEAD_ICON = {
    "recent": '<svg class="hic hic-cyan" viewBox="0 0 32 32" fill="currentColor"><path d="M20.59 22 15 16.41 15 7 17 7 17 15.58 22 20.59 20.59 22z"/><path d="M16,2A13.94,13.94,0,0,0,6,6.23V2H4v8h8V8H7.08A12,12,0,1,1,4,16H2A14,14,0,1,0,16,2Z"/></svg>',
    "all_time": '<svg class="hic hic-pink" viewBox="0 0 32 32" fill="currentColor"><path d="M26,7H24V6a2.0023,2.0023,0,0,0-2-2H10A2.0023,2.0023,0,0,0,8,6V7H6A2.0023,2.0023,0,0,0,4,9v3a4.0045,4.0045,0,0,0,4,4h.322A8.1689,8.1689,0,0,0,15,21.9341V26H10v2H22V26H17V21.9311A7.9661,7.9661,0,0,0,23.74,16H24a4.0045,4.0045,0,0,0,4-4V9A2.0023,2.0023,0,0,0,26,7ZM8,14a2.0023,2.0023,0,0,1-2-2V9H8Zm14,0a6,6,0,0,1-6.1855,5.9971A6.1991,6.1991,0,0,1,10,13.7065V6H22Zm4-2a2.0023,2.0023,0,0,1-2,2V9h2Z"/></svg>',
    "trending": '<svg class="hic hic-amber" viewBox="0 0 32 32" fill="currentColor"><path d="M4.67,28l6.39-12,7.3,6.49a2,2,0,0,0,1.7.47,2,2,0,0,0,1.42-1.07L27,10.9,25.18,10,19.69,21l-7.3-6.49A2,2,0,0,0,10.71,14a2,2,0,0,0-1.42,1L4,25V2H2V28a2,2,0,0,0,2,2H30V28Z"/></svg>',
}
# 섹션 헤더용 아이콘
IC_DOC = '<svg class="hic hic-pink" viewBox="0 0 32 32" fill="currentColor"><path d="M25.7,9.3l-7-7C18.5,2.1,18.3,2,18,2H8C6.9,2,6,2.9,6,4v24c0,1.1,0.9,2,2,2h16c1.1,0,2-0.9,2-2V10C26,9.7,25.9,9.5,25.7,9.3z M18,4.4l5.6,5.6H18V4.4z M24,28H8V4h8v6c0,1.1,0.9,2,2,2h6V28z"/><path d="M10 22H22V24H10z"/><path d="M10 16H22V18H10z"/></svg>'
IC_EYE = '<svg class="hic hic-cyan" style="width:16px;height:16px;vertical-align:-3px;margin-right:6px" viewBox="0 0 32 32" fill="currentColor"><path d="M30.94,15.66A16.69,16.69,0,0,0,16,5,16.69,16.69,0,0,0,1.06,15.66a1,1,0,0,0,0,.68A16.69,16.69,0,0,0,16,27,16.69,16.69,0,0,0,30.94,16.34,1,1,0,0,0,30.94,15.66ZM16,25c-5.3,0-10.9-3.93-12.93-9C5.1,10.93,10.7,7,16,7s10.9,3.93,12.93,9C26.9,21.07,21.3,25,16,25Z"/><path d="M16,10a6,6,0,1,0,6,6A6,6,0,0,0,16,10Zm0,10a4,4,0,1,1,4-4A4,4,0,0,1,16,20Z"/></svg>'


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


def _env_value(name):
    v = os.environ.get(name)
    if v:
        return v.strip()
    if ENV.exists():
        for ln in ENV.read_text(encoding="utf-8").splitlines():
            if ln.strip().startswith(name):
                return ln.split("=", 1)[1].strip().strip('"').strip("'")
    return None


def get_token():
    return _env_value("APIFY_TOKEN")


def get_anthropic_key():
    return _env_value("ANTHROPIC_API_KEY")


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
        "url": first(it, "postUrl", "url", "link", default="#"),
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
        # kw는 서브레딧 이름 묶음(list). 각 음악 서브레딧의 '주간 인기'를 한 run으로 수집.
        subs = kw if isinstance(kw, list) else [kw]
        urls = []
        for s in subs:
            name = str(s).strip().strip("/")
            if name.startswith("r/"):
                name = name[2:]
            if name:
                urls.append({"url": f"https://www.reddit.com/r/{name}/top/?t=week"})
        return {"startUrls": urls, "maxPostsCount": n}
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


# ---------- 요약: 3줄 트렌드 + 꼭 봐야 할 게시물 1개 (Claude 우선 → 폴백) ----------
import re as _re, collections as _collections

_STOP = set(("the a an of to in for and or is on with your you my this that it i we "
             "music song songs new how what why best top mix feat official video "
             "about who when from are was has have not but all out get got make made "
             "una que por der die und las los con para más muy son una uno like just "
             "이 그 저 및 ft vs").split())

CLAUDE_BIN = str(Path.home() / ".local" / "bin" / "claude")

_SUMMARY_SYSTEM = (
    "너는 음악 트렌드 분석가다. 아래 번호가 매겨진 '오늘 수집된 게시물' 목록을 보고 한국어로 출력한다.\n"
    "- 1~3번째 줄: 그날의 흐름을 요약한 간결한 세 문장. 각 줄에 한 문장씩, 반드시 줄바꿈으로 분리.\n"
    "- 4번째 줄: 오늘 '꼭 봐야 할' 게시물 하나를 골라 정확히 다음 형식으로 출력 → PICK|<번호>|<왜 봐야 하는지 한 문장>\n"
    "- 5번째 줄: 그 게시물이 왜 떴는지 한 문장 → WHY|<문장>\n"
    "- 6번째 줄: 그 게시물의 핵심 포인트 한 문장 → POINT|<문장>\n"
    "- 7번째 줄: 내 음악 작업에 따라해볼 점 한 문장 → APPLY|<문장>\n"
    "불릿·서론·다른 설명 없이 정확히 7줄만 출력한다.")


def _ordered(items):
    return sorted(items, key=lambda r: r.get("score") or 0, reverse=True)[:25]


def _summary_listing(ordered):
    return "\n".join(
        f"{i}. {(it.get('title') or '')[:90]} | {it.get('channel','')} | 인기 {it.get('score',0):,}"
        for i, it in enumerate(ordered, 1))


def _parse_summary(text, ordered):
    if not text or "Not logged in" in text or "/login" in text:
        return None
    lines, pick = [], None
    analysis = {}
    for raw in text.splitlines():
        s = raw.strip(" -•\t").strip()
        if not s:
            continue
        up = s.upper()
        if up.startswith("PICK") and "|" in s:
            parts = s.split("|")
            m = _re.search(r"\d+", parts[1]) if len(parts) > 1 else None
            reason = parts[2].strip() if len(parts) > 2 else ""
            if m:
                idx = int(m.group()) - 1
                if 0 <= idx < len(ordered):
                    it = ordered[idx]
                    pick = {"title": (it.get("title") or "")[:80], "url": it.get("url", "#"),
                            "channel": it.get("channel", ""), "reason": reason}
        elif up.startswith(("WHY", "POINT", "APPLY")) and "|" in s:
            key, val = s.split("|", 1)
            analysis[key.strip().lower()] = val.strip()
        else:
            lines.append(s)
    lines = lines[:3]
    if not lines:
        return None
    if pick and analysis:
        pick["analysis"] = analysis
    return {"lines": lines, "pick": pick}


def _summarize_heuristic(label, items):
    if not items:
        return None
    ordered = _ordered(items)
    n = len(items)
    scores = [it.get("score") or 0 for it in items]
    top = ordered[0]
    slabel = PLATFORMS.get(items[0].get("platform", ""), {}).get("score", "인기")
    words = []
    for it in items:
        for w in _re.findall(r"[A-Za-z가-힣]{3,}", (it.get("title") or "").lower()):
            if w not in _STOP:
                words.append(w)
    common = [w for w, _ in _collections.Counter(words).most_common(4)]
    lines = [
        f"가장 화제: '{(top.get('title') or '')[:48]}' — {top.get('channel','')} ({slabel} {fmt(top.get('score'))})",
        f"오늘 {n}건 수집 · 평균 {slabel} {fmt(sum(scores)//n if n else 0)} · 최고 {fmt(max(scores) if scores else 0)}",
        ("자주 등장: " + ", ".join(common)) if common else "다양한 주제가 고르게 분포",
    ]
    pick = {"title": (top.get("title") or "")[:80], "url": top.get("url", "#"),
            "channel": top.get("channel", ""), "reason": f"오늘 가장 높은 {slabel} {fmt(top.get('score'))}",
            "analysis": {
                "why": f"오늘 수집분 중 {slabel}가 가장 높음 ({fmt(top.get('score'))}).",
                "point": f"{top.get('channel','')}의 게시물" + (f" — 자주 등장: {', '.join(common)}" if common else "") + ".",
                "apply": "상위 게시물의 포맷·키워드를 내 작업 방향의 참고점으로 활용.",
            }}
    return {"lines": lines, "pick": pick}


def summarize(label, items):
    """우선순위: claude CLI(구독, $0) → API(크레딧) → 데이터 폴백. 반환 {lines, pick}."""
    if not items:
        return None
    return (_summarize_claude_cli(label, items)
            or _summarize_claude_api(label, items)
            or _summarize_heuristic(label, items))


def _summarize_claude_cli(label, items):
    if not items or not os.path.exists(CLAUDE_BIN):
        return None
    ordered = _ordered(items)
    prompt = f"{_SUMMARY_SYSTEM}\n\n[{label}] 오늘 수집:\n{_summary_listing(ordered)}"
    # CLI(구독, $0)가 실질적 주 채널 — 일시적 실패 시 1회 재시도해 휴리스틱 폴백 방지
    last_err = None
    for attempt in range(2):
        try:
            r = subprocess.run([CLAUDE_BIN, "-p"], input=prompt, capture_output=True,
                               text=True, timeout=150)
            if r.returncode == 0:
                res = _parse_summary(r.stdout.strip(), ordered)
                if res:
                    return res
                last_err = "빈 응답/파싱 실패"
            else:
                last_err = f"returncode={r.returncode} {(r.stderr or '').strip()[:150]}"
        except Exception as e:
            last_err = str(e)
        if attempt == 0:
            time.sleep(2)
    log(f"claude CLI 요약 실패 {label}: {last_err}")
    return None


def _summarize_claude_api(label, items):
    key = get_anthropic_key()
    if not key or not items:
        return None
    ordered = _ordered(items)
    body = json.dumps({
        "model": ANTHROPIC_MODEL,
        "max_tokens": 500,
        "system": _SUMMARY_SYSTEM,
        "messages": [{"role": "user", "content": f"[{label}] 오늘 수집:\n{_summary_listing(ordered)}"}],
    }).encode("utf-8")
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages", data=body, method="POST",
        headers={"content-type": "application/json", "x-api-key": key,
                 "anthropic-version": "2023-06-01"})
    last_err = None
    for attempt in range(2):  # 일시적 실패(400/429/5xx) 시 1회 재시도 → 휴리스틱 폴백 방지
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            text = "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")
            res = _parse_summary(text, ordered)
            if res:
                return res
            last_err = "빈 응답/파싱 실패"
        except urllib.error.HTTPError as e:
            detail = ""
            try:
                detail = e.read().decode("utf-8")[:200]
            except Exception:
                pass
            last_err = f"HTTP {e.code} {e.reason} {detail}".strip()
            if e.code != 429 and 400 <= e.code < 500:
                break  # 크레딧 부족·잘못된 요청 등은 재시도해도 안 됨
        except Exception as e:
            last_err = str(e)
        if attempt == 0:
            time.sleep(2)
    log(f"API 요약 실패 {label}: {last_err}")
    return None


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
    all_time_all = sorted(rows, key=lambda r: r.get("score") or 0, reverse=True)

    cutoff = TODAY - datetime.timedelta(days=recent_days)
    def is_recent(r):
        try:
            return datetime.date.fromisoformat(r["published"]) >= cutoff
        except (ValueError, KeyError, TypeError):
            return False
    recent_all = sorted([r for r in rows if is_recent(r)],
                        key=lambda r: r.get("score") or 0, reverse=True)

    trend = []
    for r in rows:
        pv = r.get("prev_score")
        if pv is not None and (r.get("score") or 0) - pv > 0:
            trend.append(dict(r, delta=(r["score"] - pv)))
    trending_all = sorted(trend, key=lambda r: r["delta"], reverse=True)

    # 뷰 간 중복 제거: 한 게시물은 한 섹션에만 (우선순위 최근 > 뜨는중 > 전체)
    claimed = set()
    def take(pool, k=5):
        out = []
        for r in pool:
            rid = r.get("id")
            if rid in claimed:
                continue
            claimed.add(rid)
            out.append(r)
            if len(out) >= k:
                break
        return out
    recent = take(recent_all)
    trending = take(trending_all)
    all_time = take(all_time_all)
    return {"recent": recent, "all_time": all_time, "trending": trending}


# ---------- render ----------
def fmt(n):
    try:
        return f"{int(n):,}"
    except (ValueError, TypeError):
        return "0"


def card_html(r, kind, rank, featured=False):
    p = PLATFORMS[r["platform"]]
    title = html.escape(r.get("title", "") or "")
    channel = html.escape(r.get("channel", "") or "")
    url = html.escape(r.get("url", "#") or "#")
    thumb = html.escape(r.get("thumbnail", "") or "")
    if kind == "trending":
        meta = f"<b>+{fmt(r.get('delta'))}</b> {p['score']} · 누적 {fmt(r.get('score'))}"
    elif kind == "recent":
        meta = f"{html.escape(r.get('published',''))} · {p['score']} <b>{fmt(r.get('score'))}</b>"
    else:
        meta = f"{p['score']} <b>{fmt(r.get('score'))}</b> · {p['second']} {fmt(r.get('second'))}"
    thumb_tag = (f'<img src="{thumb}" loading="lazy" alt="{title}" '
                 f'onerror="this.parentNode.classList.add(&quot;broken&quot;)">'
                 if thumb else '')
    glyph = PLATFORM_ICON.get(r["platform"], "")
    thumb_cls = "thumb" if thumb else "thumb noimg"
    hero = " card--hero" if featured else ""
    return f"""<a class="card v-{kind}{hero}" style="--i:{rank}" href="{url}" target="_blank" rel="noopener">
      <div class="{thumb_cls}">{thumb_tag}<span class="ph">{glyph}</span>
        <span class="rank">{rank}</span>
        <span class="play"><svg viewBox="0 0 32 32" width="26" height="26" fill="currentColor"><path fill="none" d="M11,23a1,1,0,0,1-1-1V10a1,1,0,0,1,1.4473-.8945l12,6a1,1,0,0,1,0,1.789l-12,6A1.001,1.001,0,0,1,11,23Z"/><path d="M16,2A14,14,0,1,0,30,16,14,14,0,0,0,16,2Zm7.4473,14.8945-12,6A1,1,0,0,1,10,22V10a1,1,0,0,1,1.4473-.8945l12,6a1,1,0,0,1,0,1.789Z"/></svg></span>
        <span class="tag">{glyph}{html.escape(p['label'])}</span>
      </div>
      <div class="body"><div class="title">{title}</div>
        <div class="channel">{channel}</div><div class="meta">{meta}</div></div>
    </a>"""


# ---------- 지난 요약 로그: 날짜별 누적 + archive 복원 ----------
def _pick_meta(pick):
    """summaries.json의 구조화된 pick → 로그용 단일 meta 문자열."""
    if not pick:
        return None
    parts = [x for x in (pick.get("channel"), pick.get("reason")) if x]
    return {"url": pick.get("url", "") or "", "title": pick.get("title", "") or "",
            "meta": " · ".join(parts)}


def log_entry_from_summaries(summaries):
    """오늘 summaries({pid:{date,lines,pick}}) → 로그 한 날치({pid:{lines,pick}})."""
    entry = {}
    for pid, sm in (summaries or {}).items():
        if sm and sm.get("lines"):
            entry[pid] = {"lines": sm["lines"], "pick": _pick_meta(sm.get("pick"))}
    return entry


def extract_summaries_from_html(text):
    """archive HTML 한 장 → {pid:{lines,pick}}. 이 빌더가 만든 구조를 그대로 역파싱."""
    entry = {}
    for pid, body in re.findall(
            r'<section class="platform[^"]*" id="pf-(\w+)">(.*?)</section>', text, re.S):
        m = re.search(r'<div class="summary"[^>]*>(.*?)(?:<aside class="sidelog"|<h2 class="vhead">)',
                      body, re.S)
        if not m:
            continue
        block = m.group(1)
        lines = [html.unescape(x).strip() for x in re.findall(r'<li>(.*?)</li>', block, re.S)]
        if not lines:
            continue
        pick = None
        href = re.search(r'<a class="picklink" href="([^"]*)"', block)
        ptitle = re.search(r'<div class="ptitle">(.*?)</div>', block, re.S)
        if ptitle:
            pchan = re.search(r'<div class="pchan">(.*?)</div>', block, re.S)
            pick = {"url": html.unescape(href.group(1)) if href else "",
                    "title": html.unescape(ptitle.group(1)).strip(),
                    "meta": html.unescape(pchan.group(1)).strip() if pchan else ""}
        entry[pid] = {"lines": lines, "pick": pick}
    return entry


def build_log_from_archives():
    """archive/*.html 전체를 역파싱해 summary_log.json을 재생성한다 (--backfill)."""
    log_data = {}
    for f in sorted(ARCHIVE.glob("*.html")):
        date = f.stem  # YYYY-MM-DD
        entry = extract_summaries_from_html(f.read_text(encoding="utf-8"))
        if entry:
            log_data[date] = entry
            log(f"복원: {date} ({', '.join(entry)})")
    save_json(SUMMARY_LOG, log_data)
    log(f"summary_log.json 재생성 완료: {len(log_data)}일치")
    return log_data


def side_log(pid, log_data, skip_date):
    """오늘 요약 옆에 붙는, 해당 플랫폼의 지난 3줄 요약 패널 (오늘 제외, 날짜 내림차순)."""
    if not log_data:
        return ""
    days = ""
    for date in sorted(log_data, reverse=True):
        if date == skip_date:
            continue
        sm = log_data[date].get(pid)
        if not sm or not sm.get("lines"):
            continue
        lis = "".join(f"<li>{html.escape(x)}</li>" for x in sm["lines"])
        pk = sm.get("pick")
        pick_html = ""
        if pk and pk.get("title"):
            purl = html.escape(pk.get("url") or "#") or "#"
            pick_html = (f'<a class="sidepick" href="{purl}" target="_blank" rel="noopener">'
                         f'{IC_EYE}{html.escape(pk["title"])}</a>')
        days += (f'<div class="sideday"><div class="sidedate">{html.escape(date)}</div>'
                 f'<ul>{lis}</ul>{pick_html}</div>')
    if not days:
        return ""
    return (f'<aside class="sidelog"><div class="sidehead">지난 요약</div>'
            f'<div class="sidedays">{days}</div></aside>')


def render(ranks, summaries, spent, budget, log_data=None):
    btns, blocks = "", ""
    for i, (pid, p) in enumerate(PLATFORMS.items()):
        act = " active" if i == 0 else ""
        btns += (f'<button class="tabbtn{act}" data-pf="{pid}">'
                 f'{PLATFORM_ICON.get(pid, "")}{p["label"]}</button>')
        sm = (summaries or {}).get(pid)
        if sm and sm.get("lines"):
            lis = "".join(f"<li>{html.escape(x)}</li>" for x in sm["lines"])
            date_note = f' · {html.escape(sm.get("date",""))}' if sm.get("date") else ""
            pk = sm.get("pick")
            pick_html = ""
            if pk and pk.get("title"):
                purl = html.escape(pk.get("url", "#") or "#")
                ptitle = html.escape(pk.get("title", ""))
                pchan = html.escape(pk.get("channel", "") or "")
                an = pk.get("analysis") or {}
                if an:
                    steps = [("1 · 왜 떴나", an.get("why", "")),
                             ("2 · 핵심 포인트", an.get("point", "")),
                             ("3 · 따라해볼 점", an.get("apply", ""))]
                else:
                    steps = [("왜 골랐나", pk.get("reason", "") or "")]
                steps_html = "".join(
                    f'<div class="step"><div class="stepnum">{html.escape(t)}</div>'
                    f'<p class="steptext">{html.escape(v)}</p></div>'
                    for t, v in steps if v)
                pick_html = (
                    f'<div class="pick">'
                    f'<div class="pickhead">'
                    f'<div class="pickmain"><div class="ptag">{IC_EYE}꼭 봐야 할 게시물 · 눌러서 분석 보기</div>'
                    f'<div class="ptitle">{ptitle}</div>'
                    f'<div class="pchan">{pchan}</div></div>'
                    f'<span class="chev">⌄</span></div>'
                    f'<div class="panel">{steps_html}'
                    f'<a class="picklink" href="{purl}" target="_blank" rel="noopener">원본 게시물 보러 가기 →</a>'
                    f'</div></div>')
            summary = (f'<div class="summary"><div class="shead">{IC_DOC}오늘의 3줄 요약{date_note}</div>'
                       f'<ul>{lis}</ul>{pick_html}</div>')
        else:
            summary = (f'<div class="summary muted">{IC_DOC}3줄 요약은 다음 수집 때 생성됩니다 '
                       '(Claude 분석)</div>')
        today_iso = TODAY.isoformat()
        side = side_log(pid, log_data, today_iso)
        sections = f'<div class="sumrow">{summary}{side}</div>' if side else summary
        idx = 0
        for vkey, vlabel in VIEWS:
            rows = ranks[pid][vkey]
            if rows:
                cards = ""
                for n, r in enumerate(rows):
                    idx += 1
                    cards += card_html(r, vkey, idx, featured=(n == 0))
            else:
                note = ("내일부터 데이터가 쌓입니다 (전일 대비 계산)"
                        if vkey == "trending" else "아직 항목이 없습니다")
                cards = f'<p class="empty">{note}</p>'
            sections += (f'<h2 class="vhead">{VHEAD_ICON.get(vkey, "")}{vlabel}</h2>'
                         f'<div class="row">{cards}</div>')
        blocks += f'<section class="platform{act}" id="pf-{pid}">{sections}</section>'

    date_str = TODAY.isoformat()
    favicon = ("data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'>"
               "<text y='.9em' font-size='90'>🎵</text></svg>")
    return f"""<!doctype html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="description" content="매일 자동 정리되는 음악 인기 게시물 — TikTok·Instagram·Reddit">
<meta property="og:title" content="데일리 뮤직 뉴스레터">
<title>데일리 뮤직 뉴스레터 · {date_str}</title>
<link rel="icon" href="{favicon}">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@300;400;600&family=IBM+Plex+Sans+KR:wght@300;400;600&family=IBM+Plex+Mono:wght@400&display=swap" rel="stylesheet">
<style>
  :root {{
    color-scheme:dark;
    --bg:#161616; --layer:#262626; --layer-2:#393939; --layer-3:#525252;
    --border:#393939; --border-soft:#262626; --border-strong:#6f6f6f; --r:0;
    --text:#f4f4f4; --text-2:#c6c6c6; --text-helper:#8d8d8d;
    --link:#78a9ff; --accent:#4589ff; --btn:#0f62fe; --btn-hover:#0353e9;
    --recent:#78a9ff; --alltime:#be95ff; --trending:#3ddbd9;
    --head:'IBM Plex Sans','IBM Plex Sans KR',sans-serif;
    --ease:cubic-bezier(.2,0,.38,.9);
  }}
  * {{ box-sizing:border-box; }}
  html {{ scroll-behavior:smooth; }}
  body {{
    margin:0; background:var(--bg); color:var(--text); min-height:100dvh;
    font-family:'IBM Plex Sans','IBM Plex Sans KR',system-ui,-apple-system,sans-serif;
    word-break:keep-all; -webkit-font-smoothing:antialiased; font-size:16px; line-height:1.6;
  }}
  header, .navbar, main, footer {{ position:relative; z-index:1; }}
  .wrap {{ max-width:1180px; margin:0 auto; padding:0 20px; }}
  header {{ padding:48px 0 0; }}
  h1 {{ margin:0; font-family:var(--head); font-size:clamp(28px,4.4vw,40px); font-weight:300;
    letter-spacing:0; line-height:1.25; }}
  .sub {{ color:var(--text-2); font-size:13px; margin-top:8px; letter-spacing:.2px;
    font-variant-numeric:tabular-nums; }}
  .navbar {{ position:sticky; top:0; z-index:40; margin-top:16px;
    background:var(--bg); border-bottom:1px solid var(--border); }}
  .tabs {{ display:flex; max-width:1180px; margin:0 auto; padding:0 20px;
    overflow-x:auto; -webkit-overflow-scrolling:touch; scrollbar-width:none; }}
  .tabs::-webkit-scrollbar {{ display:none; }}
  .tabbtn {{ flex:0 0 auto; display:inline-flex; align-items:center; gap:8px;
    background:transparent; color:var(--text-2); border:none;
    border-bottom:3px solid transparent; padding:13px 18px; font:inherit; font-size:15px;
    cursor:pointer; transition:color .11s var(--ease),border-color .11s var(--ease),background .11s var(--ease); white-space:nowrap; }}
  .tabbtn:hover {{ color:var(--text); background:var(--layer); }}
  .tabbtn.active {{ color:var(--text); font-weight:600; border-bottom-color:var(--accent); }}
  .tic {{ width:18px; height:18px; flex:0 0 auto; }}
  .tabbtn.active .tic {{ color:var(--accent); }}
  .hic {{ width:20px; height:20px; flex:0 0 auto; vertical-align:-4px; margin-right:8px; }}
  .hic-pink {{ color:var(--alltime); }}
  .hic-amber {{ color:var(--trending); }}
  .hic-cyan {{ color:var(--recent); }}
  .platform {{ display:none; max-width:1180px; margin:0 auto; padding:8px 20px 64px; }}
  .platform.active {{ display:block; }}
  .summary {{ margin:22px 0 4px; padding:18px 20px; background:var(--layer);
    border-left:3px solid var(--accent); }}
  .summary.muted {{ background:var(--layer); border-left:3px solid var(--border);
    color:var(--text-2); font-size:14px; }}
  .shead {{ font-family:var(--head); font-size:15px; font-weight:600; color:var(--accent);
    margin-bottom:10px; letter-spacing:.2px; }}
  .summary ul {{ margin:0; padding-left:20px; }}
  .summary li {{ font-size:15px; line-height:1.7; margin:4px 0; }}
  .pick {{ margin-top:16px; overflow:hidden;
    background:var(--layer); border:1px solid var(--border); border-left:3px solid var(--accent); }}
  .pickhead {{ padding:16px 18px; display:flex; align-items:flex-start; justify-content:space-between;
    gap:10px; cursor:pointer; transition:background .12s var(--ease); }}
  .pickhead:hover {{ background:var(--layer-2); }}
  .pickmain {{ min-width:0; }}
  .ptag {{ font-size:12px; font-weight:600; color:var(--accent); letter-spacing:.3px; }}
  .ptitle {{ margin:6px 0 0; font-family:var(--head); font-size:18px; font-weight:600; line-height:1.4; }}
  .pchan {{ margin:4px 0 0; font-size:13px; color:var(--text-2); }}
  .chev {{ font-size:20px; color:var(--text-helper); flex:0 0 auto; line-height:1; margin-top:2px;
    transition:transform .2s var(--ease); }}
  .pick.open .chev {{ transform:rotate(180deg); }}
  .panel {{ display:none; border-top:1px solid var(--border); padding:6px 18px 16px; }}
  .pick.open .panel {{ display:block; }}
  .step {{ padding:12px 0 2px; border-top:1px solid var(--border); }}
  .step:first-child {{ border-top:none; }}
  .stepnum {{ font-size:12px; font-weight:600; color:var(--text-helper); letter-spacing:.4px; }}
  .steptext {{ margin:6px 0 0; font-size:15px; line-height:1.7; color:var(--text); }}
  .picklink {{ display:flex; align-items:center; justify-content:center; gap:7px; margin-top:16px;
    padding:13px; background:var(--btn); color:#fff; font-size:14px; font-weight:600;
    text-decoration:none; transition:background .12s var(--ease); }}
  .picklink:hover {{ background:var(--btn-hover); }}
  .vhead {{ font-family:var(--head); font-size:19px; font-weight:600; color:var(--text);
    margin:40px 2px 16px; padding-bottom:9px; border-bottom:1px solid var(--border); }}
  .row {{ display:grid; grid-template-columns:repeat(auto-fill,minmax(260px,1fr)); gap:16px; }}
  @keyframes fadeUp {{ from {{ opacity:0; transform:translateY(16px); }} to {{ opacity:1; transform:none; }} }}
  .platform.active .card {{ animation:fadeUp .5s var(--ease) both; animation-delay:calc(var(--i) * 45ms); }}
  .v-recent {{ --vc:var(--recent); }}
  .v-all_time {{ --vc:var(--alltime); }}
  .v-trending {{ --vc:var(--trending); }}
  .card {{ position:relative; display:block; background:var(--layer); overflow:hidden;
    border:1px solid var(--border); border-top:3px solid var(--vc,var(--border));
    text-decoration:none; color:inherit;
    transition:background .12s var(--ease), border-color .12s var(--ease), transform .12s var(--ease); }}
  .card:hover {{ background:var(--layer-2); border-color:var(--border-strong); }}
  .card:hover {{ border-top-color:var(--vc); }}
  .card--hero {{ grid-column:span 2; }}
  .card--hero .thumb {{ aspect-ratio:16/8; }}
  .card--hero .body {{ padding:18px 20px 20px; }}
  .card--hero .title {{ font-size:19px; -webkit-line-clamp:3; }}
  .card--hero .rank {{ font-size:15px; padding:5px 12px; }}
  .thumb {{ position:relative; aspect-ratio:16/9; background:var(--layer-2); overflow:hidden;
    display:grid; place-items:center; }}
  .thumb img {{ position:relative; z-index:1; width:100%; height:100%; object-fit:cover; display:block;
    transition:transform .5s var(--ease); }}
  .card:hover .thumb img {{ transform:scale(1.05); }}
  .ph {{ position:absolute; width:48px; height:48px; opacity:.5; z-index:0; color:var(--vc,var(--text-helper)); }}
  .thumb.noimg, .thumb.broken {{ background:linear-gradient(135deg, color-mix(in srgb, var(--vc) 24%, var(--layer-2)), var(--layer)); }}
  .thumb.broken img {{ display:none; }}
  .thumb::after {{ content:""; position:absolute; inset:0; z-index:1;
    background:linear-gradient(to top, rgba(0,0,0,.55), transparent 45%); }}
  .rank {{ position:absolute; top:8px; left:8px; z-index:3; font-size:13px; font-weight:600;
    line-height:1; color:#fff; background:var(--accent); padding:3px 9px;
    font-variant-numeric:tabular-nums; }}
  .play {{ position:absolute; inset:0; margin:auto; width:46px; height:46px; z-index:3; display:grid;
    place-items:center; color:#fff;
    opacity:0; transform:scale(.85); transition:all .3s var(--ease); }}
  .card:hover .play {{ opacity:1; transform:scale(1); }}
  .tag {{ position:absolute; left:8px; bottom:8px; z-index:3; font-size:12px;
    display:inline-flex; align-items:center; gap:5px;
    padding:4px 9px; color:var(--text); background:rgba(22,22,22,.82);
    border:1px solid var(--border); }}
  .tag svg {{ width:13px; height:13px; color:var(--vc); }}
  .body {{ padding:14px 15px 17px; }}
  .title {{ font-size:15px; font-weight:600; line-height:1.5;
    display:-webkit-box; -webkit-line-clamp:2; -webkit-box-orient:vertical; overflow:hidden; }}
  .channel {{ color:var(--text-2); font-size:13px; margin-top:7px; }}
  .meta {{ font-size:13px; margin-top:9px; color:var(--text-2); font-variant-numeric:tabular-nums; }}
  .meta b {{ color:var(--accent); font-weight:600; }}
  .empty {{ color:var(--text-2); font-size:14px; padding:10px 2px 4px; }}
  .sumrow {{ display:flex; gap:16px; align-items:flex-start; margin:22px 0 4px; }}
  .sumrow .summary {{ flex:1; min-width:0; margin:0; }}
  .sidelog {{ flex:0 0 280px; align-self:stretch; padding:14px 16px;
    background:var(--layer); border:1px solid var(--border);
    max-height:380px; overflow-y:auto; scrollbar-width:thin; }}
  .sidehead {{ font-size:13px; font-weight:600; color:var(--text-2); margin-bottom:10px;
    letter-spacing:.2px; }}
  .sideday {{ padding:10px 0; border-top:1px solid var(--border-soft); }}
  .sideday:first-of-type {{ border-top:none; padding-top:0; }}
  .sidedate {{ font-size:12.5px; font-weight:600; color:var(--link); margin-bottom:5px;
    font-variant-numeric:tabular-nums; }}
  .sidelog ul {{ margin:0; padding-left:16px; }}
  .sidelog li {{ font-size:13px; line-height:1.6; margin:3px 0; color:var(--text-2); }}
  .sidepick {{ display:block; margin-top:5px; font-size:12px; color:var(--text-2);
    text-decoration:none; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }}
  .sidepick:hover {{ color:var(--link); }}
  footer {{ color:var(--text-helper); font-size:13px; padding:0 0 40px; }}
  @media (max-width:600px) {{
    body {{ overflow-x:hidden; }}
    header {{ padding:26px 0 0; }}
    .platform {{ padding:6px 16px 44px; }}
    .sumrow {{ flex-direction:column; }}
    .sidelog {{ flex-basis:auto; width:100%; max-height:280px; }}
    .wrap {{ padding:0 16px; }}
    .tabs {{ padding:0 16px; }}
    .row {{ grid-template-columns:1fr; }}
    .card {{ display:flex; flex-direction:row; align-items:stretch; }}
    .card--hero {{ grid-column:span 1; }}
    .card--hero .thumb {{ aspect-ratio:auto; }}
    .card--hero .title {{ font-size:14px; }}
    .thumb {{ width:44%; max-width:170px; flex:0 0 auto; aspect-ratio:auto; min-height:100px; }}
    .body {{ flex:1; min-width:0; padding:12px 14px; align-self:center; }}
    .title {{ font-size:14px; -webkit-line-clamp:3; }}
    .play {{ width:38px; height:38px; }}
  }}
  @media (prefers-reduced-motion:reduce) {{
    html {{ scroll-behavior:auto; }} .platform.active .card {{ animation:none; }}
    * {{ transition:none !important; }}
  }}
</style></head><body>
<header><div class="wrap">
  <div class="sub">{date_str} · TikTok · Instagram · Reddit · 이번 달 ${spent:.2f} / ${budget:.2f}</div>
  <h1>데일리 뮤직 뉴스레터</h1>
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
  document.querySelectorAll('.pick').forEach(p => {{
    const h = p.querySelector('.pickhead');
    if (h) h.addEventListener('click', () => p.classList.toggle('open'));
  }});
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

    if "--backfill" in sys.argv:
        build_log_from_archives()
        return

    history = load_json(HISTORY, {})
    state = load_json(STATE, {})
    summaries = load_json(SUMMARIES, {})
    log_data = load_json(SUMMARY_LOG, {})
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
                n = int(conf.get("max_results", 8))
                unit, start = PLATFORMS[pid]["unit"], PLATFORMS[pid]["start"]
                # reddit는 음악 서브레딧 묶음을 한 번의 run으로, 나머지는 키워드별 run
                if pid == "reddit":
                    subs = conf.get("subreddits") or conf.get("keywords", [])
                    units = [subs] if subs else []
                else:
                    units = conf.get("keywords", [])
                for kw in units:
                    label = ", ".join(kw) if isinstance(kw, list) else kw
                    # reddit는 서브레딧당 n개씩 → 묶음 크기를 예산 추정에 반영
                    n_est = n * len(kw) if isinstance(kw, list) else n
                    est = start + unit * n_est
                    if state["spent"] + est > budget:
                        log(f"월 예산(${budget}) 도달 → {pid}/'{label}' 이후 수집 중단")
                        break
                    try:
                        items = fetch(token, pid, kw, n)
                        update_history(history, items)
                        got = len(items)
                        fetched += got
                        state["spent"] += start + unit * got
                        log(f"수집: {pid} · '{label}' {got}개 (누적 ${state['spent']:.2f})")
                        time.sleep(1)
                    except urllib.error.HTTPError as e:
                        log(f"수집 실패 {pid}/'{label}': HTTP {e.code} {e.reason}")
                    except Exception as e:
                        log(f"수집 실패 {pid}/'{label}': {e}")
            save_json(HISTORY, history)
            save_json(STATE, state)

            # 그날 수집분으로 플랫폼별 3줄 요약 생성 (claude CLI → API → 데이터 폴백)
            today = TODAY.isoformat()
            for pid in PLATFORMS:
                todays = [r for r in history.values()
                          if r.get("platform") == pid and r.get("last_seen") == today]
                res = summarize(PLATFORMS[pid]["label"], todays)
                if res and res.get("lines"):
                    summaries[pid] = {"date": today, **res}
                    log(f"요약 생성: {pid} ({len(res['lines'])}줄, pick={'O' if res.get('pick') else 'X'})")
            save_json(SUMMARIES, summaries)

            # 오늘치 3줄 요약을 날짜별 로그에 누적 (덮어쓰지 않고 날짜로 보존)
            entry = log_entry_from_summaries(summaries)
            if entry:
                log_data[today] = entry
                save_json(SUMMARY_LOG, log_data)

    ranks = {pid: rank_platform(history, pid, recent_days) for pid in PLATFORMS}
    page = render(ranks, summaries, state.get("spent", 0.0), budget, log_data)
    INDEX.write_text(page, encoding="utf-8")
    ARCHIVE.mkdir(exist_ok=True)
    (ARCHIVE / f"{TODAY.isoformat()}.html").write_text(page, encoding="utf-8")
    summary = " · ".join(
        f"{PLATFORMS[p]['label']} {sum(len(ranks[p][v]) for v,_ in VIEWS)}" for p in PLATFORMS)
    log(f"렌더 완료: {summary} (이번 실행 수집 {fetched}개)")
    git_push()


if __name__ == "__main__":
    main()
