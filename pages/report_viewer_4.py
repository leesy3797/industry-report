import streamlit as st
import sys
import os
import datetime
from fpdf import FPDF
from fpdf.enums import Align
import io
from report_generator import load_reports_from_db


# 현재 파일의 부모 디렉토리 (프로젝트 루트)를 sys.path에 추가
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

st.set_page_config(page_title="[4] 미래 모습 보고서", layout="wide")
st.title("🚀 미래 모습 보고서")

# 세션 상태에서 리포트 생성 시 사용된 쿼리 값을 가져옵니다.
report_query_display = st.session_state.get('report_query_for_display', '분석 대상') 

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
company_future_reports = load_reports_from_db(report_type='future', company=report_query_display, year=datetime.datetime.now().year, month=None)

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
    st.info("아직 생성된 기업 트렌드 분석 리포트가 없습니다. 메인 페이지에서 리포트를 생성해주세요.")

st.markdown("---")
st.page_link("pages/home.py", label="홈화면으로 돌아가기", icon="🏠")