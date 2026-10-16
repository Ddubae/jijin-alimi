import re
from datetime import datetime, timedelta

import requests
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import folium
from streamlit_folium import st_folium
import streamlit as st

st.set_page_config(page_title="대한민국 지진 현황 알리미", layout="wide", page_icon="🌍")

KMA_KEY = "69bb08cc0eacf8cbdfffc6b9b4ecf242d33a1cc5955004d3048de6fb54c985df"
SAFEMAP_KEY = "IE6DVJTK-IE6D-IE6D-IE6D-IE6DVJTKDJ"

KMA_URL = "https://apis.data.go.kr/1360000/EqkInfoService/getEqkMsg"
SAFEMAP_URL = "https://www.safemap.go.kr/openapi2/IF_0030"

KOREA_BOUNDS = [[33.0, 125.2], [38.65, 129.6]]
ZOOM_IN_PADDING = 60

PROVINCE_CENTER = {
    "서울": (37.5665, 126.9780), "경기": (37.4138, 127.5183), "인천": (37.4563, 126.7052),
    "강원": (37.8228, 128.1555), "충북": (36.8000, 127.7000), "충남": (36.5184, 126.8000),
    "대전": (36.3504, 127.3845), "세종": (36.4800, 127.2890), "전북": (35.7175, 127.1530),
    "전남": (34.8161, 126.4630), "광주": (35.1595, 126.8526), "경북": (36.4919, 128.8889),
    "경남": (35.4606, 128.2132), "대구": (35.8714, 128.6014), "울산": (35.5384, 129.3114),
    "부산": (35.1796, 129.0756), "제주": (33.4996, 126.5312),
}

NORTH_KOREA_KEYWORDS = [
    "북한", "함경북도", "함경남도", "량강도", "양강도", "자강도",
    "평안북도", "평안남도", "황해북도", "황해남도", "평양", "남포",
    "나선", "개성", "혜산", "청진", "함흥", "신의주", "원산", "해주",
    "사리원", "강계", "온성", "무산", "회령", "종성", "경원", "경흥",
]

# 대한민국 영토·영해 지진만 허용하는 필터
DOMESTIC_FCTP = {"3", "5", "11", "13", "14"}   # 2·12(국외 통보) 제외
KR_SEA_BOUNDS = {"lat_min": 32.0, "lat_max": 38.7, "lon_min": 124.0, "lon_max": 132.0}
FOREIGN_KEYWORDS = ["일본", "중국", "대만", "러시아", "필리핀", "인도네시아",
                    "파푸아", "뉴기니", "베트남", "몽골", "해외", "국외"]


def is_korea_domestic(item):
    loc = str(item.get("loc", ""))
    fctp = str(item.get("fcTp", "")).strip()
    if fctp and fctp not in DOMESTIC_FCTP:
        return False
    if any(kw in loc for kw in NORTH_KOREA_KEYWORDS + FOREIGN_KEYWORDS):
        return False
    try:
        lat, lon = float(item.get("lat")), float(item.get("lon"))
    except (TypeError, ValueError):
        return False
    b = KR_SEA_BOUNDS
    return b["lat_min"] <= lat <= b["lat_max"] and b["lon_min"] <= lon <= b["lon_max"]


# ── 범례 칩 라벨: 물결(~) 기호 대신 하이픈(-)으로 통일해 폰트 깨짐 방지 ──
BIN_COLORS = {
    "0 - 10건": "#F5B7C4",
    "11 - 50건": "#E85D8A",
    "51 - 100건": "#B3123B",
    "100건 초과": "#5C0A22",
}

INTENSITY_MAP_COLORS = {
    1: "#D6EAF8", 2: "#AED6F1", 3: "#7FB3D5", 4: "#F9E79F",
    5: "#F5B041", 6: "#E67E22", 7: "#D35400", 8: "#C0392B",
    9: "#922B21", 10: "#641E16", 11: "#3B0A0A", 12: "#000000",
}

# 최근 5건 번호별 색상 (지도 번호 마커 ↔ 목록 번호 배지 동일 색)
RANK_COLORS = {
    1: ("#D50000", "#FFFFFF"),
    2: ("#FF6D00", "#FFFFFF"),
    3: ("#FFD600", "#111111"),
    4: ("#00A86B", "#FFFFFF"),
    5: ("#2962FF", "#FFFFFF"),
}

def intensity_color(grade):
    try:
        g = int(float(grade))
    except (TypeError, ValueError):
        g = 1
    return INTENSITY_MAP_COLORS.get(min(max(g, 1), 12), "#999999")


def fit_bounds_zoomed(m, bounds, pad=ZOOM_IN_PADDING):
    m.fit_bounds(
        bounds,
        padding_top_left=(-pad, -pad),
        padding_bottom_right=(-pad, -pad),
    )


def clean_paren(text):
    if not isinstance(text, str):
        return text
    cleaned = re.sub(r"\([^)]*\)", "", text)
    cleaned = re.sub(r"\s{2,}", " ", cleaned).strip(" ,")
    return cleaned


INTENSITY_LEVELS = [
    {"key": "1_2", "label": "진도 Ⅰ~Ⅱ", "desc": "거의 느낄 수 없음",
     "detail": "특별히 좋은 조건에서 극소수만 느끼며, 대부분 지진계에만 기록되는 수준입니다.",
     "color": "#8E8E93", "video": "https://www.youtube.com/embed/2tt1wRGJY8c"},
    {"key": "3_4", "label": "진도 Ⅲ~Ⅳ", "desc": "약한 흔들림",
     "detail": "실내에 있는 사람 다수가 흔들림을 느끼며, 매달린 물체가 흔들릴 수 있습니다.",
     "color": "#E8A93A", "video": "https://www.youtube.com/embed/oNTGC34kZtU"},
    {"key": "5_6", "label": "진도 Ⅴ~Ⅵ", "desc": "뚜렷한 흔들림",
     "detail": "거의 모든 사람이 느끼고, 놀라서 밖으로 대피하는 사람이 생기며 물건이 넘어질 수 있습니다.",
     "color": "#D9534F", "video": "https://www.youtube.com/embed/8LUG9Iuk8rI"},
    {"key": "7_8", "label": "진도 Ⅶ~Ⅷ", "desc": "구조물 피해 시작",
     "detail": "내진설계가 부실한 건물에 균열·붕괴가 시작되고, 서있기 힘들 정도의 흔들림입니다.",
     "color": "#B3123B", "video": "https://www.youtube.com/embed/2tt1wRGJY8c"},
    {"key": "9_up", "label": "진도 Ⅸ 이상", "desc": "심각한 붕괴",
     "detail": "내진 여부와 관계없이 건물 붕괴가 발생할 수 있는 매우 위험한 수준입니다.",
     "color": "#5C0A22", "video": "https://www.youtube.com/embed/oNTGC34kZtU"},
]

SAFETY_STEPS = [
    {"key": "step1", "title": "1단계. 평소 대비",
     "desc": "가구·가전제품이 넘어지거나 떨어지지 않도록 벽에 단단히 고정해두고, 소화기·손전등·생수 등 비상용품을 미리 챙겨둡니다. 가족과 함께 대피 장소와 만날 장소를 미리 정해둡니다.",
     "video": "https://www.youtube.com/embed/zO2H4dzGsho"},
    {"key": "step2", "title": "2단계. 흔들리는 동안",
     "desc": "당황하지 말고 즉시 책상이나 튼튼한 탁자 아래로 들어가 다리를 꼭 잡습니다. 머리와 목을 가방이나 팔로 보호하고, 흔들림이 멈출 때까지 기다립니다.",
     "video": "https://www.youtube.com/embed/gEf45HNBiK4"},
    {"key": "step3", "title": "3단계. 흔들림이 멈춘 후",
     "desc": "가스 밸브를 잠그고 전기 차단기를 내려 화재 위험을 없앤 뒤, 신발을 신고 문을 열어 출구를 확보한 다음 신속하게 밖으로 이동합니다.",
     "video": "https://www.youtube.com/embed/BF6LZfE7v8o"},
    {"key": "step4", "title": "4단계. 대피 및 장소별 대응",
     "desc": "엘리베이터는 절대 이용하지 말고 계단으로 이동합니다. 유리창·간판이 떨어질 수 있는 건물 벽면을 피해 운동장이나 공원 등 넓은 공간으로 이동합니다.",
     "video": "https://www.youtube.com/embed/stOUne88yR0"},
]

st.markdown("""
<style>
html, body, [class*="css"]  { font-size: 18px !important; }

/* 모니터 베젤 디자인 */
.stApp::before {
    content: "";
    position: fixed;
    top: 28px; left: 28px; right: 28px; bottom: 62px;
    border-radius: 14px;
    pointer-events: none;
    z-index: 999990;
    box-shadow:
        0 0 0 3px #000000,
        0 0 0 6px #2A2E36,
        0 0 0 400px #15171C,
        inset 0 0 30px rgba(0,0,0,0.35);
}
/* 하단 베젤 로고 */
.stApp::after {
    content: "DISASTER SITUATION MONITOR";
    position: fixed;
    left: 50%; bottom: 22px;
    transform: translateX(-50%);
    color: #8A8F98;
    font-size: 12px;
    font-weight: 700;
    letter-spacing: 4px;
    pointer-events: none;
    z-index: 999991;
}
/* 전원 LED */
[data-testid="stAppViewContainer"]::after {
    content: "";
    position: fixed;
    right: 56px; bottom: 26px;
    width: 9px; height: 9px;
    border-radius: 50%;
    background: #00E676;
    box-shadow: 0 0 8px #00E676;
    pointer-events: none;
    z-index: 999991;
}
/* 내용이 베젤에 가려지지 않게 안쪽 여백 */
.block-container {
    padding-top: 70px !important;
    padding-left: 70px !important;
    padding-right: 70px !important;
    padding-bottom: 110px !important;
}

.hero-box {
    background: linear-gradient(90deg,#1a1a2e,#8B0000);
    padding: 22px 28px; border-radius: 10px; color: white; margin-bottom: 6px;
}
.hero-title { font-size: 30px; font-weight: 800; margin: 0; }
.hero-sub { font-size: 20px; opacity: 0.9; margin-top: 4px; }

.alert-badge {
    background:#B3123B; color:#fff; display:inline-block; padding:8px 20px;
    border-radius: 20px; font-size:20px; font-weight:800; margin: 14px 0 8px 0;
}

.ticker-wrap {
    position: relative; background: #0B2545; overflow: hidden;
    height: 56px; border-radius: 0 0 10px 10px; margin-bottom: 22px;
}
.ticker-move {
    display: inline-block;
    padding-left: 100%;
    line-height: 56px;
    white-space: nowrap; color: #FFFFFF !important; font-size: 24px; font-weight: 700;
    will-change: transform;
    backface-visibility: hidden;
    animation-name: ticker-scroll; animation-timing-function: linear; animation-iteration-count: infinite;
}
@keyframes ticker-scroll {
    from { transform: translate3d(0, 0, 0); }
    to   { transform: translate3d(-100%, 0, 0); }
}

.section-title { font-size: 26px; font-weight: 800; border-left: 6px solid #B3123B;
    padding-left: 12px; margin: 30px 0 14px 0; }
.sub-title { font-size: 22px; font-weight: 800; color:#555; margin: 6px 0 14px 0; }
.data-range { font-size: 20px; font-weight: 800; color: #222; margin-bottom: 14px; }
.intro-text { font-size: 20px; color:#555; margin-bottom: 16px; line-height:1.6; }

/* 도표 사이 구분 여백 + 옅은 구분선 */
.chart-gap { margin: 44px 0 40px 0; border-top: 1px solid #E6E6E6; }

.legend-chip {
    display:inline-block; padding:6px 16px; border-radius: 20px; color:#fff;
    font-size: 19px; font-weight: 700; margin-right: 10px; margin-bottom: 8px;
    white-space: nowrap; letter-spacing: 0.5px;
}
.legend-chip-dark { color:#111; border:1px solid #ccc; }

/* [변경] 통계 카드 : 3칸 높이 동일 + 제목·숫자·설명 줄 위치 가로 정렬 */
.stat-card { background:#fafafa; border:1px solid #eee; border-radius: 12px; padding: 24px 16px;
    text-align:center; overflow:hidden;
    min-height: 190px; box-sizing: border-box;
    display:flex; flex-direction:column; justify-content:center; }
.stat-label { font-size: clamp(18px, 1.35vw, 23px); font-weight: 800; color:#333;
    white-space: nowrap; overflow:hidden; text-overflow: ellipsis; }
.stat-num { font-size: clamp(26px, 2.5vw, 42px); font-weight: 900; color:#B3123B; margin-top: 10px;
    white-space: nowrap; overflow:hidden; text-overflow: ellipsis; }
.stat-sub { font-size: clamp(16px, 1.1vw, 20px); color:#666; margin-top: 8px;
    white-space: nowrap; overflow:hidden; text-overflow: ellipsis; }

/* 통계 카드: 배경 네이비 / 빨간 글자 → 노랑 / 검정 글자 → 흰색 */
.stat-card.stat-navy { background:#0B2545; border:1px solid #0B2545; }
.stat-card.stat-navy .stat-label { color:#FFFFFF; }
.stat-card.stat-navy .stat-num { color:#FFD400; }
.stat-card.stat-navy .stat-sub { color:#FFFFFF; }

.level-card { border-radius: 10px 10px 0 0; padding: 18px; text-align:center; color:white;
    font-weight: 800; font-size: clamp(19px, 1.5vw, 24px); white-space: nowrap; }
.level-sub { font-size: clamp(16px, 1.15vw, 20px); font-weight: 600; margin-top: 6px; white-space: nowrap; }

.safety-card { border-radius: 10px 10px 0 0; padding: 20px; text-align:left;
    min-height: 270px; background:#f5f5f5; }
.safety-title { font-size: 22px; font-weight: 800; color:#B3123B; }
.safety-desc { font-size: 19px; margin-top: 10px; line-height:1.7; color:#222; font-weight:500; }

div.stButton > button {
    width: 100%; border-radius: 0 0 10px 10px; border: none;
    background: #333; color: #fff; font-weight: 700; font-size: 18px;
    padding: 10px 0; margin-top: -2px;
    transition: 0.2s;
}
div.stButton > button p { font-size: 18px !important; }
div.stButton > button:hover { background: #B3123B; color: #fff; }

.info-panel { background:#fafafa; border:1px solid #eee; border-radius: 12px;
    padding: 20px; height: 100%; overflow:hidden; }
.info-panel-title { font-size: 24px; font-weight: 800; color:#222; margin-bottom: 12px; }
.info-panel-desc { font-size: 19px; color:#555; margin-bottom: 14px; white-space: nowrap;
    overflow:hidden; text-overflow: ellipsis; }
.info-item { background:#fff; border:1px solid #eee; border-left:5px solid #B3123B;
    border-radius: 8px; padding: 12px 14px; margin-bottom: 10px; }
.info-item-main { display:flex; align-items:center; gap:8px;
    font-size: clamp(17px, 1.2vw, 22px); font-weight: 700; color:#111;
    white-space: nowrap; overflow:hidden; }
.info-item-main .loc-text { overflow:hidden; text-overflow: ellipsis; min-width:0; }
.info-item-sub { font-size: clamp(17px, 1.15vw, 21px); color:#555; margin-top: 6px;
    white-space: nowrap; overflow:hidden; text-overflow: ellipsis; }
.info-empty { font-size: 19px; color:#888; padding: 10px 0; }

/* 목록 번호 배지 (지도 번호 마커와 같은 색) */
.rank-badge {
    display:inline-flex; align-items:center; justify-content:center;
    width:32px; height:32px; border-radius:50%; flex-shrink:0;
    font-size:18px; font-weight:900;
    border:2px solid #FFFFFF; box-shadow:0 0 0 1px rgba(0,0,0,0.25);
}

/* 조회 결과 표 (스타일드 HTML 테이블) */
.result-table-wrap { max-height: 420px; overflow-y: auto; border:1px solid #eee; border-radius: 10px; }
.result-table-wrap table { width: 100%; border-collapse: collapse; }
.result-table-wrap th, .result-table-wrap td { text-align: center; }

/* ── 내 지역 조회 : 시·도 / 시·군·구 커스텀 라벨 (Streamlit 기본 라벨 대체) ── */
.region-select-label {
    font-size: 24px !important;
    font-weight: 900 !important;
    color: #111111 !important;
    margin-bottom: 6px;
}
div[data-baseweb="select"] * { font-size: 19px !important; }

[data-testid="stCaptionContainer"], [data-testid="stCaptionContainer"] p { font-size: 17px !important; }
</style>
""", unsafe_allow_html=True)

# 모든 Plotly 차트에서 편집 툴바(카메라·확대·이동 등 아이콘)를 숨기기 위한 공통 설정
PLOTLY_CONFIG = {"displayModeBar": False}


@st.cache_data(ttl=180)
def fetch_recent_eq():
    today = datetime.now()
    frm = (today - timedelta(days=2)).strftime("%Y%m%d")
    to = today.strftime("%Y%m%d")
    params = {"ServiceKey": KMA_KEY, "pageNo": 1, "numOfRows": 50,
              "dataType": "JSON", "fromTmFc": frm, "toTmFc": to}
    try:
        r = requests.get(KMA_URL, params=params, timeout=10)
        data = r.json()
        items = data.get("response", {}).get("body", {}).get("items", {})
        if isinstance(items, dict):
            items = items.get("item", [])
        if isinstance(items, dict):
            items = [items]
        return pd.DataFrame(items) if items else pd.DataFrame()
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=6 * 3600)
def fetch_history_eq():
    all_rows = []
    page = 1
    total = None
    while True:
        params = {"serviceKey": SAFEMAP_KEY, "pageNo": page, "numOfRows": 2000, "returnType": "JSON"}
        try:
            r = requests.get(SAFEMAP_URL, params=params, timeout=15)
            data = r.json()
        except Exception:
            break
        body = data.get("body", {})
        items = body.get("items", {})
        if isinstance(items, dict):
            items = items.get("item", [])
        if isinstance(items, dict):
            items = [items]
        if not items:
            break
        all_rows.extend(items)
        total = body.get("totalCount", len(all_rows))
        if len(all_rows) >= int(total):
            break
        page += 1
        if page > 10:
            break
    return pd.DataFrame(all_rows)


def extract_province(text):
    if not isinstance(text, str):
        return "기타"
    for key in PROVINCE_CENTER.keys():
        if text.startswith(key) or key in text[:6]:
            return key
    return "기타"


def extract_city(text):
    if not isinstance(text, str) or not text.strip():
        return "기타"
    parts = text.strip().split()
    if len(parts) >= 2:
        return f"{parts[0]} {parts[1]}"
    return parts[0] if parts else "기타"


def bin_label(cnt):
    if cnt <= 10:
        return "0 - 10건"
    elif cnt <= 50:
        return "11 - 50건"
    elif cnt <= 100:
        return "51 - 100건"
    else:
        return "100건 초과"


def fmt_date(date_str):
    try:
        return f"{date_str[:4]}년 {int(date_str[4:6])}월 {int(date_str[6:8])}일"
    except Exception:
        return date_str


# [변경] 진도 값 표시용 (값 없으면 "-")
def int_text(g):
    return f"진도 {int(g)}" if pd.notna(g) else "-"


CHART_FONT = dict(size=19, color="#111111")
TICK_FONT = dict(size=19, color="#111111")
BAR_TEXT_FONT = dict(size=19, color="#111111")


def style_fig(fig, height=420, title=None, top_margin=90, bottom_margin=50):
    fig.update_layout(
        font=CHART_FONT, height=height,
        margin=dict(t=top_margin, b=bottom_margin),
        title=dict(text=f"<b>{title}</b>", font=dict(size=25, color="#111111")) if title else None,
        plot_bgcolor="white",
    )
    fig.update_xaxes(tickfont=TICK_FONT, showgrid=False)
    fig.update_yaxes(tickfont=TICK_FONT, showgrid=True, gridcolor="#eeeeee")
    return fig


recent_df = fetch_recent_eq()
history_df = fetch_history_eq()

recent_list = []
if not recent_df.empty:
    for _, row in recent_df.iterrows():
        recent_list.append({
            "time": str(row.get("tmEqk", "")),
            "loc": row.get("loc", "-"),
            "mt": row.get("mt", "-"),
            "lat": row.get("lat"),
            "lon": row.get("lon"),
            "inT": row.get("inT", "-"),
            "fcTp": row.get("fcTp", ""),
        })

seen = set()
unique_recent = []
for item in recent_list:
    if not is_korea_domestic(item):
        continue
    key = (item["time"], item["loc"], item["mt"])
    if key not in seen:
        seen.add(key)
        unique_recent.append(item)

if not history_df.empty:
    history_df = history_df.copy()
    history_df["mt"] = pd.to_numeric(history_df.get("smints"), errors="coerce")
    history_df["loc_text"] = history_df.get("lc", "")
    history_df["lat"] = pd.to_numeric(history_df.get("lat"), errors="coerce")
    history_df["lon"] = pd.to_numeric(history_df.get("lon"), errors="coerce")
    history_df["date_str"] = history_df.get("occu_de", "").astype(str)
    history_df["year"] = history_df["date_str"].str[:4]
    history_df["province"] = history_df["loc_text"].apply(extract_province)
    history_df["city"] = history_df["loc_text"].apply(extract_city)
    history_df["intensity"] = pd.to_numeric(history_df.get("smints_gd"), errors="coerce")
    history_df = history_df.dropna(subset=["lat", "lon", "mt"])
    history_df = history_df[history_df["year"].str.isdigit()]

    def _is_south_korea(row):
        loc = str(row["loc_text"])
        if any(kw in loc for kw in NORTH_KOREA_KEYWORDS):
            return False
        lat, lon = row["lat"], row["lon"]
        if not (32.8 <= lat <= 38.65 and 124.5 <= lon <= 130.0):
            return False
        return True

    history_df = history_df[history_df.apply(_is_south_korea, axis=1)].reset_index(drop=True)


# 최근 발생 5건 : 기상청 실시간(최근) + 생활안전지도 이력을 합쳐 최신순 5건
def _to_float(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


latest_pool = []
for it in unique_recent:
    t = it["time"]
    latest_pool.append({
        "sort_key": t[:12],
        "day": t[:8],
        "disp_time": f"{t[:4]}.{t[4:6]}.{t[6:8]} {t[8:10]}:{t[10:12]}" if len(t) >= 12 else t,
        "loc": it["loc"],
        "mt": it["mt"],
        "int_disp": clean_paren(it["inT"]),
        "lat": _to_float(it["lat"]),
        "lon": _to_float(it["lon"]),
    })

if not history_df.empty:
    for _, row in history_df.sort_values("date_str", ascending=False).head(20).iterrows():
        g = row["intensity"]
        d = str(row["date_str"])
        latest_pool.append({
            "sort_key": d[:8] + "0000",
            "day": d[:8],
            "disp_time": fmt_date(d),
            "loc": row["loc_text"],
            "mt": row["mt"],
            "int_disp": str(int(g)) if pd.notna(g) else "-",
            "lat": _to_float(row["lat"]),
            "lon": _to_float(row["lon"]),
        })

latest_seen = set()
latest_dedup = []
for it in latest_pool:
    mt_f = _to_float(it["mt"])
    k = (it["day"], round(mt_f, 1) if mt_f is not None else str(it["mt"]))
    if k in latest_seen:
        continue
    latest_seen.add(k)
    latest_dedup.append(it)

latest5 = sorted(latest_dedup, key=lambda x: x["sort_key"], reverse=True)[:5]

# ---------------- 상단 배너 + 티커 ----------------
st.markdown("""
<div class="hero-box">
  <div class="hero-title">🔴 대한민국 지진 현황 알리미</div>
  <div class="hero-sub">기상청·행정안전부 공식 데이터를 기반으로 실시간 지진 속보와 최근 이력을 보여드립니다.</div>
</div>
""", unsafe_allow_html=True)

st.markdown('<div class="alert-badge">🔴 최근 3일 이내 발생 알림</div>', unsafe_allow_html=True)

if not unique_recent:
    ticker_text = "현재 최근 3일 이내 발생한 지진 속보가 없습니다."
    duration = 13
else:
    def fmt_item(it):
        t = it["time"]
        t_disp = f"{t[:4]}.{t[4:6]}.{t[6:8]} {t[8:10]}:{t[10:12]}" if len(t) >= 12 else t
        return f'🔴 {t_disp} · 진도 {clean_paren(it["inT"])} · {it["loc"]}'   # [변경] 규모 → 진도
    ticker_text = "&nbsp;&nbsp;|&nbsp;&nbsp;".join(fmt_item(it) for it in unique_recent)
    duration = max(15, len(ticker_text) // 16)

st.markdown(
    f'<div class="ticker-wrap"><div class="ticker-move" style="animation-duration:{duration}s;">{ticker_text}</div></div>',
    unsafe_allow_html=True
)

# ---------------- 실시간 지진 발생 지도 ----------------
st.markdown('<div class="section-title">🗺️ 실시간 지진 발생 지도</div>', unsafe_allow_html=True)

map_col, info_col = st.columns([1.15, 1])

with map_col:
    m_recent = folium.Map(location=[36.0, 127.7], tiles="OpenStreetMap",
                           zoom_control=False, scrollWheelZoom=False, dragging=False,
                           doubleClickZoom=False, touchZoom=False)
    fit_bounds_zoomed(m_recent, KOREA_BOUNDS)

    # 번호 마커 : 실제 위치에 작은 점 + 번호 원(목록과 같은 색·같은 번호)
    placed = []
    for idx, it in reversed(list(enumerate(latest5, 1))):   # 1번이 맨 위에 보이도록 5번부터 그림
        if it["lat"] is None or it["lon"] is None:
            continue
        bg, fg = RANK_COLORS.get(idx, ("#B3123B", "#FFFFFF"))
        near = sum(1 for (plat, plon) in placed
                   if abs(plat - it["lat"]) < 0.25 and abs(plon - it["lon"]) < 0.25)
        placed.append((it["lat"], it["lon"]))
        shift = near * 30   # 겹치는 개수만큼 오른쪽으로 30px씩 이동

        # [변경] 팝업에서 규모 줄 삭제 → 진도만 표기
        popup_html = f"""
        <div style='font-size:16px; line-height:1.6;'>
        <b>{idx}번 · 📍 진원지 :</b> {it['loc']}<br>
        <b>진도 :</b> {it['int_disp']}<br>
        <b>발생 :</b> {it['disp_time']}
        </div>
        """
        folium.CircleMarker(
            location=[it["lat"], it["lon"]],
            radius=4, color="#111111", weight=1, fill=True, fill_color=bg, fill_opacity=1,
        ).add_to(m_recent)
        folium.Marker(
            location=[it["lat"], it["lon"]],
            icon=folium.DivIcon(
                icon_size=(32, 32),
                icon_anchor=(16 - shift, 36),
                html=(
                    f'<div style="width:32px;height:32px;border-radius:50%;'
                    f'background:{bg};color:{fg};border:3px solid #FFFFFF;'
                    f'box-shadow:0 0 0 1px #111,0 2px 6px rgba(0,0,0,0.45);'
                    f'display:flex;align-items:center;justify-content:center;'
                    f'font-size:17px;font-weight:900;font-family:sans-serif;">{idx}</div>'
                ),
            ),
            popup=folium.Popup(popup_html, max_width=300),
            tooltip=f"{idx}번 · {it['loc']} · 진도 {it['int_disp']}",   # [변경] 규모 → 진도
        ).add_to(m_recent)

    with st.container(border=True):
        st_folium(m_recent, width=None, height=620, use_container_width=True, returned_objects=[])

with info_col:
    if latest5:
        items_html = ""
        for i, it in enumerate(latest5, 1):
            bg, fg = RANK_COLORS.get(i, ("#B3123B", "#FFFFFF"))
            items_html += (
                f'<div class="info-item" style="border-left:6px solid {bg};">'
                f'<div class="info-item-main" title="{it["loc"]}">'
                f'<span class="rank-badge" style="background:{bg}; color:{fg};">{i}</span>'
                f'<span class="loc-text">📍 {it["loc"]}</span></div>'
                f'<div class="info-item-sub">진도 {it["int_disp"]} · {it["disp_time"]}</div>'
                f'</div>'
            )
    else:
        items_html = '<div class="info-empty">표시할 지진 발생 기록이 없습니다.</div>'

    st.markdown(
        f'<div class="info-panel">'
        f'<div class="info-panel-title">📋 최근 발생 지진 5건</div>'
        f'<div class="info-panel-desc">'
        f'가장 최근에 발생한 지진 <b style="color:#B3123B; font-size:22px;">{len(latest5)}건</b>을 최신순으로 보여드립니다.'
        f'</div>'
        f'{items_html}'
        f'</div>',
        unsafe_allow_html=True
    )

# ---------------- 진도별 설명 + 영상 ----------------
st.markdown('<div class="section-title">📺 지진 규모와 진도, 클릭해서 실제 피해 영상을 확인하세요</div>', unsafe_allow_html=True)

if "selected_level" not in st.session_state:
    st.session_state.selected_level = None

cols = st.columns(len(INTENSITY_LEVELS))
for col, lvl in zip(cols, INTENSITY_LEVELS):
    with col:
        st.markdown(f"""
        <div class="level-card" style="background:{lvl['color']};">
        {lvl['label']}
        <div class="level-sub">{lvl['desc']}</div>
        </div>
        """, unsafe_allow_html=True)
        if st.button("▶ 영상보기", key=f"btn_{lvl['key']}", use_container_width=True):
            st.session_state.selected_level = lvl["key"]
            st.rerun()

if st.session_state.selected_level:
    lvl = next(l for l in INTENSITY_LEVELS if l["key"] == st.session_state.selected_level)
    st.markdown(f"### 🎬 {lvl['label']} — {lvl['desc']}")
    st.markdown(f"<p style='font-size:20px;'>{lvl['detail']}</p>", unsafe_allow_html=True)
    vc1, vc2, vc3 = st.columns([1, 2, 1])
    with vc2:
        st.video(lvl["video"])
    cc1, cc2, cc3 = st.columns([2, 1, 2])
    with cc2:
        if st.button("✕ 영상 닫기", key="close_video", use_container_width=True):
            st.session_state.selected_level = None
            st.rerun()

# ---------------- 안전 행동 요령 ----------------
st.markdown('<div class="section-title">🛡️ 지진 발생 시 행동 요령 (단계별)</div>', unsafe_allow_html=True)

if "selected_safety" not in st.session_state:
    st.session_state.selected_safety = None

cols = st.columns(4)
for col, step in zip(cols, SAFETY_STEPS):
    with col:
        st.markdown(f"""
        <div class="safety-card">
        <div class="safety-title">{step['title']}</div>
        <div class="safety-desc">{step['desc']}</div>
        </div>
        """, unsafe_allow_html=True)
        if st.button("▶ 참고영상 보기", key=f"safety_{step['key']}", use_container_width=True):
            st.session_state.selected_safety = step["key"]
            st.rerun()

if st.session_state.selected_safety:
    step = next(s for s in SAFETY_STEPS if s["key"] == st.session_state.selected_safety)
    st.markdown(f"### 🎬 {step['title']} 참고영상")
    vc1, vc2, vc3 = st.columns([1, 2, 1])
    with vc2:
        st.video(step["video"])
    cc1, cc2, cc3 = st.columns([2, 1, 2])
    with cc2:
        if st.button("✕ 영상 닫기", key="close_safety_video", use_container_width=True):
            st.session_state.selected_safety = None
            st.rerun()

# ---------------- 이력 통계 ----------------
st.markdown('<div class="section-title">📊 지진 발생 이력 통계</div>', unsafe_allow_html=True)

if not history_df.empty:
    years_sorted = sorted(history_df["year"].dropna().unique())
    start_y, end_y = years_sorted[0], years_sorted[-1]
    st.markdown(f'<div class="data-range">📅 데이터 기준 기간 : {start_y}년 1월 ~ {end_y}년 9월 (행정안전부 생활안전지도, 규모 2.0 이상 기준)</div>', unsafe_allow_html=True)
    st.markdown('<div class="sub-title">📌 전체 이력 요약</div>', unsafe_allow_html=True)

    history_kr = history_df.copy()

    total_cnt = len(history_kr)
    # [변경] 역대 최대 규모 → 역대 최대 진도
    int_valid = history_kr.dropna(subset=["intensity"])
    if not int_valid.empty:
        max_row = int_valid.loc[int_valid["intensity"].idxmax()]
        max_num = int_text(max_row["intensity"])
        max_sub = f"{fmt_date(max_row['date_str'])} · {max_row['loc_text']}"
    else:
        max_num, max_sub = "-", "&nbsp;"
    city_counts = history_kr["city"].value_counts()
    top_city = city_counts.index[0]
    top_city_cnt = city_counts.iloc[0]
    top_city_pct = round(top_city_cnt / total_cnt * 100, 1)

    c1, c2, c3 = st.columns(3)
    with c1:
        # [변경] 설명 줄 자리 확보(빈 줄) → 3칸 높이·위치 정렬
        st.markdown(f"""<div class="stat-card stat-navy">
        <div class="stat-label">전체 지진 발생 건수</div>
        <div class="stat-num">{total_cnt:,}건</div>
        <div class="stat-sub">&nbsp;</div>
        </div>""", unsafe_allow_html=True)
    with c2:
        st.markdown(f"""<div class="stat-card stat-navy">
        <div class="stat-label">역대 최대 진도</div>
        <div class="stat-num">{max_num}</div>
        <div class="stat-sub" title="{max_sub}">{max_sub}</div>
        </div>""", unsafe_allow_html=True)
    with c3:
        st.markdown(f"""<div class="stat-card stat-navy">
        <div class="stat-label">발생 최다 지역</div>
        <div class="stat-num">{top_city}</div>
        <div class="stat-sub">{top_city_cnt:,}건 · 전체의 {top_city_pct}%</div>
        </div>""", unsafe_allow_html=True)

    st.markdown('<div class="chart-gap"></div>', unsafe_allow_html=True)

    yearly = history_kr.groupby("year").size().reset_index(name="cnt")
    mean_v, std_v = yearly["cnt"].mean(), yearly["cnt"].std()
    yearly["color"] = yearly["cnt"].apply(lambda x: "#B3123B" if x > mean_v + std_v else "#9c9c9c")

    fig_year = go.Figure(go.Bar(
        x=yearly["year"], y=yearly["cnt"], marker_color=yearly["color"],
        text=[f"{v}건" for v in yearly["cnt"]], textposition="outside",
        textfont=BAR_TEXT_FONT, cliponaxis=False
    ))
    fig_year = style_fig(fig_year, height=460, title=f"연도별 지진 발생 건수 ({start_y}년 1월 ~ {end_y}년 9월)")
    fig_year.update_xaxes(type="category", dtick=1, tickangle=0)
    st.plotly_chart(fig_year, use_container_width=True, config=PLOTLY_CONFIG)

    st.markdown('<div class="chart-gap"></div>', unsafe_allow_html=True)

    city_top = city_counts.head(15).reset_index()
    city_top.columns = ["city", "cnt"]
    city_top["color"] = city_top["cnt"].apply(
        lambda x: "#B3123B" if x == city_top["cnt"].max() else "#9c9c9c"
    )

    fig_city = go.Figure(go.Bar(
        x=city_top["city"], y=city_top["cnt"], marker_color=city_top["color"],
        text=[f"{v}건" for v in city_top["cnt"]], textposition="outside",
        textfont=BAR_TEXT_FONT, cliponaxis=False
    ))
    fig_city = style_fig(fig_city, height=500, title="지역별(도·시 단위) 지진 발생 건수 TOP 15", bottom_margin=120)
    fig_city.update_xaxes(tickangle=-30, tickfont=TICK_FONT)
    st.plotly_chart(fig_city, use_container_width=True, config=PLOTLY_CONFIG)

    st.markdown('<div class="chart-gap"></div>', unsafe_allow_html=True)

    # [변경] 규모별 발생 분포 → 진도별 발생 분포 (가로축 : 진도 단계)
    int_dist = history_df["intensity"].dropna().astype(int).value_counts().sort_index().reset_index()
    int_dist.columns = ["grade", "cnt"]
    int_dist["label"] = int_dist["grade"].apply(lambda g: f"진도 {g}")

    fig_mag = go.Figure(go.Bar(
        x=int_dist["label"], y=int_dist["cnt"], marker_color="#B3123B",
        text=[f"{v:,}건" for v in int_dist["cnt"]], textposition="outside",
        textfont=BAR_TEXT_FONT, cliponaxis=False
    ))
    fig_mag = style_fig(fig_mag, height=440, title="진도별 발생 분포", bottom_margin=70)
    fig_mag.update_xaxes(title_text="진도", type="category")
    fig_mag.update_yaxes(title_text="건수")
    st.plotly_chart(fig_mag, use_container_width=True, config=PLOTLY_CONFIG)

    # ---------------- 지역별 발생 빈도 지도 + 강도(진도) 지도 ----------------
    st.markdown('<div class="section-title">🎯 지역별 지진 발생 빈도 · 강도 지도</div>', unsafe_allow_html=True)
    st.markdown(f'<div class="data-range">📅 데이터 기준 기간 : {start_y}년 1월 ~ {end_y}년 9월</div>', unsafe_allow_html=True)

    province_counts = history_df["province"].value_counts().to_dict()

    freq_col, intensity_col = st.columns(2)

    with freq_col:
        st.markdown("<div style='font-size:21px; font-weight:800; margin-bottom:8px;'>🔴 지역별 발생 빈도</div>", unsafe_allow_html=True)
        legend_html = "".join([
            f'<span class="legend-chip" style="background:{c};">{label}</span>'
            for label, c in BIN_COLORS.items()
        ])
        st.markdown(legend_html, unsafe_allow_html=True)
        st.write("")

        m_freq = folium.Map(location=[36.0, 127.7], tiles="OpenStreetMap",
                             zoom_control=False, scrollWheelZoom=False, dragging=False,
                             doubleClickZoom=False, touchZoom=False)
        fit_bounds_zoomed(m_freq, KOREA_BOUNDS)

        for _, row in history_df.iterrows():
            prov = row["province"]
            cnt = province_counts.get(prov, 0)
            label = bin_label(cnt)
            color = BIN_COLORS[label]
            g = row["intensity"]
            g_disp = int(g) if pd.notna(g) else "-"
            # [변경] 강도(규모) → 진도
            popup_html = f"""
            <div style='font-size:16px; line-height:1.6;'>
            <b>📍 진원지 :</b> {row['loc_text']}<br>
            <b>진도 :</b> {g_disp}<br>
            <b>{prov} 누적 발생 :</b> {cnt}건 ({label})
            </div>
            """
            folium.CircleMarker(
                location=[row["lat"], row["lon"]],
                radius=3.5, color=color, fill=True, fill_color=color, fill_opacity=0.85,
                popup=folium.Popup(popup_html, max_width=280),
            ).add_to(m_freq)

        with st.container(border=True):
            st_folium(m_freq, width=None, height=560, use_container_width=True, returned_objects=[])

    with intensity_col:
        st.markdown("<div style='font-size:21px; font-weight:800; margin-bottom:8px;'>🟠 지역별 발생 강도(진도)</div>", unsafe_allow_html=True)

        grades_present = sorted(history_df["intensity"].dropna().unique().astype(int).tolist())
        legend_html2 = "".join([
            f'<span class="legend-chip legend-chip-dark" style="background:{intensity_color(g)};">진도 {g}</span>'
            for g in grades_present
        ])
        st.markdown(legend_html2 if legend_html2 else "<span style='color:#888;'>진도 정보 없음</span>", unsafe_allow_html=True)
        st.write("")

        m_intensity = folium.Map(location=[36.0, 127.7], tiles="OpenStreetMap",
                                  zoom_control=False, scrollWheelZoom=False, dragging=False,
                                  doubleClickZoom=False, touchZoom=False)
        fit_bounds_zoomed(m_intensity, KOREA_BOUNDS)

        for _, row in history_df.iterrows():
            grade = row["intensity"]
            color = intensity_color(grade)
            grade_disp = int(grade) if pd.notna(grade) else "-"
            # [변경] 강도(규모) 줄 삭제 → 진도만 표기
            popup_html = f"""
            <div style='font-size:16px; line-height:1.6;'>
            <b>📍 진원지 :</b> {row['loc_text']}<br>
            <b>진도 :</b> {grade_disp}
            </div>
            """
            folium.CircleMarker(
                location=[row["lat"], row["lon"]],
                radius=3.5, color=color, fill=True, fill_color=color, fill_opacity=0.85,
                popup=folium.Popup(popup_html, max_width=280),
            ).add_to(m_intensity)

        with st.container(border=True):
            st_folium(m_intensity, width=None, height=560, use_container_width=True, returned_objects=[])

    # ---------------- 내 지역 지진 발생기록 찾기 ----------------
    st.markdown('<div class="section-title">🔎 내 지역 지진 발생기록 찾기</div>', unsafe_allow_html=True)
    st.markdown(
        "<div class='intro-text'>"
        "실제 관측 데이터를 기반으로, 원하시는 시·도와 시·군·구를 선택하면 해당 지역에서 발생한 "
        "지진 이력을 날짜·규모·진도까지 모두 조회할 수 있습니다.</div>",
        unsafe_allow_html=True
    )

    with st.container(border=True):
        available_provinces = sorted(
            [p for p in history_kr["province"].unique() if p != "기타"]
        )

        s1, s2 = st.columns(2)
        with s1:
            st.markdown('<div class="region-select-label">① 시·도 선택</div>', unsafe_allow_html=True)
            sel_province = st.selectbox(
                "시도선택", ["전체"] + available_provinces,
                key="my_region_province", label_visibility="collapsed"
            )
        with s2:
            st.markdown('<div class="region-select-label">② 시·군·구 선택</div>', unsafe_allow_html=True)
            if sel_province == "전체":
                city_options = ["전체"] + sorted(history_kr["city"].unique().tolist())
            else:
                city_options = ["전체"] + sorted(
                    history_kr[history_kr["province"] == sel_province]["city"].unique().tolist()
                )
            sel_city = st.selectbox(
                "시군구선택", city_options,
                key="my_region_city", label_visibility="collapsed"
            )

        result_df = history_kr.copy()
        if sel_province != "전체":
            result_df = result_df[result_df["province"] == sel_province]
        if sel_city != "전체":
            result_df = result_df[result_df["city"] == sel_city]

        result_df = result_df.sort_values("date_str", ascending=False)

        region_label = sel_city if sel_city != "전체" else (sel_province if sel_province != "전체" else "전국")

        if result_df.empty:
            st.markdown(f"<div class='info-empty'>선택하신 '{region_label}' 지역에서는 관측 이력이 없습니다.</div>", unsafe_allow_html=True)
        else:
            r_total = len(result_df)
            r_latest = result_df.iloc[0]
            # [변경] 최대 규모 → 최대 진도
            r_valid = result_df.dropna(subset=["intensity"])
            if not r_valid.empty:
                r_max = r_valid.loc[r_valid["intensity"].idxmax()]
                r_max_num = int_text(r_max["intensity"])
                r_max_sub = fmt_date(r_max["date_str"])
            else:
                r_max_num, r_max_sub = "-", "&nbsp;"

            rc1, rc2, rc3 = st.columns(3)
            with rc1:
                # [변경] 설명 줄 자리 확보(빈 줄) → 3칸 높이·위치 정렬
                st.markdown(f"""<div class="stat-card stat-navy">
                <div class="stat-label">{region_label} 발생 건수</div>
                <div class="stat-num">{r_total:,}건</div>
                <div class="stat-sub">&nbsp;</div>
                </div>""", unsafe_allow_html=True)
            with rc2:
                st.markdown(f"""<div class="stat-card stat-navy">
                <div class="stat-label">최대 진도</div>
                <div class="stat-num">{r_max_num}</div>
                <div class="stat-sub">{r_max_sub}</div>
                </div>""", unsafe_allow_html=True)
            with rc3:
                # [변경] 규모 → 진도
                st.markdown(f"""<div class="stat-card stat-navy">
                <div class="stat-label">가장 최근 발생</div>
                <div class="stat-num">{fmt_date(r_latest['date_str'])}</div>
                <div class="stat-sub">{int_text(r_latest['intensity'])}</div>
                </div>""", unsafe_allow_html=True)

            st.write("")

            # [변경] 규모 열 삭제 → 진도 열만 표시
            table_df = result_df[["date_str", "loc_text", "intensity"]].copy()
            table_df["date_str"] = table_df["date_str"].apply(fmt_date)
            table_df["intensity"] = table_df["intensity"].apply(int_text)
            table_df.columns = ["발생일자", "진원지(상세위치)", "진도"]

            styled_table = (
                table_df.reset_index(drop=True).style
                .set_properties(**{"font-size": "19px", "padding": "10px 8px"})
                .set_table_styles([
                    {"selector": "th", "props": [("font-size", "19px"), ("font-weight", "800"),
                                                   ("background-color", "#B3123B"), ("color", "#ffffff"),
                                                   ("padding", "10px 8px")]},
                ])
                .hide(axis="index")
            )
            st.markdown(
                f"<div class='result-table-wrap'>{styled_table.to_html()}</div>",
                unsafe_allow_html=True
            )

else:
    st.warning("이력 데이터를 불러오지 못했습니다. API 키 또는 네트워크 상태를 확인해주세요.")

st.markdown("---")
st.caption(f"※ 데이터 출처 : 기상청 지진정보(EqkInfoService), 행정안전부 생활안전지도(safemap.go.kr) · "
            f"조회 시각 {datetime.now().strftime('%Y-%m-%d %H:%M')}")
