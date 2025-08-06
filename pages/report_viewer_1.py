import streamlit as st
import sys
import os
import datetime
from fpdf import FPDF
from fpdf.enums import Align
import io
from report_generator import _load_yearly_reports_content


# 현재 파일의 부모 디렉토리 (프로젝트 루트)를 sys.path에 추가
# 이 부분이 report_generator.py를 임포트하기 위해 필요합니다.
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

st.set_page_config(page_title="[1] 연도별 핵심 이슈 분석", layout="wide")
st.title("📄 연도별 주요 이슈 분석")

# 세션 상태에서 리포트 생성 시 사용된 쿼리 값을 가져옵니다.
report_query_display = st.session_state.get('report_query_for_display', '분석 대상') 
st.subheader(f"**{report_query_display}**의 연도별 주요 이슈 분석 리포트")


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

yearly_reports_content = _load_yearly_reports_content(company=report_query_display)

if yearly_reports_content:
    # 여러 해에 걸친 보고서를 하나로 합쳐서 보여줍니다.
    combined_content = "\n\n---\n\n".join(yearly_reports_content)
    st.markdown(combined_content)

    pdf_data = create_pdf(combined_content, f"{report_query_display} 연도별 주요 이슈 분석")
    
    st.download_button(
        label="📄 리포트 PDF로 다운로드",
        data=pdf_data,
        file_name=f"{report_query_display}_연도별_주요_이슈_분석.pdf",
        mime="application/pdf"
    )
else:
    st.info("아직 생성된 연도별 이슈 리포트가 없습니다. 메인 페이지에서 리포트를 생성해주세요.")

st.markdown("---")
st.page_link("pages/home.py", label="홈화면으로 돌아가기", icon="🏠")
