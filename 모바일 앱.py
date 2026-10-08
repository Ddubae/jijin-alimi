import re
from datetime import datetime, timedelta

import requests
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
import folium
from streamlit_folium import st_folium
import streamlit as st

st.set_page_config(page_title="대한민국 지진 알리미 (모바일)", page_icon="🌍", layout="centered")

# ------------------------------------------------------------------
# 자동 번역 방지
# ------------------------------------------------------------------
NOTRANSLATE_SCRIPT = """
<script>
(function() {
    var meta = document.createElement('meta');
    meta.name = "google";
    meta.content = "notranslate";
    document.getElementsByTagName('head')[0].appendChild(meta);
    document.documentElement.setAttribute('translate', 'no');
    document.documentElement.classList.add('notranslate');
    document.body.classList.add('notranslate');
})();
</script>
"""
st.markdown(NOTRANSLATE_SCRIPT, unsafe_allow_html=True)

# ------------------------------------------------------------------
# 상수 / API 설정 (원본 PC버전 데이터 로직과 완전히 동일 - 절대 변경 금지 영역)
# ------------------------------------------------------------------
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

WEEKDAY_KR = ["월", "화", "수", "목", "금", "토", "일"]


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


def to_watch_url(embed_url):
    return embed_url.replace("/embed/", "/watch?v=")


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


def parse_history_dt(date_str):
    try:
        return datetime.strptime(str(date_str)[:8], "%Y%m%d")
    except Exception:
        return None


def fmt_date_wd(date_str):
    base = fmt_date(date_str)
    dt = parse_history_dt(date_str)
    if dt:
        return f"{base}({WEEKDAY_KR[dt.weekday()]})"
    return base


def parse_recent_dt(t):
    try:
        return datetime.strptime(str(t)[:12], "%Y%m%d%H%M")
    except Exception:
        return None


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


# ------------------------------------------------------------------
# 모바일 전용 CSS ("중대재해 알리미" 모바일 디자인 패턴 적용 — 내용(데이터)은 지진 원본 그대로)
# ------------------------------------------------------------------
mobile_css = """
<style>
#MainMenu {visibility: hidden;}
footer {visibility: hidden;}
header {visibility: hidden;}
[data-testid="stToolbar"] {display: none;}
[data-testid="stDecoration"] {display: none;}

:root { color-scheme: light only; }
html, body, .stApp { color-scheme: light; }

.block-container {
    padding-top: 0rem;
    padding-bottom: 6.5rem;
    max-width: 480px;
    margin: 0 auto;
}
body, .stApp { background-color: #EEF1F6; }

/* 상단 앱바 */
.app-bar {
    position: sticky;
    top: 0;
    z-index: 999;
    display: flex;
    align-items: center;
    gap: 12px;
    background: linear-gradient(120deg, #0B2545, #173A6A);
    padding: 16px 18px;
    margin: 0 -1rem 16px -1rem;
    box-shadow: 0 4px 14px rgba(11,37,69,0.25);
}
.app-bar-icon {
    width: 42px; height: 42px;
    background: rgba(255,255,255,0.15);
    border-radius: 12px;
    display: flex; align-items: center; justify-content: center;
    font-size: 22px;
}
.app-bar-text { flex: 1; }
.app-bar-title { color: white !important; font-size: 18px; font-weight: 800; letter-spacing: -0.3px; }
.app-bar-sub { color: #BFD0EA !important; font-size: 12.5px; font-weight: 500; margin-top: 2px; }
.app-bar-live {
    display: flex; align-items: center; gap: 5px;
    background: rgba(179,18,59,0.85);
    color: white !important; font-size: 11px; font-weight: 800;
    padding: 5px 10px; border-radius: 999px;
}
.live-dot {
    width: 7px; height: 7px; border-radius: 50%;
    background: #FFEB3B;
    animation: blink 1.2s infinite;
}
@keyframes blink { 0%,100% {opacity:1;} 50% {opacity:0.3;} }

/* 속보 배너 */
.m-ticker {
    position: relative;
    background: #14171C;
    border-radius: 12px;
    overflow: hidden;
    margin-bottom: 18px;
    height: 40px;
}
.m-ticker-tag {
    position: absolute; top: 0; left: 0; bottom: 0; width: 72px; z-index: 3;
    display: flex; align-items: center; justify-content: center;
    background: #B3123B; color: white !important; font-size: 12px; font-weight: 800;
    white-space: nowrap; border-radius: 12px 0 0 12px;
    box-shadow: 3px 0 8px rgba(0,0,0,0.35);
}
.m-ticker-scroll {
    position: absolute; top: 0; left: 72px; right: 0; bottom: 0;
    overflow: hidden; white-space: nowrap; line-height: 40px;
}
.m-ticker-move {
    display: inline-block; padding-left: 100%;
    animation: m-scroll 50s linear infinite;
    color: #F2C744 !important; font-size: 13px; font-weight: 600; line-height: 40px;
}
@keyframes m-scroll { 0% { transform: translateX(0); } 100% { transform: translateX(-100%); } }

/* 섹션 타이틀 */
.m-section-title {
    font-size: 18px; font-weight: 800; color: #0B2545 !important;
    margin: 22px 2px 12px 2px; padding-left: 10px; border-left: 5px solid #B3123B;
}
.m-section-sub {
    display: block; font-size: 13px; font-weight: 700; color: #5A6B85 !important; margin-top: 4px;
}

/* 아코디언(정의) */
[data-testid="stExpander"] {
    border: none !important; border-radius: 14px !important; overflow: hidden;
    box-shadow: 0 2px 10px rgba(15,30,60,0.07); margin-bottom: 6px; background: white !important;
}
[data-testid="stExpander"] summary { background: #0B2545 !important; }
[data-testid="stExpander"] summary,
[data-testid="stExpander"] summary p,
[data-testid="stExpander"] summary span,
[data-testid="stExpander"] summary svg {
    color: #FFFFFF !important; fill: #FFFFFF !important; font-weight: 800 !important;
}
[data-testid="stExpander"] > div,
[data-testid="stExpander"] > div * { color: #1A1D21 !important; }

.m-def-item {
    display: flex; align-items: flex-start; gap: 8px;
    font-size: 14px; font-weight: 700; color: #222 !important; line-height: 1.7; margin-bottom: 10px;
}
.m-def-badge {
    flex-shrink: 0; margin-top: 1px; background: #0B2545; color: white !important;
    font-weight: 800; font-size: 11px; padding: 2px 8px; border-radius: 999px;
}
.m-def-text { flex: 1; min-width: 0; }

/* 캐러셀 (가로 스와이프 카드) */
.m-carousel {
    display: flex; gap: 12px; overflow-x: auto; scroll-snap-type: x mandatory;
    padding: 4px 2px 14px 2px; -webkit-overflow-scrolling: touch;
}
.m-carousel::-webkit-scrollbar { height: 4px; }
.m-carousel::-webkit-scrollbar-thumb { background: #C9D2DE; border-radius: 10px; }

.m-card {
    flex: 0 0 86%; scroll-snap-align: center; background: white; border-radius: 18px;
    box-shadow: 0 6px 18px rgba(15,30,60,0.12); overflow: hidden; border: 1px solid #E7EAEE;
}
.m-card-head { position: relative; padding: 16px 16px 18px 16px; text-align: center; color: white !important; }
.m-card-head-top { display: flex; justify-content: flex-start; margin-bottom: 12px; }
.m-badge {
    display: inline-block; padding: 5px 12px; border-radius: 999px;
    color: white !important; font-size: 12px; font-weight: 800;
    background: rgba(0,0,0,0.30); border: 1px solid rgba(255,255,255,0.5); white-space: nowrap;
}
.m-date { font-size: 17px; font-weight: 900; line-height: 1.3; color: white !important; }

.m-card-body { padding: 14px 16px 4px 16px; }
.m-field { margin-bottom: 12px; }
.m-field-label { font-size: 11.5px; font-weight: 800; color: #7A8699 !important; margin-bottom: 3px; letter-spacing: 0.2px; }
.m-field-value { font-size: 14.5px; font-weight: 600; color: #1a1a1a !important; line-height: 1.55; }
.m-tip-box {
    border-radius: 10px; padding: 10px 12px; font-size: 13px; font-weight: 700;
    line-height: 1.5; margin-bottom: 10px; background: #FFF8E1; color: #8A6D00 !important;
}
.m-detail-btn {
    display: block; text-align: center; background: #0B2545; color: white !important;
    padding: 13px; margin: 6px 16px 16px 16px; border-radius: 10px;
    text-decoration: none; font-weight: 800; font-size: 14px;
}

/* 통계 카드 */
.m-stat-grid { display: flex; flex-wrap: wrap; gap: 10px; margin-bottom: 6px; }
.m-stat-card {
    flex: 1 1 28%; background: white; border-radius: 14px;
    box-shadow: 0 3px 10px rgba(15,30,60,0.08); padding: 14px 8px; text-align: center;
}
.m-stat-label { font-size: 11.5px; font-weight: 700; color: #667 !important; margin-bottom: 5px; }
.m-stat-value { font-size: 20px; font-weight: 900; }
.m-stat-sub { font-size: 10.5px; font-weight: 600; color: #8894A6 !important; margin-top: 3px; }

/* 순위 카드 */
.m-top-wrap { background: white !important; border-radius: 14px; padding: 16px; box-shadow: 0 3px 10px rgba(15,30,60,0.08); margin-bottom: 16px; }
.m-top-title { font-size: 15px; font-weight: 800; color: #0B2545 !important; margin-bottom: 10px; }
.m-top-item-head { display: flex; justify-content: space-between; font-size: 13.5px; font-weight: 700; margin-bottom: 4px; }
.m-top-item-head span { color: #1A1D21 !important; }
.m-top-bar-bg { background: #EEF0F3; border-radius: 6px; height: 14px; overflow: hidden; }
.m-top-bar-fill { height: 100%; border-radius: 6px; }
.m-top-item { margin-bottom: 12px; }

/* 리스트 카드 */
.m-list-wrap { max-height: 520px; overflow-y: auto; padding-right: 2px; }
.m-list-item {
    display: flex; gap: 10px; background: white; border-radius: 12px;
    padding: 12px 14px; margin-bottom: 8px; box-shadow: 0 2px 6px rgba(15,30,60,0.06);
}
.m-list-stripe { width: 5px; border-radius: 4px; flex-shrink: 0; }
.m-list-main { flex: 1; min-width: 0; }
.m-list-top { display: flex; justify-content: space-between; align-items: center; margin-bottom: 4px; flex-wrap: wrap; gap: 6px; }
.m-list-date { font-size: 12px; font-weight: 800; color: #555 !important; }
.m-list-type {
    display: inline-block; font-size: 11px; font-weight: 800; line-height: 1.6 !important;
    padding: 4px 9px !important; border-radius: 999px; color: white !important; white-space: nowrap;
}
.m-list-loc { font-size: 13px; font-weight: 700; color: #0B2545 !important; margin-bottom: 3px; }
.m-list-content { font-size: 12.5px; color: #444 !important; line-height: 1.5; word-break: keep-all; }
.m-list-link { font-size: 11.5px; font-weight: 800; color: #0B2545 !important; text-decoration: none; white-space: nowrap; align-self: center; }
.m-empty-msg { font-size: 13px; color: #8894A6 !important; text-align: center; padding: 24px 0; }

/* 지도/카드형 컨테이너 공통 (st.container(border=True)를 카드처럼) */
[data-testid="stVerticalBlockBorderWrapper"] {
    border-radius: 14px !important; border: none !important;
    box-shadow: 0 3px 10px rgba(15,30,60,0.08) !important;
    overflow: hidden; margin-bottom: 14px; background: white !important;
}

/* 범례 칩 (가로 스크롤 허용) */
.m-legend-row { display: flex; gap: 8px; overflow-x: auto; padding: 2px 2px 10px 2px; -webkit-overflow-scrolling: touch; }
.m-legend-chip {
    flex-shrink: 0; display: inline-block; padding: 5px 12px; border-radius: 999px;
    color: #fff !important; font-size: 12px; font-weight: 800; white-space: nowrap; letter-spacing: 0.3px;
}
.m-legend-chip-dark { color: #111 !important; border: 1px solid #ccc; }

/* 내 지역 선택 라벨 */
.m-select-label {
    font-size: 15px; font-weight: 800; color: #0B2545 !important; margin: 4px 0 4px 2px;
}

/* 하단 고정 바 */
.m-bottom-bar {
    position: fixed; bottom: 0; left: 0; right: 0; z-index: 998;
    background: white; box-shadow: 0 -4px 14px rgba(0,0,0,0.08);
    padding: 10px 16px calc(10px + env(safe-area-inset-bottom, 0px)) 16px;
}
.m-bottom-info { text-align: center; font-size: 11px; color: #8894A6 !important; margin-bottom: 6px; }
</style>
"""
st.markdown(mobile_css, unsafe_allow_html=True)

CHART_CONFIG = {
    "staticPlot": False,
    "displayModeBar": False,
    "scrollZoom": False,
    "doubleClick": False,
    "showTips": False,
    "responsive": True,
}

# ------------------------------------------------------------------
# 데이터 로딩 & 가공 (원본 PC버전과 동일 로직)
# ------------------------------------------------------------------
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
        })

seen = set()
unique_recent = []
for item in recent_list:
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

# ------------------------------------------------------------------
# 상단 앱바
# ------------------------------------------------------------------
st.markdown(
    '<div class="app-bar">'
    '<div class="app-bar-icon">🌍</div>'
    '<div class="app-bar-text">'
    '<div class="app-bar-title">대한민국 지진 알리미</div>'
    '<div class="app-bar-sub">실시간 속보 · 누적 통계</div>'
    '</div>'
    '<div class="app-bar-live"><span class="live-dot"></span>LIVE</div>'
    '</div>',
    unsafe_allow_html=True
)

# ------------------------------------------------------------------
# 속보 티커
# ------------------------------------------------------------------
if unique_recent:
    ticker_parts = []
    for it in unique_recent[:6]:
        t = it["time"]
        t_disp = f"{t[4:6]}월 {t[6:8]}일 {t[8:10]}:{t[10:12]}" if len(t) >= 12 else t
        ticker_parts.append(f"📢 {t_disp} · {it['loc']} · 규모 {it['mt']} · 진도 {clean_paren(it['inT'])}")
    ticker_text = "&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;".join(ticker_parts)
else:
    ticker_text = "현재 최근 3일 이내 발생한 지진 속보가 없습니다."

st.markdown(
    '<div class="m-ticker">'
    '<div class="m-ticker-tag">🔴 속보</div>'
    '<div class="m-ticker-scroll"><div class="m-ticker-move">' + ticker_text + '</div></div>'
    '</div>',
    unsafe_allow_html=True
)

# ------------------------------------------------------------------
# 정의 아코디언 (규모 vs 진도)
# ------------------------------------------------------------------
with st.expander("📌 지진 규모와 진도, 무엇이 다를까요?"):
    st.markdown(
        '<div class="m-def-item"><span class="m-def-badge">1</span>'
        '<span class="m-def-text"><b>규모(Magnitude)</b> — 지진 자체가 가진 에너지의 절대적인 크기를 나타내는 값입니다.</span></div>'
        '<div class="m-def-item"><span class="m-def-badge">2</span>'
        '<span class="m-def-text"><b>진도(Intensity)</b> — 특정 지점에서 사람이 느끼거나 건물이 받는 흔들림과 피해 정도를 나타내는 값입니다.</span></div>'
        '<div class="m-def-item"><span class="m-def-badge">3</span>'
        '<span class="m-def-text">같은 규모라도 거리·지반 조건에 따라 지역별 진도는 다르게 나타날 수 있습니다.</span></div>',
        unsafe_allow_html=True
    )

# ------------------------------------------------------------------
# 최근 발생 지진 - 가로 스와이프 캐러셀
# ------------------------------------------------------------------
st.markdown('<div class="m-section-title">🚨 최근 3일 이내 발생 지진</div>', unsafe_allow_html=True)

if not unique_recent:
    st.markdown('<div class="m-empty-msg">현재 최근 3일 이내 발생한 지진이 없습니다.<br>평소 대비 요령을 미리 확인해보세요.</div>', unsafe_allow_html=True)
else:
    def build_recent_card_html(it, idx):
        t = it["time"]
        dt = parse_recent_dt(t)
        if dt:
            date_display = f"{dt.year}. {dt.month}. {dt.day}.({WEEKDAY_KR[dt.weekday()]}) {dt.hour:02d}:{dt.minute:02d}"
        else:
            date_display = t if t else "시각 미상"

        bg = "#B3123B" if idx == 0 else "#7A0000"
        lat, lon = it.get("lat"), it.get("lon")
        map_link = f"https://www.google.com/maps?q={lat},{lon}" if lat and lon else "#"

        html = []
        html.append('<div class="m-card">')
        html.append(f'<div class="m-card-head" style="background:{bg};">')
        html.append(f'<div class="m-card-head-top"><span class="m-badge">규모 {it["mt"]}</span></div>')
        html.append(f'<div class="m-date">{date_display}</div>')
        html.append('</div>')
        html.append('<div class="m-card-body">')
        html.append(f'<div class="m-field"><div class="m-field-label">📍 진원지</div><div class="m-field-value">{it["loc"]}</div></div>')
        html.append(f'<div class="m-field"><div class="m-field-label">📊 진도</div><div class="m-field-value">{clean_paren(it["inT"])}</div></div>')
        html.append('</div>')
        html.append(f'<a class="m-detail-btn" href="{map_link}" target="_blank">📍 지도에서 위치 확인</a>')
        html.append('</div>')
        return "".join(html)

    carousel_html = '<div class="m-carousel">' + "".join(
        build_recent_card_html(it, idx) for idx, it in enumerate(unique_recent)
    ) + '</div>'
    st.markdown(carousel_html, unsafe_allow_html=True)

# ------------------------------------------------------------------
# 실시간 지진 발생 지도
# ------------------------------------------------------------------
st.markdown('<div class="m-section-title">🗺️ 실시간 지진 발생 지도</div>', unsafe_allow_html=True)

with st.container(border=True):
    m_recent = folium.Map(location=[36.0, 127.7], tiles="OpenStreetMap",
                           zoom_control=False, scrollWheelZoom=False, dragging=False,
                           doubleClickZoom=False, touchZoom=False)
    fit_bounds_zoomed(m_recent, KOREA_BOUNDS)

    if unique_recent:
        for it in unique_recent:
            if it["lat"] is None or it["lon"] is None:
                continue
            popup_html = f"""
            <div style='font-size:14px; line-height:1.6;'>
            <b>📍 진원지 :</b> {it['loc']}<br>
            <b>강도(규모) :</b> {it['mt']}<br>
            <b>진도 :</b> {clean_paren(it['inT'])}
            </div>
            """
            folium.CircleMarker(
                location=[float(it["lat"]), float(it["lon"])],
                radius=8, color="#D9534F", fill=True, fill_color="#D9534F", fill_opacity=0.9,
                popup=folium.Popup(popup_html, max_width=260),
                tooltip=f"{it['loc']} · 규모 {it['mt']}"
            ).add_to(m_recent)

    st_folium(m_recent, width=None, height=400, use_container_width=True, returned_objects=[])

# ------------------------------------------------------------------
# 진도 단계별 설명 - 가로 스와이프 캐러셀
# ------------------------------------------------------------------
st.markdown('<div class="m-section-title">📺 진도 단계별 피해 정도</div>', unsafe_allow_html=True)

def build_level_card_html(lvl):
    html = []
    html.append('<div class="m-card">')
    html.append(f'<div class="m-card-head" style="background:{lvl["color"]};">')
    html.append(f'<div class="m-card-head-top"><span class="m-badge">{lvl["label"]}</span></div>')
    html.append(f'<div class="m-date">{lvl["desc"]}</div>')
    html.append('</div>')
    html.append('<div class="m-card-body">')
    html.append(f'<div class="m-field-label">📝 상세 설명</div>')
    html.append(f'<div class="m-tip-box">{lvl["detail"]}</div>')
    html.append('</div>')
    html.append(f'<a class="m-detail-btn" href="{to_watch_url(lvl["video"])}" target="_blank">▶ 영상으로 보기</a>')
    html.append('</div>')
    return "".join(html)

level_carousel_html = '<div class="m-carousel">' + "".join(
    build_level_card_html(lvl) for lvl in INTENSITY_LEVELS
) + '</div>'
st.markdown(level_carousel_html, unsafe_allow_html=True)

# ------------------------------------------------------------------
# 행동요령 4단계 - 가로 스와이프 캐러셀
# ------------------------------------------------------------------
st.markdown('<div class="m-section-title">🛡️ 지진 발생 시 행동요령</div>', unsafe_allow_html=True)

def build_safety_card_html(step):
    html = []
    html.append('<div class="m-card">')
    html.append('<div class="m-card-head" style="background:#0B2545;">')
    html.append(f'<div class="m-card-head-top"><span class="m-badge">{step["key"].upper()}</span></div>')
    html.append(f'<div class="m-date">{step["title"]}</div>')
    html.append('</div>')
    html.append('<div class="m-card-body">')
    html.append('<div class="m-field-label">📝 행동 요령</div>')
    html.append(f'<div class="m-tip-box">{step["desc"]}</div>')
    html.append('</div>')
    html.append(f'<a class="m-detail-btn" href="{to_watch_url(step["video"])}" target="_blank">▶ 참고영상 보기</a>')
    html.append('</div>')
    return "".join(html)

safety_carousel_html = '<div class="m-carousel">' + "".join(
    build_safety_card_html(step) for step in SAFETY_STEPS
) + '</div>'
st.markdown(safety_carousel_html, unsafe_allow_html=True)

# ------------------------------------------------------------------
# 이력 통계
# ------------------------------------------------------------------
if not history_df.empty:
    years_sorted = sorted(history_df["year"].dropna().unique())
    start_y, end_y = years_sorted[0], years_sorted[-1]

    history_kr = history_df.copy()
    total_cnt = len(history_kr)
    max_row = history_kr.loc[history_kr["mt"].idxmax()]
    city_counts = history_kr["city"].value_counts()
    top_city = city_counts.index[0]
    top_city_cnt = city_counts.iloc[0]

    st.markdown(
        '<div class="m-section-title">📊 지진 발생 이력 누적 통계<br>'
        f'<span class="m-section-sub">({start_y}년 1월 ~ {end_y}년 9월 · 규모 2.0 이상)</span></div>',
        unsafe_allow_html=True
    )

    st.markdown(
        '<div class="m-stat-grid">'
        f'<div class="m-stat-card"><div class="m-stat-label">전체 건수</div>'
        f'<div class="m-stat-value" style="color:#1565C0;">{total_cnt:,}건</div></div>'
        f'<div class="m-stat-card"><div class="m-stat-label">역대 최대 규모</div>'
        f'<div class="m-stat-value" style="color:#C62828;">{max_row["mt"]}</div>'
        f'<div class="m-stat-sub">{fmt_date_wd(max_row["date_str"])}</div></div>'
        f'<div class="m-stat-card"><div class="m-stat-label">최다 발생 지역</div>'
        f'<div class="m-stat-value" style="color:#8E44AD; font-size:16px;">{top_city}</div>'
        f'<div class="m-stat-sub">{top_city_cnt:,}건</div></div>'
        '</div>',
        unsafe_allow_html=True
    )

    # ---- 연도별 발생건수 + 평균규모 추이 (다크 네이비 차트) ----
    yearly = history_kr.groupby("year").agg(cnt=("mt", "size"), avg_mag=("mt", "mean")).reset_index()
    max_cnt = int(yearly["cnt"].max()) if not yearly.empty else 1
    max_avg = float(yearly["avg_mag"].max()) if not yearly.empty else 1
    scale = (max_cnt * 0.85 / max_avg) if max_avg else 1
    line_y = (yearly["avg_mag"] * scale).tolist()

    fig_bar = go.Figure()
    fig_bar.add_trace(go.Bar(
        x=yearly["year"], y=yearly["cnt"], name="발생건수", marker_color="#1565C0",
        text=yearly["cnt"], textposition="outside",
        textfont=dict(size=11, family="Arial Black", color="#FFFFFF")
    ))
    fig_bar.add_trace(go.Scatter(
        x=yearly["year"], y=line_y, name="평균규모 추이", mode="lines+markers+text",
        line=dict(color="#FFD600", width=3), marker=dict(size=7, color="#FFD600"),
        text=[f"{v:.1f}" for v in yearly["avg_mag"]], textposition="top center",
        textfont=dict(size=11, family="Arial Black", color="#FFD600"), showlegend=True
    ))
    fig_bar.update_layout(
        font=dict(size=11, color="#FFFFFF"), paper_bgcolor="#0B2545", plot_bgcolor="#0B2545",
        xaxis=dict(type="category", tickfont=dict(size=11, color="#FFFFFF"),
                   gridcolor="rgba(255,255,255,0.12)"),
        yaxis=dict(tickfont=dict(size=10, color="#FFFFFF"), range=[0, max_cnt * 1.35],
                   gridcolor="rgba(255,255,255,0.12)"),
        legend=dict(font=dict(size=11, color="#FFFFFF"), orientation="h", x=0.5, xanchor="center", y=-0.18, yanchor="top"),
        height=300, margin=dict(t=20, b=10, l=10, r=10), dragmode=False
    )
    st.plotly_chart(fig_bar, use_container_width=True, config=CHART_CONFIG)

    # ---- TOP3 지역 순위 ----
    top3 = city_counts.head(3)
    max_val = int(top3.iloc[0]) if len(top3) > 0 else 1
    items_html = []
    bar_colors = ["#B3123B", "#E85D8A", "#F5B7C4"]
    for rank, (c_name, c_count) in enumerate(top3.items()):
        pct = int((c_count / max_val) * 100) if max_val else 0
        items_html.append(
            f'<div class="m-top-item">'
            f'<div class="m-top-item-head"><span>{rank + 1}위 · {c_name}</span>'
            f'<span>{int(c_count)}건</span></div>'
            f'<div class="m-top-bar-bg"><div class="m-top-bar-fill" style="width:{pct}%; background:{bar_colors[rank]};"></div></div>'
            f'</div>'
        )
    st.markdown(
        '<div class="m-top-wrap"><div class="m-top-title">🏆 지역별 발생 TOP3</div>' + "".join(items_html) + '</div>',
        unsafe_allow_html=True
    )

    # ---- 진도별 분포 파이차트 ----
    intensity_counts = history_kr.dropna(subset=["intensity"]).copy()
    intensity_counts["intensity"] = intensity_counts["intensity"].astype(int)
    pie_df = intensity_counts["intensity"].value_counts().reset_index()
    pie_df.columns = ["intensity", "cnt"]
    pie_df["label"] = pie_df["intensity"].apply(lambda g: f"진도 {g}")
    color_map = {f"진도 {g}": intensity_color(g) for g in pie_df["intensity"]}

    fig_pie = px.pie(pie_df, names="label", values="cnt", color="label",
                      color_discrete_map=color_map, hole=0.4)
    fig_pie.update_traces(textfont=dict(size=12), textinfo="percent", textposition="outside",
                           texttemplate="%{percent}")
    fig_pie.update_layout(
        font=dict(size=11),
        legend=dict(font=dict(size=11), orientation="h", x=0.5, xanchor="center", y=-0.1, yanchor="top"),
        height=340, margin=dict(t=10, b=10, l=10, r=10)
    )
    st.plotly_chart(fig_pie, use_container_width=True, config=CHART_CONFIG)

    # ---- 지역별 발생 빈도 지도 ----
    st.markdown('<div class="m-section-title">🎯 지역별 발생 빈도 지도</div>', unsafe_allow_html=True)
    province_counts = history_df["province"].value_counts().to_dict()
    legend_html = "".join(
        f'<span class="m-legend-chip" style="background:{c};">{label}</span>'
        for label, c in BIN_COLORS.items()
    )
    st.markdown(f'<div class="m-legend-row">{legend_html}</div>', unsafe_allow_html=True)

    with st.container(border=True):
        m_freq = folium.Map(location=[36.0, 127.7], tiles="OpenStreetMap",
                             zoom_control=False, scrollWheelZoom=False, dragging=False,
                             doubleClickZoom=False, touchZoom=False)
        fit_bounds_zoomed(m_freq, KOREA_BOUNDS)
        for _, row in history_df.iterrows():
            prov = row["province"]
            cnt = province_counts.get(prov, 0)
            label = bin_label(cnt)
            color = BIN_COLORS[label]
            popup_html = f"""
            <div style='font-size:13px; line-height:1.6;'>
            <b>📍 진원지 :</b> {row['loc_text']}<br>
            <b>강도(규모) :</b> {row['mt']}<br>
            <b>{prov} 누적 발생 :</b> {cnt}건 ({label})
            </div>
            """
            folium.CircleMarker(
                location=[row["lat"], row["lon"]], radius=3, color=color,
                fill=True, fill_color=color, fill_opacity=0.85,
                popup=folium.Popup(popup_html, max_width=240),
            ).add_to(m_freq)
        st_folium(m_freq, width=None, height=380, use_container_width=True, returned_objects=[])

    # ---- 지역별 발생 강도(진도) 지도 ----
    st.markdown('<div class="m-section-title">🟠 지역별 발생 강도(진도) 지도</div>', unsafe_allow_html=True)
    grades_present = sorted(history_df["intensity"].dropna().unique().astype(int).tolist())
    legend_html2 = "".join(
        f'<span class="m-legend-chip m-legend-chip-dark" style="background:{intensity_color(g)};">진도 {g}</span>'
        for g in grades_present
    )
    st.markdown(f'<div class="m-legend-row">{legend_html2}</div>', unsafe_allow_html=True)

    with st.container(border=True):
        m_intensity = folium.Map(location=[36.0, 127.7], tiles="OpenStreetMap",
                                  zoom_control=False, scrollWheelZoom=False, dragging=False,
                                  doubleClickZoom=False, touchZoom=False)
        fit_bounds_zoomed(m_intensity, KOREA_BOUNDS)
        for _, row in history_df.iterrows():
            grade = row["intensity"]
            color = intensity_color(grade)
            grade_disp = int(grade) if pd.notna(grade) else "-"
            popup_html = f"""
            <div style='font-size:13px; line-height:1.6;'>
            <b>📍 진원지 :</b> {row['loc_text']}<br>
            <b>강도(규모) :</b> {row['mt']}<br>
            <b>진도 :</b> {grade_disp}
            </div>
            """
            folium.CircleMarker(
                location=[row["lat"], row["lon"]], radius=3, color=color,
                fill=True, fill_color=color, fill_opacity=0.85,
                popup=folium.Popup(popup_html, max_width=240),
            ).add_to(m_intensity)
        st_folium(m_intensity, width=None, height=380, use_container_width=True, returned_objects=[])

    # ---------------- 내 지역 지진 발생기록 찾기 ----------------
    st.markdown('<div class="m-section-title">🔎 내 지역 지진 발생기록 찾기</div>', unsafe_allow_html=True)
    st.markdown(
        '<div style="font-size:13px; color:#5A6B85; margin-bottom:10px;">'
        '실제 관측 데이터를 기반으로 시·도와 시·군·구를 선택하면 해당 지역의 발생 이력을 '
        '날짜·규모·진도까지 모두 조회할 수 있습니다.</div>',
        unsafe_allow_html=True
    )

    with st.container(border=True):
        available_provinces = sorted([p for p in history_kr["province"].unique() if p != "기타"])

        st.markdown('<div class="m-select-label">① 시·도 선택</div>', unsafe_allow_html=True)
        sel_province = st.selectbox("시도선택", ["전체"] + available_provinces,
                                     key="my_region_province", label_visibility="collapsed")

        st.markdown('<div class="m-select-label">② 시·군·구 선택</div>', unsafe_allow_html=True)
        if sel_province == "전체":
            city_options = ["전체"] + sorted(history_kr["city"].unique().tolist())
        else:
            city_options = ["전체"] + sorted(
                history_kr[history_kr["province"] == sel_province]["city"].unique().tolist()
            )
        sel_city = st.selectbox("시군구선택", city_options, key="my_region_city", label_visibility="collapsed")

        result_df = history_kr.copy()
        if sel_province != "전체":
            result_df = result_df[result_df["province"] == sel_province]
        if sel_city != "전체":
            result_df = result_df[result_df["city"] == sel_city]
        result_df = result_df.sort_values("date_str", ascending=False)

        region_label = sel_city if sel_city != "전체" else (sel_province if sel_province != "전체" else "전국")

        if result_df.empty:
            st.markdown(f'<div class="m-empty-msg">선택하신 \'{region_label}\' 지역에서는 관측 이력이 없습니다.</div>', unsafe_allow_html=True)
        else:
            r_total = len(result_df)
            r_max = result_df.loc[result_df["mt"].idxmax()]
            r_latest = result_df.iloc[0]

            st.markdown(
                '<div class="m-stat-grid">'
                f'<div class="m-stat-card"><div class="m-stat-label">{region_label} 발생 건수</div>'
                f'<div class="m-stat-value" style="color:#1565C0;">{r_total:,}건</div></div>'
                f'<div class="m-stat-card"><div class="m-stat-label">최대 규모</div>'
                f'<div class="m-stat-value" style="color:#C62828;">{r_max["mt"]}</div>'
                f'<div class="m-stat-sub">{fmt_date_wd(r_max["date_str"])}</div></div>'
                f'<div class="m-stat-card"><div class="m-stat-label">최근 발생</div>'
                f'<div class="m-stat-value" style="color:#8E44AD; font-size:15px;">{fmt_date_wd(r_latest["date_str"])}</div>'
                f'<div class="m-stat-sub">규모 {r_latest["mt"]}</div></div>'
                '</div>',
                unsafe_allow_html=True
            )
            st.write("")

            rows_html = ['<div class="m-list-wrap">']
            for _, row in result_df.iterrows():
                grade = row["intensity"]
                stripe_color = intensity_color(grade)
                grade_disp = f"진도 {int(grade)}" if pd.notna(grade) else "진도 -"
                rows_html.append(
                    '<div class="m-list-item">'
                    f'<div class="m-list-stripe" style="background:{stripe_color};"></div>'
                    '<div class="m-list-main">'
                    '<div class="m-list-top">'
                    f'<span class="m-list-date">{fmt_date_wd(row["date_str"])}</span>'
                    f'<span class="m-list-type" style="background:{stripe_color};">{grade_disp}</span>'
                    '</div>'
                    f'<div class="m-list-loc">📍 {row["loc_text"]}</div>'
                    f'<div class="m-list-content">규모 {row["mt"]}</div>'
                    '</div>'
                    '</div>'
                )
            rows_html.append('</div>')
            st.markdown("".join(rows_html), unsafe_allow_html=True)

else:
    st.warning("⚠️ 이력 데이터를 불러오지 못했습니다. API 키 또는 네트워크 상태를 확인해주세요.")

# ------------------------------------------------------------------
# 하단 고정 새로고침 바
# ------------------------------------------------------------------
now_str = datetime.now().strftime("%m.%d %H:%M")
st.markdown(
    '<div class="m-bottom-bar">'
    f'<div class="m-bottom-info">📡 실시간 연동 · 마지막 확인 {now_str}</div>'
    '</div>',
    unsafe_allow_html=True
)
if st.button("🔄  새로고침", key="mobile_refresh", use_container_width=True):
    st.cache_data.clear()
    st.rerun()

