# -*- coding: utf-8 -*-
import io
import re
import time
from datetime import datetime
from typing import List, Dict, Optional

import base64
import pandas as pd
import streamlit as st

# -----------------------------
# 선택 의존성 (설치 안되어도 앱이 죽지 않게)
# -----------------------------
try:
    from PIL import Image
except Exception:
    Image = None

try:
    from pyzbar.pyzbar import decode as zbar_decode
    PYZBAR_AVAILABLE = True
except Exception:
    PYZBAR_AVAILABLE = False

# [추가] 실시간(WebRTC)용 선택 의존성
try:
    import cv2
    import av
    import numpy as np
    from streamlit_webrtc import webrtc_streamer, VideoTransformerBase
    WEBRTC_AVAILABLE = True
except Exception:
    WEBRTC_AVAILABLE = False

# -----------------------------
# 앱 기본 설정
# -----------------------------
st.set_page_config(page_title="제품 설명 가이드", layout="wide")

REQUIRED_COLS = ["바코드", "SAP코드", "제품명", "입수", "출고가", "포함가(면세 시 제외)", "면세/과세 구분", "PLT 박스수"]

def normalize_barcode(x: str) -> str:
    if not isinstance(x, str):
        x = str(x) if x is not None else ""
    return re.sub(r"[^0-9]", "", x).strip()

def normalize_name(x: str) -> str:
    if not isinstance(x, str):
        x = str(x) if x is not None else ""
    return re.sub(r"\s+", "", x).strip().lower()

def prepare_df(df: pd.DataFrame) -> pd.DataFrame:
    # 필요한 컬럼 없으면 최대한 맞춰줌(없는 건 빈값)
    for c in REQUIRED_COLS:
        if c not in df.columns:
            df[c] = ""
    # 검색용 정규화 컬럼
    df["__바코드_norm__"] = df["바코드"].astype(str).map(normalize_barcode)
    df["__제품명_norm__"] = df["제품명"].astype(str).map(normalize_name)
    return df[REQUIRED_COLS + ["__바코드_norm__", "__제품명_norm__"]]

def filter_by_barcode(df: pd.DataFrame, query: str) -> pd.DataFrame:
    q = normalize_barcode(query)
    if not q:
        return df.iloc[0:0]
    exact = df[df["__바코드_norm__"] == q]
    if len(exact) > 0:
        return exact
    return df[df["__바코드_norm__"].str.contains(q, na=False)]

def filter_by_name(df: pd.DataFrame, query: str) -> pd.DataFrame:
    q = normalize_name(query)
    if not q:
        return df.iloc[0:0]
    # 부분일치
    return df[df["__제품명_norm__"].str.contains(q, na=False)]

def result_view(df: pd.DataFrame):
    if df is None or len(df) == 0:
        st.info("검색 결과가 없습니다.")
        return
    # 카드 느낌의 상단 1건
    top = df.iloc[0]
    st.markdown(
        f"""
        **제품명**: {top['제품명']}  
        **바코드**: {top['바코드']}  |  **SAP코드**: {top['SAP코드']}  
        **입수**: {top['입수']}  |  **출고가**: {top['출고가']}  |  **포함가(면세 시 제외)**: {top['포함가(면세 시 제외)']}  
        **면세/과세**: {top['면세/과세 구분']}  |  **PLT 박스수**: {top['PLT 박스수']}
        """.strip()
    )
    with st.expander("표로 보기", expanded=False):
        st.dataframe(df[REQUIRED_COLS], use_container_width=True)

# -----------------------------
# 히스토리 관리
# -----------------------------
if "history" not in st.session_state:
    st.session_state["history"] = []
if "df" not in st.session_state:
    st.session_state["df"] = None
if "last_result" not in st.session_state:
    st.session_state["last_result"] = None

def push_history(kind: str, query: str, hit_df: pd.DataFrame):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    st.session_state["history"].insert(0, {"시각": ts, "종류": kind, "검색어": query, "건수": len(hit_df or [])})
    st.session_state["last_result"] = hit_df.copy() if hit_df is not None else None

def show_history():
    if len(st.session_state["history"]) == 0:
        st.info("검색 기록이 없습니다.")
        return
    st.dataframe(pd.DataFrame(st.session_state["history"]), use_container_width=True)

# -----------------------------
# 파일 업로드/로드
# -----------------------------
st.sidebar.header("데이터 업로드")
up = st.sidebar.file_uploader("EXCEL 파일 업로드 (.xlsx)", type=["xlsx"], accept_multiple_files=False)
if up is not None:
    try:
        df = pd.read_excel(up)
        st.session_state["df"] = prepare_df(df)
        st.sidebar.success(f"업로드 완료: {len(st.session_state['df'])}개 제품")
    except Exception as e:
        st.sidebar.error(f"엑셀 읽기 실패: {e}")

if st.session_state["df"] is None:
    st.warning("먼저 좌측에서 EXCEL 파일을 업로드하세요. (필수 컬럼: " + ", ".join(REQUIRED_COLS) + ")")

# -----------------------------
# 페이지 본문 탭
# -----------------------------
tab_search, tab_history, tab_camera = st.tabs(["🔎 검색", "🕘 히스토리", "📷 카메라 스캔(사진)"])

with tab_search:
    st.subheader("1) 검색")
    mode = st.radio("검색 기준", ["바코드", "제품명"], horizontal=True)
    query = st.text_input("검색어 입력", placeholder="바코드(숫자/하이픈) 또는 제품명(2자 이상)")
    colA, colB = st.columns([1, 1])
    do = colA.button("검색", type="primary")
    reset = colB.button("초기화")

    if reset:
        query = ""
        st.experimental_rerun()

    hit_df = None
    if do and st.session_state.get("df") is not None:
        if mode == "바코드":
            hit_df = filter_by_barcode(st.session_state["df"], query)
            push_history("바코드", query, hit_df)
        else:
            hit_df = filter_by_name(st.session_state["df"], query)
            push_history("제품명", query, hit_df)

    st.subheader("2) 결과")
    if hit_df is not None:
        result_view(hit_df)
    else:
        hit_df2 = st.session_state.get("last_result", pd.DataFrame(columns=REQUIRED_COLS))
        result_view(hit_df2)

with tab_history:
    show_history()

with tab_camera:
    st.subheader("카메라로 바코드 인식 (사진 캡처)")
    if not PYZBAR_AVAILABLE or Image is None:
        st.warning(
            "선택 기능입니다. 사진 캡처 인식을 사용하려면:\n"
            "- pip install pyzbar Pillow\n"
            "- (Windows는 보통 추가 설치 불필요, 드물게 zbar DLL 필요)\n"
            "※ 미설치여도 본 앱의 검색 기능은 정상 동작합니다."
        )
    else:
        img_file = st.camera_input("바코드가 잘 보이도록 촬영 후 [찍기]를 눌러주세요.")
        if img_file is not None:
            pil = Image.open(img_file)
            results = zbar_decode(pil)
            if not results:
                st.info("바코드를 인식하지 못했습니다. 각도/거리/초점을 바꿔 다시 시도해보세요.")
            else:
                # 여러 후보 중 숫자만 추출 후 가장 긴 것
                cands = []
                for r in results:
                    val = "".join(ch for ch in r.data.decode("utf-8", errors="ignore") if ch.isdigit())
                    if val:
                        cands.append(val)
                if cands:
                    cands.sort(key=len, reverse=True)
                    decoded = cands[0]
                    st.success(f"인식된 바코드: **{decoded}**")
                    if st.session_state.get("df") is not None:
                        hit = filter_by_barcode(st.session_state["df"], decoded)
                        push_history("바코드(카메라)", decoded, hit)
                        result_view(hit)

# ============================================================
# [추가] 실시간(WebRTC) 스캔 탭
# ============================================================
st.markdown("---")
st.subheader("⚡ 실시간 바코드 스캔 (베타)")

if not WEBRTC_AVAILABLE:
    st.warning(
        "실시간 스캔은 선택 기능입니다.\n\n"
        "아래 패키지를 설치한 뒤 다시 실행하세요:\n"
        "    pip install streamlit-webrtc opencv-python-headless av numpy\n"
        "또는 opencv-python(전체판)을 사용해도 됩니다.\n\n"
        "iOS Safari는 HTTPS(또는 localhost)에서만 카메라 허용됩니다."
    )
else:
    class BarcodeTransformer(VideoTransformerBase):
        def __init__(self):
            self.last_texts: List[str] = []

        def transform(self, frame: "av.VideoFrame"):
            img = frame.to_ndarray(format="bgr24")
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

            # 성능을 위한 다운스케일
            h, w = gray.shape[:2]
            max_side = max(h, w)
            scale = 720 / max_side if max_side > 720 else 1.0
            if scale < 1.0:
                small = cv2.resize(gray, (int(w * scale), int(h * scale)))
            else:
                small = gray

            decoded_texts = []
            if PYZBAR_AVAILABLE and Image is not None:
                pil = Image.fromarray(small)
                results = zbar_decode(pil)
                for r in results:
                    x, y, ww, hh = r.rect
                    if scale < 1.0:
                        x, y, ww, hh = int(x / scale), int(y / scale), int(ww / scale), int(hh / scale)
                    cv2.rectangle(img, (x, y), (x + ww, y + hh), (0, 255, 0), 2)
                    txt = r.data.decode("utf-8", errors="ignore")
                    decoded_texts.append(txt)
                    cv2.putText(img, txt, (x, max(0, y - 10)), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)

            if decoded_texts:
                for t in decoded_texts:
                    if t not in self.last_texts:
                        self.last_texts.insert(0, t)
                self.last_texts = self.last_texts[:5]

            cv2.putText(img, "Align barcode in view. Lighting matters.",
                        (10, img.shape[0] - 12), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1)
            return img

    ctx = webrtc_streamer(
        key="barcode-live",
        video_transformer_factory=BarcodeTransformer,
        media_stream_constraints={"video": True, "audio": False},
        async_processing=True,
    )

    if ctx and ctx.video_transformer:
        latest = ctx.video_transformer.last_texts[:3]
        if latest:
            st.success("실시간 인식(최신순): " + " | ".join(f"**{t}**" for t in latest))
            if st.session_state.get("df") is not None:
                # 가장 최신값으로 즉시 조회
                hit = filter_by_barcode(st.session_state["df"], latest[0])
                push_history("바코드(실시간)", latest[0], hit)
                result_view(hit)
        else:
            st.info("바코드가 감지되면 여기에 표시됩니다.")
