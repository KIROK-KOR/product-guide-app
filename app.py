import io
import re
import time
from datetime import datetime
from typing import List, Dict, Optional

import pandas as pd
import streamlit as st

# 선택 기능(카메라 인식) 의존성: 설치되지 않아도 앱은 구동되도록 처리
try:
    from pyzbar.pyzbar import decode as zbar_decode
    from PIL import Image
    PYZBAR_AVAILABLE = True
except Exception:
    PYZBAR_AVAILABLE = False

APP_TITLE = "제품 설명 가이드 앱"
REQUIRED_COLS = [
    "바코드", "SAP코드", "제품명", "입수",
    "출고가", "포함가(면세 시 제외)", "면세/과세 구분", "PLT 박스수"
]

# ---------------------
# 유틸: 문자열 정규화
# ---------------------
def normalize_barcode(x: object) -> str:
    """
    바코드를 비교 가능한 숫자문자열로 통일.
    - 숫자만 추출
    - 선행 0 보존 로직: 원본이 문자열이면 그대로 숫자만 유지, 숫자형이면 정수 변환 뒤 문자열
    """
    if pd.isna(x):
        return ""
    s = str(x).strip()
    # 하이픈/공백 제거 후 숫자만 남김
    s_digits = "".join(ch for ch in s if ch.isdigit())
    return s_digits

def normalize_name(x: object) -> str:
    if pd.isna(x):
        return ""
    return re.sub(r"\s+", " ", str(x).strip()).lower()

# ---------------------
# 데이터 적재 & 검증
# ---------------------
@st.cache_data(show_spinner=False)
def load_excel(file_bytes: bytes) -> pd.DataFrame:
    df = pd.read_excel(io.BytesIO(file_bytes), engine="openpyxl")
    # 컬럼 존재 검증
    missing = [c for c in REQUIRED_COLS if c not in df.columns]
    if missing:
        raise ValueError(f"엑셀에 필수 컬럼이 없습니다: {missing}\n"
                         f"필수 컬럼: {REQUIRED_COLS}")
    # 타입/정규화 보조 컬럼
    df["__바코드_norm__"] = df["바코드"].apply(normalize_barcode)
    df["__제품명_norm__"] = df["제품명"].apply(normalize_name)
    return df

def filter_by_barcode(df: pd.DataFrame, query: str) -> pd.DataFrame:
    q = normalize_barcode(query)
    if not q:
        return df.iloc[0:0]
    # 완전일치 우선, 없으면 부분일치
    exact = df[df["__바코드_norm__"] == q]
    if len(exact) > 0:
        return exact
    return df[df["__바코드_norm__"].str.contains(q, na=False)]

def filter_by_name(df: pd.DataFrame, query: str) -> pd.DataFrame:
    q = normalize_name(query)
    if not q:
        return df.iloc[0:0]
    # 부분일치 우선
    hit = df[df["__제품명_norm__"].str.contains(q, na=False)]
    return hit

def result_view(df_hit: pd.DataFrame):
    # 필수 컬럼만 노출
    view_cols = REQUIRED_COLS
    if len(df_hit) == 0:
        st.info("검색 결과가 없습니다. 입력값을 확인해주세요.")
        return

    if len(df_hit) == 1:
        row = df_hit.iloc[0].to_dict()
        with st.container(border=True):
            st.markdown(f"### {row['제품명']}")
            c1, c2, c3 = st.columns([1,1,1])
            with c1:
                st.metric("바코드", str(row["바코드"]))
                st.metric("SAP코드", str(row["SAP코드"]))
                st.metric("입수", str(row["입수"]))
            with c2:
                st.metric("출고가", f"{int(row['출고가']):,} 원")
                st.metric("포함가(면세 시 제외)", f"{int(row['포함가(면세 시 제외)']):,} 원")
                st.metric("면세/과세 구분", str(row["면세/과세 구분"]))
            with c3:
                st.metric("PLT 박스수", str(row["PLT 박스수"]))
    else:
        st.caption(f"총 {len(df_hit)}건이 검색되었습니다.")
        st.dataframe(df_hit[view_cols].reset_index(drop=True), use_container_width=True)

def push_history(query_type: str, query_value: str, df_hit: pd.DataFrame):
    if "history" not in st.session_state:
        st.session_state["history"] = []
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    item = {
        "시간": stamp,
        "검색유형": query_type,
        "입력값": query_value,
        "결과건수": int(len(df_hit)),
        "대표제품": (df_hit.iloc[0]["제품명"] if len(df_hit) > 0 else "")
    }
    st.session_state["history"].append(item)

def show_history():
    st.subheader("조회 이력")
    hist = st.session_state.get("history", [])
    if not hist:
        st.caption("아직 조회 이력이 없습니다.")
        return
    st.dataframe(pd.DataFrame(hist), use_container_width=True)
    if st.button("이력 초기화", type="secondary"):
        st.session_state["history"] = []
        st.rerun()

def template_download_button():
    # 런타임에서 샘플 템플릿 생성
    sample = pd.DataFrame([
        {
            "바코드": "0881234567890",
            "SAP코드": "SAP100001",
            "제품명": "오뚜기 진라면 매운맛 120g",
            "입수": 40, "출고가": 42000, "포함가(면세 시 제외)": 46200,
            "면세/과세 구분": "과세", "PLT 박스수": 48
        }
    ])
    bio = io.BytesIO()
    with pd.ExcelWriter(bio, engine="openpyxl") as w:
        sample.to_excel(w, index=False, sheet_name="제품정보")
    st.download_button(
        "샘플 템플릿(.xlsx) 다운로드",
        data=bio.getvalue(),
        file_name="products_template_min.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        help="필수 컬럼 형식을 참고하세요.",
        type="secondary",
        use_container_width=True
    )

def camera_barcode_reader() -> Optional[str]:
    """
    선택 기능: 카메라로 바코드 촬영 → pyzbar로 해석.
    pyzbar 미설치 시 None 반환 + 안내.
    """
    if not PYZBAR_AVAILABLE:
        st.warning("카메라 인식 기능은 선택 기능입니다. 사용하려면 'pyzbar'를 설치하세요.\n\n"
                   "설치(Windows):\n"
                   "1) 관리자 PowerShell로 `choco install zbar`(Chocolatey 필요)\n"
                   "2) `pip install pyzbar`\n"
                   "※ 미설치여도 본 앱의 검색 기능은 정상 동작합니다.")
        return None

    st.caption("스마트폰으로 접속한 경우에도 브라우저 카메라 접근 허용 후 촬영하세요.")
    img = st.camera_input("바코드가 잘 보이도록 촬영 후 [찍기]를 눌러주세요.")
    if img is None:
        return None

    # 이미지 → 바코드 디코드
    bytes_data = img.getvalue()
    pil = Image.open(io.BytesIO(bytes_data))
    results = zbar_decode(pil)
    candidates = [r.data.decode("utf-8") for r in results]
    if not candidates:
        st.info("바코드를 인식하지 못했습니다. 각도를 바꾸거나 초점을 맞춰 다시 시도해주세요.")
        return None

    # 숫자만 추출(하이픈/공백 제거)
    decoded = normalize_barcode(candidates[0])
    st.success(f"인식된 바코드: {decoded}")
    return decoded

# ======================
# 앱 시작
# ======================
st.set_page_config(page_title=APP_TITLE, layout="wide")


# === Mobile-only UI tweaks injected by assistant ===
CUSTOM_CSS = """
<style>
/* Desktop base */
.block-container {max-width: 1200px !important; padding-top: 1rem;}
footer {visibility: hidden;}
.stButton>button, .stDownloadButton>button {height: 44px; border-radius: 12px;}
[data-testid="stTextInput"] input {height: 44px; border-radius: 10px;}

/* Mobile tweaks (<= 640px) */
@media (max-width: 640px) {
  .block-container { padding-left: .75rem; padding-right: .75rem; }
  .stButton>button, .stDownloadButton>button { height: 48px; font-size: 1rem; }
  [data-testid="stTextInput"] input { height: 48px; font-size: 1rem; }
  [data-baseweb="radio"] label { font-size: .95rem; }
  .stDataFrame [role="table"] { font-size: .9rem; }
}
</style>
"""
st.markdown(CUSTOM_CSS, unsafe_allow_html=True)
# === End of mobile tweaks ===
st.title(APP_TITLE)
st.caption("엑셀 데이터만을 신뢰소스로 활용하여 제품 정보를 조회합니다.")

with st.sidebar:
    st.header("1) 엑셀 업로드")
    file = st.file_uploader(
        "제품정보 엑셀 업로드 (.xlsx)",
        type=["xlsx", "xlsm"],
        accept_multiple_files=False,
        help="드래그앤드롭 또는 클릭하여 선택",
    )
    template_download_button()

    if file:
        try:
            df = load_excel(file.getvalue())
            st.session_state["df"] = df
            st.success(f"업로드 완료: {file.name} · 행 {len(df)}건")
            st.caption("필수 컬럼: " + ", ".join(REQUIRED_COLS))
        except Exception as e:
            st.error(f"엑셀 읽기 오류: {e}")
    else:
        st.info("엑셀을 업로드하면 검색이 가능합니다.")
        st.session_state["df"] = None

st.divider()

# 탭: 검색 / 이력 / (선택) 카메라 바코드
tab_search, tab_history, tab_camera = st.tabs(["🔍 검색", "🕘 조회 이력", "📷 카메라 바코드(선택)"])

with tab_search:
    st.subheader("2) 검색 입력")
    colA, colB = st.columns([1,3])
    with colA:
        mode = st.radio("검색 기준", ["바코드", "제품명"], horizontal=True)
    with colB:
        placeholder = "숫자/하이픈 허용" if mode == "바코드" else "제품명 2자 이상"
        query = st.text_input("검색어", "", placeholder=placeholder)

    c1, c2, c3 = st.columns([1,1,6])
    with c1:
        do_search = st.button("검색", type="primary", use_container_width=True)
    with c2:
        do_reset = st.button("초기화", type="secondary", use_container_width=True)

    if do_reset:
        st.session_state.pop("last_result", None)
        st.rerun()

    df = st.session_state.get("df")
    if do_search:
        if df is None:
            st.warning("엑셀을 먼저 업로드해주세요.")
        else:
            if mode == "바코드":
                if not re.fullmatch(r"[0-9\-\s]+", query or ""):
                    st.error("바코드는 숫자/하이픈만 입력 가능합니다.")
                else:
                    hit = filter_by_barcode(df, query)
                    push_history("바코드", query, hit)
                    st.session_state["last_result"] = hit
            else:
                if not query or len(query.strip()) < 2:
                    st.error("제품명은 2자 이상 입력해주세요.")
                else:
                    hit = filter_by_name(df, query)
                    push_history("제품명", query, hit)
                    st.session_state["last_result"] = hit

    # 결과 표시
    hit_df = st.session_state.get("last_result", pd.DataFrame(columns=REQUIRED_COLS))
    st.subheader("3) 검색 결과")
    result_view(hit_df)

with tab_history:
    show_history()

with tab_camera:
    st.subheader("카메라로 바코드 인식 (선택 기능)")
    decoded = camera_barcode_reader()
    if decoded and st.session_state.get("df") is not None:
        st.info("인식된 바코드로 즉시 검색합니다.")
        hit = filter_by_barcode(st.session_state["df"], decoded)
        push_history("바코드(카메라)", decoded, hit)
        result_view(hit)