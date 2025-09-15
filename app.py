# app.py (UI 개선판)
import re
from io import BytesIO
from datetime import datetime
import pandas as pd
import streamlit as st

# -----------------------------
# Page Config & Global Styles
# -----------------------------
st.set_page_config(
    page_title="제품 검색기 (개선 UI)",
    page_icon="🛒",
    layout="wide",
    initial_sidebar_state="expanded",
)

CUSTOM_CSS = """
<style>
/* Wide content & clean look */
.block-container {max-width: 1200px !important; padding-top: 1rem;}
/* Hide default footer */
footer {visibility: hidden;}
/* Title styling */
.app-title {font-size: 1.9rem; font-weight: 800; letter-spacing: -0.02em;}
.app-sub {color: var(--secondary-text, #6b7280); margin-top: .25rem;}
/* Card */
.card {border: 1px solid rgba(0,0,0,.06); border-radius: 16px; padding: 1rem 1.25rem; background: rgba(255,255,255,.6); box-shadow: 0 4px 16px rgba(0,0,0,.06);}
.card h3 {margin: 0 0 .75rem 0;}
/* Pills for filters */
.pills {display:flex; flex-wrap:wrap; gap:.5rem; margin:.25rem 0 0;}
.pill {padding: .2rem .6rem; border-radius: 999px; background: rgba(59,130,246,.12); border:1px solid rgba(59,130,246,.2); font-size:.85rem;}
/* Muted label row */
.muted {color:#6b7280; font-size:.9rem;}
/* Sticky toolbar */
.toolbar {position: sticky; top: 0; z-index: 100; background: var(--background-color, #fff); padding: .75rem 0 .5rem; border-bottom: 1px solid rgba(0,0,0,.06); backdrop-filter: blur(6px);}
/* Dataframe caption */
.caption {color:#6b7280; font-size:.85rem; margin:.25rem 0;}
/* Sidebar tweaks */
[data-testid="stSidebar"] .block-container {padding-top: 1rem;}
</style>
"""
st.markdown(CUSTOM_CSS, unsafe_allow_html=True)

# -----------------------------
# Utilities
# -----------------------------
REQUIRED_COLS = ["바코드", "제품명", "입수", "출고가"]
OPTIONAL_COLS = ["소비기한", "보관조건", "SAP코드"]

SYNONYMS = {
    "barcode": "바코드",
    "bar_code": "바코드",
    "바_코드": "바코드",
    "code": "바코드",
    "상품명": "제품명",
    "품명": "제품명",
    "product_name": "제품명",
    "sap": "SAP코드",
    "sap코드": "SAP코드",
    "sap_code": "SAP코드",
    "입수량": "입수",
    "입수(개)": "입수",
    "출고가(원)": "출고가",
    "가격": "출고가",
    "단가": "출고가",
    "유통기한": "소비기한",
    "소비_기한": "소비기한",
    "보관": "보관조건",
    "보관 조건": "보관조건",
}

def clean_colname(name: str) -> str:
    return re.sub(r"\s+", "", str(name)).strip().lower()

def normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    renamed = {}
    for c in df.columns:
        key = clean_colname(c)
        if key in SYNONYMS:
            renamed[c] = SYNONYMS[key]
        else:
            pretty = re.sub(r"\s+", "", str(c)).strip()
            if pretty in REQUIRED_COLS + OPTIONAL_COLS:
                renamed[c] = pretty
    df = df.rename(columns=renamed)

    for col in REQUIRED_COLS:
        if col not in df.columns:
            df[col] = None

    # 숫자 컬럼 정리
    for col in ["입수", "출고가"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    # 바코드 정규화 열
    def digits_only(x):
        s = "" if pd.isna(x) else str(x)
        return re.sub(r"\D+", "", s)
    df["정규화_바코드"] = df["바코드"].apply(digits_only)

    return df

@st.cache_data(show_spinner=False)
def load_data(file) -> pd.DataFrame:
    if file is None:
        sample = pd.DataFrame({
            "바코드": ["8801234567890","8809876543210","8801122334455"],
            "제품명": ["진라면(순한맛) 120g","참치마요컵밥 250g","케찹 500g"],
            "입수":   [40,12,20],
            "출고가": [450,1450,2200],
            "소비기한": ["2026-12-31","2025-08-15","2026-01-31"],
            "보관조건": ["실온","실온","실온"]
        })
        return normalize_columns(sample)

    name = file.name.lower()
    try:
        if name.endswith(".csv"):
            df = pd.read_csv(file)
        elif name.endswith(".xls") or name.endswith(".xlsx"):
            df = pd.read_excel(file)
        else:
            st.warning("지원하지 않는 파일 형식입니다. CSV 또는 Excel(.xlsx)을 업로드하세요.")
            return pd.DataFrame(columns=REQUIRED_COLS)
    except Exception as e:
        st.error(f"파일 로드 중 오류: {e}")
        return pd.DataFrame(columns=REQUIRED_COLS)

    return normalize_columns(df)

def validate_input(text: str, mode: str) -> str | None:
    if mode == "바코드":
        if not text:
            return "바코드를 입력하세요."
        if not re.fullmatch(r"[0-9\-\s]+", text):
            return "바코드는 숫자/하이픈/공백만 허용됩니다."
    else:
        if not text or len(text.strip()) < 2:
            return "제품명은 2자 이상 입력하세요."
    return None

def apply_filters(df: pd.DataFrame, storage_options, price_range, qty_range):
    out = df.copy()
    if storage_options and "보관조건" in out.columns:
        out = out[out["보관조건"].astype(str).isin(storage_options)]
    # 가격
    pmin, pmax = price_range
    if "출고가" in out.columns:
        out = out[(out["출고가"].fillna(0) >= pmin) & (out["출고가"].fillna(0) <= pmax)]
    # 입수
    qmin, qmax = qty_range
    if "입수" in out.columns:
        out = out[(out["입수"].fillna(0) >= qmin) & (out["입수"].fillna(0) <= qmax)]
    return out

def search(df: pd.DataFrame, text: str, mode: str) -> pd.DataFrame:
    if mode == "바코드":
        target = re.sub(r"\D+", "", text)
        return df[df["정규화_바코드"] == target]
    else:
        pat = re.escape(text.strip())
        return df[df["제품명"].astype(str).str.contains(pat, case=False, na=False)]

def sort_df(df: pd.DataFrame, sort_key: str):
    mapping = {
        "출고가 ↑": ("출고가", True),
        "출고가 ↓": ("출고가", False),
        "제품명 A→Z": ("제품명", True),
        "입수 ↑": ("입수", True),
        "입수 ↓": ("입수", False),
    }
    if sort_key in mapping:
        col, asc = mapping[sort_key]
        if col in df.columns:
            return df.sort_values(col, ascending=asc, kind="mergesort")
    return df

def format_display(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    if "출고가" in out.columns:
        out["출고가"] = out["출고가"].apply(lambda x: f"{int(x):,}" if pd.notna(x) else "")
    if "입수" in out.columns:
        out["입수"] = out["입수"].apply(lambda x: f"{int(x):,}" if pd.notna(x) else "")
    return out

def result_card(row: pd.Series):
    st.markdown('<div class="card">', unsafe_allow_html=True)
    st.markdown(f"### 🧾 {str(row.get('제품명',''))}")
    c1, c2, c3, c4, c5, c6 = st.columns([2,2,1,1,1,1])
    c1.metric("바코드", str(row.get("바코드","")))
    c2.metric("SAP코드", str(row.get("SAP코드","")) if "SAP코드" in row else "")
    c3.metric("입수", f"{int(row.get('입수')):,}" if pd.notna(row.get("입수")) else "")
    c4.metric("출고가", f"{int(row.get('출고가')):,}" if pd.notna(row.get("출고가")) else "")
    c5.metric("소비기한", str(row.get("소비기한","")))
    c6.metric("보관조건", str(row.get("보관조건","")))
    st.markdown("</div>", unsafe_allow_html=True)

def make_download(df: pd.DataFrame, filename_prefix: str = "검색결과"):
    basic_cols = [c for c in ["바코드","제품명","입수","출고가","소비기한","보관조건","SAP코드"] if c in df.columns]
    out = df[basic_cols].copy()

    csv_bytes = out.to_csv(index=False).encode("utf-8-sig")
    st.download_button(
        "CSV 다운로드", data=csv_bytes, file_name=f"{filename_prefix}.csv", mime="text/csv", use_container_width=True
    )

    try:
        bio = BytesIO()
        with pd.ExcelWriter(bio, engine="openpyxl") as xw:
            out.to_excel(xw, index=False, sheet_name="결과")
        st.download_button(
            "Excel 다운로드", data=bio.getvalue(), file_name=f"{filename_prefix}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", use_container_width=True
        )
    except Exception:
        st.caption("※ openpyxl 미설치 등으로 Excel 저장을 건너뛰었습니다. CSV를 사용하세요.")

def record_history(item: dict):
    hist = st.session_state.get("history", [])
    hist.insert(0, item)
    st.session_state["history"] = hist[:20]  # 최근 20개 유지

def history_buttons():
    hist = st.session_state.get("history", [])
    if not hist:
        st.info("검색 히스토리가 비어 있습니다.")
        return None
    for i, h in enumerate(hist):
        cols = st.columns([4,2,2,1])
        cols[0].markdown(f"**{h['query']}**  <span class='muted'>({h['mode']}, {h['time']})</span>", unsafe_allow_html=True)
        cols[1].write(f"결과: **{h['count']}건**")
        if cols[2].button("다시 검색", key=f"rehit_{i}"):
            st.session_state["mode"] = h["mode"]
            st.session_state["query"] = h["query"]
            st.session_state["rehit"] = True
        cols[3].write("")

# -----------------------------
# Sidebar: Upload & Summary
# -----------------------------
with st.sidebar:
    st.header("📦 데이터 업로드")
    file = st.file_uploader("CSV 또는 Excel(.xlsx) 파일 선택", type=["csv","xls","xlsx"])
    st.caption("컬럼 예: 바코드, 제품명, 입수, 출고가, (선택) 소비기한, 보관조건, SAP코드")

    st.markdown("---")
    st.subheader("📊 데이터 요약")

# -----------------------------
# Main: Title
# -----------------------------
st.markdown('<div class="app-title">🛒 제품 검색기</div>', unsafe_allow_html=True)
st.markdown('<div class="app-sub">엑셀/CSV 업로드 후 바코드 또는 제품명으로 빠르게 검색하세요. (파일이 없으면 샘플 데이터 사용)</div>', unsafe_allow_html=True)

df = load_data(file)

# Sidebar summary after data load
with st.sidebar:
    if not df.empty:
        total = len(df)
        uniq_bar = df["정규화_바코드"].nunique() if "정규화_바코드" in df.columns else ""
        min_p = int(df["출고가"].min()) if "출고가" in df.columns and pd.notna(df["출고가"]).any() else 0
        max_p = int(df["출고가"].max()) if "출고가" in df.columns and pd.notna(df["출고가"]).any() else 0
        st.metric("총 제품 수", f"{total:,}")
        st.metric("고유 바코드", f"{uniq_bar:,}")
        st.metric("출고가 범위", f"{min_p:,} ~ {max_p:,}")
    else:
        st.caption("샘플 데이터가 사용됩니다.")

# -----------------------------
# Tabs
# -----------------------------
tab1, tab2, tab3 = st.tabs(["🔎 검색", "🕘 히스토리", "📄 데이터 미리보기"])

with tab3:
    if df.empty:
        st.warning("데이터가 없습니다.")
    else:
        st.dataframe(df.drop(columns=[c for c in ["정규화_바코드"] if c in df.columns]), use_container_width=True, height=360)
        st.caption("원본 칼럼은 자동 정규화되어 검색에 활용됩니다.")

with tab2:
    history_buttons()

with tab1:
    # -----------------------------
    # Search Toolbar (sticky)
    # -----------------------------
    st.markdown('<div class="toolbar">', unsafe_allow_html=True)
    colA, colB = st.columns([1,3])
    with colA:
        st.session_state.setdefault("mode", "바코드")
        mode = st.radio("검색 기준", ["바코드","제품명"], horizontal=True, key="mode")
    with colB:
        placeholder = "숫자/하이픈만 입력" if mode == "바코드" else "제품명 2자 이상 입력"
        st.session_state.setdefault("query", "")
        query = st.text_input("검색어", value=st.session_state["query"], placeholder=placeholder, label_visibility="visible", key="query")
    st.markdown('</div>', unsafe_allow_html=True)

    # -----------------------------
    # Advanced Filters
    # -----------------------------
    with st.expander("고급 필터 • 정렬", expanded=False):
        storage_vals = sorted([v for v in df["보관조건"].dropna().unique().tolist()]) if "보관조건" in df.columns else []
        storage_sel = st.multiselect("보관조건", options=storage_vals, placeholder="보관조건 선택", help="예: 실온 / 냉장 / 냉동", key="flt_storage")

        if "출고가" in df.columns and pd.notna(df["출고가"]).any():
            pmin = int(df["출고가"].min())
            pmax = int(df["출고가"].max())
        else:
            pmin, pmax = 0, 0
        price_range = st.slider("출고가 범위", min_value=pmin, max_value=pmax if pmax>=pmin else pmin+0, value=(pmin, pmax), disabled=(pmax==pmin==0), key="flt_price")

        if "입수" in df.columns and pd.notna(df["입수"]).any():
            qmin = int(df["입수"].min())
            qmax = int(df["입수"].max())
        else:
            qmin, qmax = 0, 0
        qty_range = st.slider("입수 범위", min_value=qmin, max_value=qmax if qmax>=qmin else qmin+0, value=(qmin, qmax), disabled=(qmax==qmin==0), key="flt_qty")

        sort_key = st.selectbox("정렬", ["출고가 ↓","출고가 ↑","제품명 A→Z","입수 ↓","입수 ↑"], index=0, key="sort_key")

        pills = []
        if storage_sel: pills.append(f"보관조건: {', '.join(storage_sel)}")
        if price_range and price_range[0] != price_range[1]: pills.append(f"출고가 {price_range[0]:,}~{price_range[1]:,}")
        if qty_range and qty_range[0] != qty_range[1]: pills.append(f"입수 {qty_range[0]:,}~{qty_range[1]:,}")
        if pills:
            st.markdown('<div class="pills">' + "".join([f'<span class="pill">{p}</span>' for p in pills]) + "</div>", unsafe_allow_html=True)

    # -----------------------------
    # Actions
    # -----------------------------
    colX, colY, colZ = st.columns([1,1,6])
    do_search = colX.button("검색", type="primary")
    do_reset = colY.button("초기화")

    if do_reset:
        st.session_state["query"] = ""
        st.session_state["rehit"] = False
        st.toast("입력값을 초기화했습니다.", icon="🧹")
        st.experimental_rerun()

    rehit = st.session_state.pop("rehit", False)

    # -----------------------------
    # Execute Search
    # -----------------------------
    if (do_search or rehit) and not df.empty:
        error = validate_input(st.session_state["query"], st.session_state["mode"])
        if error:
            st.error(error)
        else:
            base = df
            base = apply_filters(base, st.session_state.get("flt_storage", []), st.session_state.get("flt_price", (0,0)), st.session_state.get("flt_qty", (0,0)))
            hits = search(base, st.session_state["query"], st.session_state["mode"])
            hits = sort_df(hits, st.session_state.get("sort_key", "출고가 ↓"))
            count = len(hits)

            record_history({
                "time": datetime.now().strftime("%H:%M"),
                "mode": st.session_state["mode"],
                "query": st.session_state["query"],
                "count": count,
            })

            st.subheader(f"검색결과: {count}건")
            if count == 0:
                st.info("일치하는 결과가 없습니다. 필터를 조정하거나 다른 키워드를 시도해 보세요.")
            elif count == 1:
                st.success("단일 결과를 찾았습니다.")
                result_card(hits.iloc[0])
                make_download(hits, filename_prefix="검색결과_단건")
            else:
                display_cols = [c for c in ["바코드","제품명","입수","출고가","소비기한","보관조건","SAP코드"] if c in hits.columns]
                st.dataframe(format_display(hits[display_cols]), use_container_width=True, height=420)
                make_download(hits, filename_prefix=f"검색결과_{count}건")

            st.toast("검색이 완료되었습니다.", icon="🔎")

st.caption("ⓘ 팁: 'streamlit run app.py' 또는 'python -m streamlit run app.py' 로 실행하세요.  •  Esc → Command Palette  •  ? → Keyboard Shortcuts")
