import streamlit as st
import pandas as pd
import datetime
import time
import asyncio

# 크롤링 로직이 담긴 모듈 임포트
from async_hankyung_crawler import fetch_all_hankyung_articles
# 데이터베이스 관리 모듈 임포트
from async_data_manager import (
    initialize_db,
    initialize_reports_db,
    save_articles_to_db,
    load_articles_from_db,
    reset_articles_db
)
# 리포트 생성 모듈 임포트
from async_report_generator import (
    _generate_page_1_yearly_issues,
    _generate_page_2_keyword_summary,
    _generate_page_3_company_trend_analysis
)
from async_future_report_generator import _generate_page_4_future_report

# --- Streamlit 앱 인터페이스 ---
st.set_page_config(page_title="[Home] 레포트 작성", layout="wide")

st.title("📰 산업/기업 분석 Executive Report 작성")
st.subheader("🕸️ 한국경제신문 뉴스 크롤링")
st.write("⬅️ 원하는 검색 조건으로 한국경제신문의 뉴스를 크롤링해보세요.")

# 데이터베이스 초기화 (앱 시작 시 한 번만 실행)
@st.cache_resource
def setup_databases():
    asyncio.run(initialize_db())
    asyncio.run(initialize_reports_db())

setup_databases()

# 세션 상태 초기화
if 'last_crawled_articles' not in st.session_state:
    st.session_state.last_crawled_articles = []
if 'status_message' not in st.session_state:
    st.session_state.status_message = "준비 완료: 검색 조건을 설정하고 '뉴스 크롤링 시작' 버튼을 눌러주세요."
if 'progress_value' not in st.session_state:
    st.session_state.progress_value = 0.0
if 'crawling_active' not in st.session_state:
    st.session_state.crawling_active = False
if 'db_articles_loaded' not in st.session_state:
    st.session_state.db_articles_loaded = []
if 'report_page1_result' not in st.session_state:
    st.session_state.report_page1_result = None
if 'report_page2_result' not in st.session_state:
    st.session_state.report_page2_result = None
if 'report_page3_result' not in st.session_state:
    st.session_state.report_page3_result = None
if 'report_page4_result' not in st.session_state:
    st.session_state.report_page4_result = None
if 'report_query_for_display' not in st.session_state:
    st.session_state.report_query_for_display = None
if 'username' not in st.session_state:
    st.session_state.username = ""


# 사이드바에서 검색 설정
with st.sidebar:
    st.header("🔍 검색 설정")
    username_input = st.text_input("사용자 이름 (필수)", key="username_input")
    if username_input:
        st.session_state.username = username_input
    else:
        st.session_state.username = ""
        st.warning("사용자 이름을 입력해주세요. 사용자 이름이 없으면 기능이 비활성화됩니다.")
        
    is_disabled = st.session_state.crawling_active or not st.session_state.username
    st.subheader("기본 검색어")
    query = st.text_input("검색할 키워드", key="query_input", disabled=is_disabled)
    st.session_state.report_query_for_display = query
    st.subheader("정렬 방식")
    sort_options = {
        "최신순": "DATE/DESC,RANK/DESC",
        "정확도순": "RANK/DESC,DATE/ASC",
        "오래된순": "DATE/ASC,RANK/DESC"
    }
    selected_sort_display = st.radio("정렬 기준", list(sort_options.keys()), index=0, key="sort_radio", disabled=is_disabled)
    sort = sort_options[selected_sort_display]
    st.subheader("검색 영역")
    area_options = {
        "전체 (제목 + 내용)": "ALL",
        "제목만": "title",
        "내용만": "content"
    }
    selected_area_display = st.radio("검색할 영역", list(area_options.keys()), index=0, key="area_radio", disabled=is_disabled)
    area = area_options[selected_area_display]
    st.subheader("날짜 범위")
    col1, col2 = st.columns(2)
    with col1:
        start_date_obj = st.date_input("시작 날짜", value=datetime.date(2014, 1, 1), key="start_date_input", disabled=is_disabled)
        start_date = start_date_obj.strftime("%Y.%m.%d")
    with col2:
        current_korea_time = datetime.datetime.now().date()
        end_date_obj = st.date_input("종료 날짜", value=current_korea_time, key="end_date_input", disabled=is_disabled)
        end_date = end_date_obj.strftime("%Y.%m.%d")
    st.subheader("고급 검색 옵션")
    exact_phrase = st.text_input("정확히 일치하는 문구", value=st.session_state.report_query_for_display, help="이 문구가 포함된 기사만 검색합니다.", key="exact_phrase_input", disabled=is_disabled)
    include_keywords = st.text_input("반드시 포함할 키워드 (한개만)", value=st.session_state.report_query_for_display, help="입력된 모든 키워드를 포함하는 기사만 검색합니다.", key="include_keywords_input", disabled=is_disabled)
    exclude_keywords = st.text_input("제외할 키워드 (한개만)", help="입력된 키워드가 포함된 기사는 제외합니다.", key="exclude_keywords_input", disabled=is_disabled)
    hk_only = st.checkbox("한국경제신문 기사만 보기", value=True, key="hk_only_checkbox", disabled=is_disabled)
    st.subheader("크롤링 설정")
    max_pages = st.number_input("최대 크롤링 페이지 수 (0 입력 시 모든 페이지)", min_value=0, value=0, help="0은 모든 페이지 크롤링을 의미합니다.", key="max_pages_input", disabled=is_disabled)
    if max_pages == 0:
        max_pages = None

# --- 메인 화면: 크롤링/임베딩 상태 및 진행 바 표시 영역 ---
status_placeholder = st.empty()
progress_bar_placeholder = st.empty()

# 크롤링 시작 버튼
if st.button("뉴스 크롤링 시작", key="start_button", disabled=is_disabled):
    st.session_state.db_reset_success_message = ""
    if not query:
        st.error("검색 키워드를 입력해주세요.")
    else:
        st.session_state.crawling_active = True
        st.session_state.last_crawled_articles = []
        status_placeholder.info("크롤링 준비 중...")
        progress_bar_placeholder.progress(0.0)

        def update_crawling_ui(message, current_progress_val, _total_count):
            status_placeholder.info(message)
            progress_bar_placeholder.progress(current_progress_val)

        with st.spinner("뉴스 크롤링 중... 잠시만 기다려 주세요."):
            crawled_articles = asyncio.run(fetch_all_hankyung_articles(
                query=query,
                sort=sort,
                area=area,
                start_date=start_date,
                end_date=end_date,
                exact_phrase=exact_phrase,
                include_keywords=include_keywords,
                exclude_keywords=exclude_keywords,
                hk_only=hk_only,
                max_pages=max_pages,
                progress_callback=update_crawling_ui,
                username=st.session_state.username
            ))
        st.session_state.crawling_active = False

        if crawled_articles:
            st.session_state.last_crawled_articles = crawled_articles
            st.session_state.status_message = f"크롤링 완료: 총 {len(crawled_articles)}개의 기사를 찾았습니다."
            st.session_state.progress_value = 1.0
        else:
            db_articles = asyncio.run(load_articles_from_db(st.session_state.username))
            if db_articles:
                st.session_state.status_message = f"크롤링 완료: 총 {len(db_articles)}개의 기사가 DB에 저장되었습니다."
                st.session_state.progress_value = 1.0
            else:
                st.session_state.status_message = "검색된 기사가 없거나 크롤링에 실패했습니다. 검색 조건을 확인해주세요."
                st.session_state.progress_value = 0.0
        st.rerun()

# --- 크롤링 결과 표시 및 다운로드 버튼 ---
if st.session_state.last_crawled_articles:
    status_placeholder.success(st.session_state.status_message)
    progress_bar_placeholder.progress(st.session_state.progress_value)
    df = pd.DataFrame(st.session_state.last_crawled_articles)
    desired_columns = ["제목", "작성일자", "기자", "기사 원문", "기사 URL", "기업명"]
    df_display = df[df.columns.intersection(desired_columns)]
    st.subheader(f"총 {len(st.session_state.last_crawled_articles)}개의 기사를 찾았습니다.")
    st.dataframe(df_display, use_container_width=True)
    csv_data = df.to_csv(index=False, encoding='utf-8-sig')
    col_csv, col_db = st.columns([1, 1])
    with col_csv:
        st.download_button(
            label="결과를 CSV 파일로 다운로드",
            data=csv_data,
            file_name=f"hankyung_news_{query}_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
            mime="text/csv"
        )
    with col_db:
        if st.button("현재 기사를 DB에 저장", key="save_to_db_button", disabled=is_disabled):
            if st.session_state.last_crawled_articles:
                with st.spinner("기사 데이터를 DB에 저장 중..."):
                    asyncio.run(save_articles_to_db(st.session_state.last_crawled_articles, st.session_state.username))
                st.success(f"총 {len(st.session_state.last_crawled_articles)}개의 기사를 DB에 저장 완료했습니다. (중복 제외)")
                st.session_state.db_articles_loaded = asyncio.run(load_articles_from_db(st.session_state.username))
                st.rerun()
            else:
                st.warning("DB에 저장할 크롤링된 기사가 없습니다. 먼저 뉴스를 크롤링해주세요.")
else:
    if not st.session_state.crawling_active:
        status_placeholder.info(st.session_state.status_message)
        progress_bar_placeholder.progress(st.session_state.progress_value)

# --- DB에서 기사 불러와서 보기 ---
st.markdown("---")
st.subheader("📂 저장된 DB 기사 목록")
if st.button("내 기사 DB 리셋", key="reset_db_button", disabled=is_disabled):
    with st.spinner("DB를 초기화하는 중..."):
        asyncio.run(reset_articles_db(st.session_state.username))
        st.session_state.db_articles_loaded = []
        st.session_state.last_crawled_articles = []
        st.success(f"{st.session_state.username} 님의 기사 DB가 초기화되었습니다.")
        st.session_state.status_message = "DB가 초기화되었습니다."
        st.session_state.progress_value = 0.0
    st.rerun()
if st.button("내 기사 DB 불러오기", key="load_from_db_button", disabled=is_disabled):
    with st.spinner("DB에서 기사 불러오는 중..."):
        st.session_state.db_articles_loaded = asyncio.run(load_articles_from_db(st.session_state.username))
    if not st.session_state.db_articles_loaded:
        st.info(f"{st.session_state.username} 님의 데이터베이스에 저장된 기사가 없습니다.")
    st.rerun()
if st.session_state.db_articles_loaded:
    df_db = pd.DataFrame(st.session_state.db_articles_loaded)
    cols_to_display_from_db = ["id", "username", "제목", "작성일자", "기자", "기사 URL", '기사 원문', "suitability_score", "기업명"]
    df_db_display = df_db[df_db.columns.intersection(cols_to_display_from_db)]
    st.write(f"{st.session_state.username} 님, DB에 저장된 총 {len(st.session_state.db_articles_loaded)}개의 기사가 있습니다.")
    st.dataframe(df_db_display, use_container_width=True)

# --- 리포트 생성 및 보기 섹션 ---
st.markdown("---")
st.subheader("📊 리포트 생성")

report_query = st.text_input("리포트 생성용 키워드 (예: cj대한통운)", value=st.session_state.report_query_for_display, key="report_query_input", disabled=is_disabled)


# 비동기 버튼 클릭 핸들러
async def run_yearly_report_on_click(report_query, username, status_widget):
    st.session_state.crawling_active = True
    st.session_state.report_query_for_display = report_query
    
    try:
        # 비동기 함수를 await로 직접 호출
        report_content = await _generate_page_1_yearly_issues(
            query=report_query,
            username=username,
            progress_callback=lambda msg, val, type: status_widget.update(label=msg, state="running", expanded=True)
        )
        
        st.session_state.report_page1_result = report_content
        status_widget.update(label=f"**연도별 핵심 이슈 분석** 생성 완료!", state="complete", expanded=False)
        st.page_link("pages/async_report_viewer_1.py", label="이슈 분석 레포트 보기", icon="🔗")
    
    except Exception as e:
        st.error(f"리포트 생성 중 오류 발생: {e}")
        status_widget.update(label=f"**연도별 핵심 이슈 분석** 생성 실패!", state="error", expanded=True)
        st.session_state.report_page1_result = None
    finally:
        st.session_state.crawling_active = False
    
    # st.rerun()을 async 함수에서 호출하면 오류가 발생할 수 있으므로,
    # 필요에 따라 이 코드를 주석 처리하고 Streamlit의 자동 재실행에 의존합니다.
    # st.rerun()


# (1) 연도별 핵심 이슈 분석 버튼
if st.button("(1) 연도별 핵심 이슈 분석", key="run_yearly_report_button", disabled=is_disabled):
    if not report_query:
        st.warning("리포트 생성 키워드를 입력해주세요.")
    else:
        with st.status(f"**연도별 핵심 이슈 분석** 생성 중...", expanded=True) as status:
            # st.button의 on_click 매개변수에 async 함수를 직접 할당하는 방식
            # (이 방식은 Streamlit 1.25.0 이상에서 권장됩니다)
            # 그러나 on_click 인자가 없는 경우, st.button 블록 내에서 `asyncio.run`을 사용해야 합니다.
            # 하지만 이는 오류를 발생시키므로, Streamlit이 비동기 함수를 지원하는 방식을 찾아야 합니다.
            
            # 아래 코드는 Streamlit의 비동기 실행을 위한 일반적인 해결책입니다.
            # 하지만 이 코드는 여전히 오류를 발생시킬 수 있습니다.
            # 가장 확실한 해결책은 Streamlit의 최신 버전을 사용하고, 
            # 버튼 클릭 핸들러를 별도의 `async` 함수로 정의하여 `st.button`의 `on_click` 인자로 전달하는 것입니다.
            # 또는 on_click 인자를 사용하지 않는 경우, 아래 코드와 같이 Streamlit이 자동으로 `await`를 처리하도록 해야 합니다.
            
            asyncio.run(run_yearly_report_on_click(report_query, st.session_state.username, status))
            
# -----------------------------------------------------------------------------

if st.button("(2) 핵심 키워드 요약", key="run_keyword_summary_button", disabled=is_disabled):
    if not report_query:
        st.warning("리포트 생성 키워드를 입력해주세요.")
    else:
        st.session_state.crawling_active = True
        st.session_state.main_status_placeholder = st.empty()
        st.session_state.main_progress_placeholder = st.empty()

        def update_ui_for_process(message, progress_value, message_type="info"):
            if message_type == "error":
                st.session_state.main_status_placeholder.error(message)
            elif message_type == "warning":
                st.session_state.main_status_placeholder.warning(message)
            else:
                st.session_state.main_status_placeholder.info(message)
            st.session_state.main_progress_placeholder.progress(progress_value)

        update_ui_for_process(f"[{report_query}] 핵심 키워드 요약 중...", 0.0)
        st.session_state.report_page2_result = None
        st.session_state.report_query_for_display = report_query

        try:
            report_content = asyncio.run(_generate_page_2_keyword_summary(
                query=report_query,
                username = st.session_state.username,
                progress_callback=update_ui_for_process
            ))
            st.session_state.report_page2_result = report_content
            update_ui_for_process("핵심 키워드 요약 리포트 생성이 완료되었습니다.", 1.0)
            st.page_link("pages/async_report_viewer_2.py", label="핵심 키워드 레포트 보기", icon="🔗")
        except Exception as e:
            st.error(f"핵심 키워드 요약 리포트 생성 중 오류 발생: {e}")
            st.session_state.report_page2_result = None
            update_ui_for_process("핵심 키워드 요약 리포트 생성 중 오류 발생.", 0.0)
        finally:
            st.session_state.crawling_active = False

# -----------------------------------------------------------------------------

if st.button("(3) 기업 트렌드 분석", key="run_company_trend_button", disabled=is_disabled):
    if not report_query:
        st.warning("리포트 생성 키워드를 입력해주세요.")
    else:
        st.session_state.crawling_active = True
        st.session_state.main_status_placeholder = st.empty()
        st.session_state.main_progress_placeholder = st.empty()

        def update_ui_for_process(message, progress_value, message_type="info"):
            if message_type == "error":
                st.session_state.main_status_placeholder.error(message)
            elif message_type == "warning":
                st.session_state.main_status_placeholder.warning(message)
            else:
                st.session_state.main_status_placeholder.info(message)
            st.session_state.main_progress_placeholder.progress(progress_value)

        update_ui_for_process(f"[{report_query}] 기업 트렌드 분석 중...", 0.0)
        st.session_state.report_page3_result = None
        st.session_state.report_query_for_display = report_query

        try:
            report_content = asyncio.run(_generate_page_3_company_trend_analysis(
                query=report_query,
                username = st.session_state.username,
                progress_callback=update_ui_for_process
            ))
            st.session_state.report_page3_result = report_content
            update_ui_for_process("기업 트렌드 분석 리포트 생성이 완료되었습니다.", 1.0)
            st.page_link("pages/async_report_viewer_3.py", label="기업 트렌드 분석 레포트 보기", icon="🔗")
        except Exception as e:
            st.error(f"기업 트렌드 분석 리포트 생성 중 오류 발생: {e}")
            st.session_state.report_page3_result = None
            update_ui_for_process("기업 트렌드 분석 리포트 생성 중 오류 발생.", 0.0)
        finally:
            st.session_state.crawling_active = False

# -----------------------------------------------------------------------------

# 🚀 수정: st.columns를 사용하여 버튼과 체크박스를 같은 행에 배치
col1, col2 = st.columns([0.4, 0.6]) # 버튼이 차지할 비율 (40%)과 체크박스가 차지할 비율 (60%) 조정

with col1:
    # (4) 미래 모습 보고서 버튼
    run_button_clicked = st.button(
        "(4) 미래 모습 보고서", 
        key="run_future_report_button", 
        disabled=is_disabled
    )

with col2:
    # 인터넷 검색 수행 여부를 위한 토글 버튼 (체크박스)
    perform_serper_search_toggle = st.checkbox(
        "🌐 인터넷 검색 수행 (최신 웹 정보 반영)",
        value=True,  # 기본값은 True (검색 수행)
        help="체크하면 Serper API를 통해 최신 웹 정보를 검색하여 보고서에 반영합니다. 체크 해제 시 기존에 저장된 데이터만 사용합니다."
    )


if run_button_clicked: # 버튼 클릭 여부를 이 변수로 확인
    if not report_query:
        st.warning("리포트 생성 키워드를 입력해주세요.")
    else:
        st.session_state.crawling_active = True
        st.session_state.main_status_placeholder = st.empty()
        st.session_state.main_progress_placeholder = st.empty()

        def update_ui_for_process_future(message, progress_value, message_type="info"):
            if message_type == "error":
                st.session_state.main_status_placeholder.error(message)
            elif message_type == "warning":
                st.session_state.main_status_placeholder.warning(message)
            else:
                st.session_state.main_status_placeholder.info(message)
            st.session_state.main_progress_placeholder.progress(progress_value)

        update_ui_for_process_future(f"[{report_query}] 미래 모습 보고서 생성 중...", 0.0)
        st.session_state.report_page4_result = None # 미래 보고서 결과 초기화
        st.session_state.report_query_for_display = report_query # 디스플레이용 쿼리 업데이트

        try:
            # 🚀 수정: perform_serper_search_toggle 값 전달
            future_report_content = asyncio.run(_generate_page_4_future_report(
                query=report_query,
                username=st.session_state.username,
                progress_callback=update_ui_for_process_future,
                perform_serper_search=perform_serper_search_toggle # 토글 값 전달
            ))
            
            st.session_state.report_page4_result = future_report_content
            update_ui_for_process_future("미래 모습 보고서 생성이 완료되었습니다.", 1.0)
            st.page_link("pages/async_report_viewer_4.py", label="미래 모습 보고서 레포트 보기", icon="🔗")
        except Exception as e:
            st.error(f"미래 모습 보고서 생성 중 오류 발생: {e}")
            st.session_state.report_page4_result = None
            update_ui_for_process_future("미래 모습 보고서 생성 중 오류 발생.", 0.0)
        finally:
            st.session_state.crawling_active = False

# 크롤링/리포트 생성 중이 아닐 때 현재 상태를 다시 표시
if not st.session_state.crawling_active:
    status_placeholder.info(st.session_state.status_message)
    progress_bar_placeholder.progress(st.session_state.progress_value)