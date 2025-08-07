import streamlit as st
import sys
import os
import datetime
from fpdf import FPDF
from fpdf.enums import Align
import io
from async_report_generator import load_reports_from_db
import asyncio

# 현재 파일의 부모 디렉토리 (프로젝트 루트)를 sys.path에 추가
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

st.set_page_config(page_title="[4] 미래 모습 보고서", layout="wide")

# 세션 상태 초기화
if 'username' not in st.session_state:
    st.session_state.username = ""
if 'report_query_for_display' not in st.session_state:
    st.session_state.report_query_for_display = ""

st.title("🚀 미래 모습 보고서")

# 사이드바에서 사용자 이름과 기업명 입력 받기
with st.sidebar:
    st.header("🔍 보고서 조회 설정")
    st.session_state.username = st.text_input("사용자 이름", value=st.session_state.username)
    st.session_state.report_query_for_display = st.text_input("기업명 (분석 대상)", value=st.session_state.report_query_for_display)

# 사용자 이름과 기업명이 모두 입력된 경우에만 리포트 표시
if st.session_state.username and st.session_state.report_query_for_display:
    report_query_display = st.session_state.report_query_for_display 
    st.subheader(f"**{report_query_display}**의 미래 모습 리포트")

    # 마크다운 텍스트를 PDF로 변환하는 함수
    def create_pdf(markdown_text, title):
        pdf = FPDF()
        
        # 폰트 파일 경로 설정 (다운로드한 폰트 파일명으로 변경)
        font_path = os.path.join(os.path.dirname(__file__), 'NotoSansKR-Regular.ttf')

        try:
            if not os.path.exists(font_path):
                st.warning("폰트 파일(NotoSansKR-Regular.ttf)을 찾을 수 없습니다. 기본 폰트로 대체되며, 한글이 깨질 수 있습니다.")
                pdf.set_font("helvetica", 'B', 16) # 기본 폰트 설정
                font_registered = False
            else:
                # FPDF에 폰트 추가 및 등록
                pdf.add_font('notosans', '', font_path)
                pdf.add_font('notosans', 'B', font_path) # bold 폰트도 추가
                font_registered = True
        except Exception as e:
            st.error(f"폰트 등록 중 오류 발생: {e}. 기본 폰트로 대체됩니다.")
            pdf.set_font("helvetica", 'B', 16)
            font_registered = False

        pdf.add_page()
        
        # 제목 추가 (등록된 폰트 또는 기본 폰트 사용)
        if font_registered:
            pdf.set_font("notosans", 'B', 16)
        else:
            pdf.set_font("helvetica", 'B', 16)
        pdf.multi_cell(0, 10, title, align=Align.C)
        pdf.ln(10)
        
        # 마크다운 텍스트를 PDF에 추가 (등록된 폰트 또는 기본 폰트 사용)
        if font_registered:
            pdf.set_font("notosans", '', 12)
        else:
            pdf.set_font("helvetica", '', 12)
            markdown_text = markdown_text.encode('latin-1', 'replace').decode('latin-1')

        pdf.multi_cell(0, 8, markdown_text)
        
        # PDF 데이터를 바이트로 변환
        return bytes(pdf.output())

    # DB에서 'company_future' 타입의 리포트 데이터를 불러옵니다.
    company_future_reports = asyncio.run(load_reports_from_db(
        report_type='future',
        query=report_query_display, 
        year=datetime.datetime.now().year, 
        month=None,
        username = st.session_state.username
        ))

    if company_future_reports:
        # 미래 모습 보고서는 단일 보고서이므로 최신 하나만 보여줍니다.
        report_content = company_future_reports[0]['content']
        st.markdown(report_content)
        
        pdf_data = create_pdf(report_content, f"{report_query_display} 미래 모습 보고서")
        
        st.download_button(
            label="📄 리포트 PDF로 다운로드",
            data=pdf_data,
            file_name=f"{report_query_display}_미래_모습_보고서.pdf",
            mime="application/pdf"
        )
    else:
        st.info("아직 생성된 미래 모습 보고서가 없습니다. 메인 페이지에서 리포트를 생성해주세요.")
else:
    st.warning("사이드바에 사용자 이름과 기업명을 입력해야 리포트를 볼 수 있습니다.")

st.markdown("---")
st.page_link("pages/async_home.py", label="홈화면으로 돌아가기", icon="🏠")