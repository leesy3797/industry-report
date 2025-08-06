import streamlit as st
import pandas as pd
import datetime
import time

# 크롤링 로직이 담긴 모듈 임포트
from hankyung_crawler import fetch_all_hankyung_articles
# 데이터베이스 관리 모듈 임포트
from data_manager import initialize_db, save_articles_to_db, load_articles_from_db
from data_manager import reset_articles_db
# 리포트 생성 모듈 임포트
from report_generator import (
    _generate_page_1_yearly_issues,
    initialize_reports_db,
    _generate_page_2_keyword_summary,
    _generate_page_3_company_trend_analysis
)
from future_report_generator import _generate_page_4_future_report 

from vector_db_manager import (
    embed_and_store_articles_to_chroma,
    get_chroma_status,
    search_chroma_by_query,
)
import asyncio # asyncio 모듈 추가

# --- Streamlit 앱 인터페이스 ---
st.set_page_config(page_title="[Home] 레포트 작성", layout="wide")

st.title("📰 산업/기업 분석 Executive Report 작성")
st.subheader("🕸️ 한국경제신문 뉴스 크롤링")
st.write("⬅️ 원하는 검색 조건으로 한국경제신문의 뉴스를 크롤링해보세요.")

# 데이터베이스 초기화 (앱 시작 시 한 번만 실행)
initialize_db()
initialize_reports_db()

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
if 'chroma_status' not in st.session_state:
    st.session_state.chroma_status = {}
if 'chroma_search_results' not in st.session_state:
    st.session_state.chroma_search_results = []
if 'report_page1_result' not in st.session_state:
    st.session_state.report_page1_result = {}
if 'report_query_for_display' not in st.session_state:
    st.session_state.report_query_for_display = None


# 사이드바에서 검색 설정
with st.sidebar:
    st.header("🔍 검색 설정")

    st.subheader("기본 검색어")
    query = st.text_input("검색할 키워드", key="query_input",
                          disabled=st.session_state.crawling_active)
    st.session_state.report_query_for_display = query

    st.subheader("정렬 방식")
    sort_options = {
        "최신순": "DATE/DESC,RANK/DESC",
        "정확도순": "RANK/DESC,DATE/DESC",
        "오래된순": "DATE/ASC,RANK/DESC"
    }
    selected_sort_display = st.radio("정렬 기준", list(sort_options.keys()), index=2, key="sort_radio",
                                    disabled=st.session_state.crawling_active)
    sort = sort_options[selected_sort_display]

    st.subheader("검색 영역")
    area_options = {
        "전체 (제목 + 내용)": "ALL",
        "제목만": "title",
        "내용만": "content"
    }
    selected_area_display = st.radio("검색할 영역", list(area_options.keys()), index=0, key="area_radio",
                                    disabled=st.session_state.crawling_active)
    area = area_options[selected_area_display]

    st.subheader("날짜 범위")
    col1, col2 = st.columns(2)
    with col1:
        start_date_obj = st.date_input("시작 날짜", value=datetime.date(2014, 1, 1), key="start_date_input",
                                     disabled=st.session_state.crawling_active)
        start_date = start_date_obj.strftime("%Y.%m.%d")
    with col2:
        current_korea_time = datetime.datetime.now().date()
        end_date_obj = st.date_input("종료 날짜", value=current_korea_time, key="end_date_input",
                                   disabled=st.session_state.crawling_active)
        end_date = end_date_obj.strftime("%Y.%m.%d")

    st.subheader("고급 검색 옵션")
    exact_phrase = st.text_input("정확히 일치하는 문구", help="이 문구가 포함된 기사만 검색합니다.", key="exact_phrase_input",
                                 disabled=st.session_state.crawling_active)
    include_keywords = st.text_input("반드시 포함할 키워드 (공백으로 구분)", help="입력된 모든 키워드를 포함하는 기사만 검색합니다.", key="include_keywords_input",
                                     disabled=st.session_state.crawling_active)
    exclude_keywords = st.text_input("제외할 키워드 (공백으로 구분)", help="입력된 키워드가 포함된 기사는 제외합니다.", key="exclude_keywords_input",
                                     disabled=st.session_state.crawling_active)

    hk_only = st.checkbox("한국경제신문 기사만 보기", value=True, key="hk_only_checkbox",
                          disabled=st.session_state.crawling_active)

    st.subheader("크롤링 설정")
    max_pages = st.number_input("최대 크롤링 페이지 수 (0 입력 시 모든 페이지)", min_value=0, value=0, help="0은 모든 페이지 크롤링을 의미합니다.", key="max_pages_input",
                                 disabled=st.session_state.crawling_active)
    if max_pages == 0:
        max_pages = None

    sleep_time = st.slider("페이지당 요청 간 지연 시간 (초)", min_value=0.1, max_value=5.0, value=0.5, step=0.1, key="sleep_time_slider",
                           disabled=st.session_state.crawling_active)

# --- 메인 화면: 크롤링/임베딩 상태 및 진행 바 표시 영역 ---
status_placeholder = st.empty()
progress_bar_placeholder = st.empty()

# 크롤링 시작 버튼
if st.button("뉴스 크롤링 시작", key="start_button", disabled=st.session_state.crawling_active):
    st.session_state.db_reset_success_message = ""  # DB 리셋 메시지 지움
    if not query:
        st.error("검색 키워드를 입력해주세요.")
    else:
        st.session_state.crawling_active = True
        st.session_state.last_crawled_articles = []
        status_placeholder.info("크롤링 준비 중...")
        progress_bar_placeholder.progress(0.0)

        # 콜백 함수: 크롤링 진행 상황을 UI에 업데이트
        def update_crawling_ui(message, current_progress_val, _total_count):
            status_placeholder.info(message)
            progress_bar_placeholder.progress(current_progress_val)

        with st.spinner("뉴스 크롤링 중... 잠시만 기다려 주세요."):
            crawled_articles = fetch_all_hankyung_articles(
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
                sleep_time=sleep_time,
                progress_callback=update_crawling_ui
            )
        st.session_state.crawling_active = False

        if crawled_articles:
            st.session_state.last_crawled_articles = crawled_articles
            st.session_state.status_message = f"크롤링 완료: 총 {len(crawled_articles)}개의 기사를 찾았습니다."
            st.session_state.progress_value = 1.0
        else:
            # DB에서 실제 저장된 기사 수 확인
            db_articles = load_articles_from_db()
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
        if st.button("현재 기사를 DB에 저장", key="save_to_db_button", disabled=st.session_state.crawling_active):
            if st.session_state.last_crawled_articles:
                with st.spinner("기사 데이터를 DB에 저장 중..."):
                    save_articles_to_db(st.session_state.last_crawled_articles)
                st.success(f"총 {len(st.session_state.last_crawled_articles)}개의 기사를 DB에 저장 완료했습니다. (중복 제외)")
                st.session_state.db_articles_loaded = load_articles_from_db()
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

# DB 리셋 버튼
if st.button("기사 DB 리셋", key="reset_db_button", disabled=st.session_state.crawling_active):
    with st.spinner("DB를 초기화하는 중..."):
        reset_articles_db()
        st.session_state.db_articles_loaded = []
        st.session_state.last_crawled_articles = []
        st.success("기사 DB가 완전히 초기화되었습니다.")
        st.session_state.status_message = "DB가 초기화되었습니다."
        st.session_state.progress_value = 0.0
    st.rerun()

if st.button("DB에서 기사 불러오기", key="load_from_db_button", disabled=st.session_state.crawling_active):
    with st.spinner("DB에서 기사 불러오는 중..."):
        st.session_state.db_articles_loaded = load_articles_from_db()
    if not st.session_state.db_articles_loaded:
        st.info("데이터베이스에 저장된 기사가 없습니다.")
    st.rerun()

if st.session_state.db_articles_loaded:
    df_db = pd.DataFrame(st.session_state.db_articles_loaded)
    cols_to_display_from_db = ["id", "제목", "작성일자", "기자", "기사 URL", '기사 원문', "suitability_score", "기업명"]
    df_db_display = df_db[df_db.columns.intersection(cols_to_display_from_db)]

    st.write(f"DB에 저장된 총 {len(st.session_state.db_articles_loaded)}개의 기사가 있습니다.")
    st.dataframe(df_db_display, use_container_width=True)

# --- 임베딩 및 벡터 DB 관리 섹션 ---
st.markdown("---")
st.subheader("⚙️ 임베딩 및 벡터 DB 관리")
db_articles_exist_for_embed = bool(st.session_state.db_articles_loaded) or bool(load_articles_from_db())
if st.button("DB 기사 임베딩 및 벡터 DB 저장", key="embed_to_chroma_button", disabled=not db_articles_exist_for_embed or st.session_state.crawling_active):
    if not db_articles_exist_for_embed:
        st.warning("먼저 DB에 저장된 기사가 있어야 임베딩을 진행할 수 있습니다. 'DB에서 기사 불러오기'를 클릭하거나 크롤링 후 DB에 저장해주세요.")
    else:
        st.session_state.crawling_active = True
        status_placeholder_embed = st.empty()
        progress_bar_placeholder_embed = st.empty()

        def embed_progress_callback(message, progress_val):
            status_placeholder_embed.info(message)
            progress_bar_placeholder_embed.progress(progress_val)

        try:
            status_placeholder_embed.info("DB 기사 적합성 판정 및 임베딩 중... (시간이 다소 소요될 수 있습니다.)")
            progress_bar_placeholder_embed.progress(0.0)

            articles_from_db_for_embed = load_articles_from_db()
            embed_and_store_articles_to_chroma(
                articles=articles_from_db_for_embed,
                progress_callback=embed_progress_callback
            )
            st.success("기사 임베딩 및 벡터 DB 저장이 완료되었습니다.")
            st.session_state.chroma_status = get_chroma_status()
            progress_bar_placeholder_embed.empty()
            status_placeholder_embed.empty()
        except Exception as e:
            st.error(f"임베딩 중 오류 발생: {e}")
        finally:
            st.session_state.crawling_active = False
            st.rerun()

# --- ChromaDB 현황 및 시각화 섹션 ---

st.markdown("---")
st.subheader("📊 벡터 DB (ChromaDB) 현황")
if st.button("ChromaDB 현황 새로고침", key="refresh_chroma_status_button", disabled=st.session_state.crawling_active):
    st.session_state.chroma_status = get_chroma_status()

if st.session_state.chroma_status:
    st.write(f"**총 임베딩 문서 수 (ChromaDB)**: {st.session_state.chroma_status.get('총 문서 수 (ChromaDB)', 0)}개")
    st.write(f"**SQLite에 저장된 전체 기사 수**: {st.session_state.chroma_status.get('SQLite에 저장된 전체 기사 수', 0)}개")
    st.write("**기사 적합도 판정 분포 (SQLite 기준)**:")
    suitability_scores_data = st.session_state.chroma_status.get("기사 적합도 점수 분포 (SQLite 기준)", {})

    suitable_count = suitability_scores_data.get(1, 0)
    unsuitable_count = suitability_scores_data.get(0, 0)

    st.write(f"- **적합 (1)**: {suitable_count}개")
    st.write(f"- **부적합 (0)**: {unsuitable_count}개")

    if suitable_count + unsuitable_count > 0:
        chart_data = pd.DataFrame({
            '판정': ['적합', '부적합'],
            '개수': [suitable_count, unsuitable_count]
        })
        st.bar_chart(chart_data.set_index('판정'))
    else:
        st.info("적합도 판정 데이터가 없습니다. 기사 임베딩을 먼저 진행해주세요.")

    st.markdown("#### 벡터 DB 검색 테스트")
    search_query_input = st.text_input("검색할 문구를 입력하세요 (예: 한화에어로스페이스 방산 수출)", key="chroma_search_input",
                                     disabled=st.session_state.crawling_active)
    search_k = st.slider("가져올 결과 수", min_value=1, max_value=10, value=3, key="chroma_search_k",
                          disabled=st.session_state.crawling_active)

    search_filter_suitability = st.checkbox("적합한 기사만 검색", value=True, key="chroma_filter_checkbox",
                                            disabled=st.session_state.crawling_active)

    if st.button("벡터 검색 실행", key="run_vector_search_button", disabled=st.session_state.crawling_active):
        if search_query_input:
            with st.spinner("벡터 검색 실행 중..."):
                filter_dict = {"suitability_score": 1} if search_filter_suitability else None
                st.session_state.chroma_search_results = search_chroma_by_query(
                    search_query_input,
                    k=search_k,
                    filter_dict=filter_dict
                )
            if st.session_state.chroma_search_results:
                df_search_results = pd.DataFrame(st.session_state.chroma_search_results)
                df_search_results = df_search_results.sort_values(by='score', ascending=True)
                st.dataframe(df_search_results[['title', 'publish_date', 'suitability_score', 'score', 'url', 'content_preview']], use_container_width=True)
            else:
                st.info("검색 결과가 없거나 필터링 조건에 맞는 문서가 없습니다.")
        else:
            st.warning("검색할 문구를 입력해주세요.")
else:
    st.info("ChromaDB 현황을 확인하려면 'ChromaDB 현황 새로고침' 버튼을 눌러주세요. (기사 임베딩 후 확인 가능)")

# -----------------------------------------------------------------------------


st.markdown("---")
st.subheader("📊 리포트 생성 (테스트)")
# st.write("`report_generator.py` 모듈의 리포트 생성 함수들을 배치 처리하여 테스트합니다.")

# report_query는 이전에 정의된 query를 기본값으로 사용
# crawling_active는 보고서 생성 중에도 UI를 비활성화하는 데 사용
report_query = st.text_input("리포트 생성할 키워드", value=query, key="report_query_input",
                             disabled=st.session_state.crawling_active)

if st.button("(1) 연도별 핵심 이슈 분석", key="run_yearly_report_button", disabled=st.session_state.crawling_active):
    if not report_query:
        st.warning("리포트 생성 키워드를 입력해주세요.")
    else:
        st.session_state.crawling_active = True
        st.session_state.main_status_placeholder = st.empty()
        st.session_state.main_progress_placeholder = st.empty()

        def update_ui_for_process(message, progress_value, message_type="info"):
            """
            Streamlit UI를 업데이트하는 전역 함수.
            메시지, 진행률, 그리고 메시지 타입을 표시합니다.
            """
            if message_type == "error":
                st.session_state.main_status_placeholder.error(message)
            elif message_type == "warning":
                st.session_state.main_status_placeholder.warning(message)
            else:
                st.session_state.main_status_placeholder.info(message)

            st.session_state.main_progress_placeholder.progress(progress_value)
 
        # 전체 리포트 진행 상태를 업데이트할 때 사용할 메시지 (연도별 진행 상황은 _generate_page_1_yearly_issues 내부에서 처리)
        # progress_text_placeholder, progress_bar_placeholder_report 대신
        # 기존에 정의된 update_ui_for_process 함수와 전역 placeholder를 사용합니다.
        update_ui_for_process(f"[{report_query}] 연도별 핵심 이슈 분석 중...", 0.0)

        # report_page1_result는 단일 문자열로 변경
        st.session_state.report_page1_result = None # 이전 결과 초기화
        st.session_state.report_query_for_display = report_query

        try:
            # _generate_page_1_yearly_issues 함수에 query와 progress_callback 인자 전달
            report_content = _generate_page_1_yearly_issues(
                query=report_query,
                progress_callback=update_ui_for_process # 전역 콜백 함수 사용
            )

            st.session_state.report_page1_result = report_content
            
            # 리포트 생성이 완료되면 최종 메시지 및 진행률 갱신
            update_ui_for_process("연도별 핵심 이슈 리포트 생성이 완료되었습니다.", 1.0)
            
            # 외부 페이지로 이동하는 링크 (pages/report_viewer.py 파일이 존재해야 함)
            st.page_link("pages/report_viewer_1.py", label="이슈 분석 레포트 보기", icon="🔗")

        except Exception as e:
            st.error(f"리포트 생성 중 오류 발생: {e}")
            st.session_state.report_page1_result = None
            # 오류 발생 시 진행률 초기화 및 메시지 갱신
            update_ui_for_process("리포트 생성 중 오류 발생.", 0.0)
        finally:
            st.session_state.crawling_active = False

# -----------------------------------------------------------------------------

if st.button("(2) 핵심 키워드 요약", key="run_keyword_summary_button", disabled=st.session_state.crawling_active):
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
            report_content = _generate_page_2_keyword_summary(
                query=report_query,
                progress_callback=update_ui_for_process
            )
            st.session_state.report_page2_result = report_content
            update_ui_for_process("핵심 키워드 요약 리포트 생성이 완료되었습니다.", 1.0)
            st.page_link("pages/report_viewer_2.py", label="핵심 키워드 레포트 보기", icon="🔗")
        except Exception as e:
            st.error(f"핵심 키워드 요약 리포트 생성 중 오류 발생: {e}")
            st.session_state.report_page2_result = None
            update_ui_for_process("핵심 키워드 요약 리포트 생성 중 오류 발생.", 0.0)
        finally:
            st.session_state.crawling_active = False

# -----------------------------------------------------------------------------

if st.button("(3) 기업 트렌드 분석", key="run_company_trend_button", disabled=st.session_state.crawling_active):
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
            report_content = _generate_page_3_company_trend_analysis(
                query=report_query,
                progress_callback=update_ui_for_process
            )
            st.session_state.report_page3_result = report_content
            update_ui_for_process("기업 트렌드 분석 리포트 생성이 완료되었습니다.", 1.0)
            st.page_link("pages/report_viewer_3.py", label="기업 트렌드 분석 레포트 보기", icon="🔗")
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
        disabled=st.session_state.crawling_active
    )

with col2:
    # 인터넷 검색 수행 여부를 위한 토글 버튼 (체크박스)
    perform_serper_search_toggle = st.checkbox(
        "🌐 인터넷 검색 수행 (최신 웹 정보 반영)",
        value=False,  # 기본값은 True (검색 수행)
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
                progress_callback=update_ui_for_process_future,
                perform_serper_search=perform_serper_search_toggle # 토글 값 전달
            ))
            
            st.session_state.report_page4_result = future_report_content
            update_ui_for_process_future("미래 모습 보고서 생성이 완료되었습니다.", 1.0)
            st.page_link("pages/report_viewer_4.py", label="미래 모습 보고서 레포트 보기", icon="🔗")
        except Exception as e:
            st.error(f"미래 모습 보고서 생성 중 오류 발생: {e}")
            st.session_state.report_page4_result = None
            update_ui_for_process_future("미래 모습 보고서 생성 중 오류 발생.", 0.0)
        finally:
            st.session_state.crawling_active = False


# 크롤링/임베딩/리포트 생성 중이 아닐 때 현재 상태를 다시 표시
if not st.session_state.crawling_active:
    status_placeholder.info(st.session_state.status_message)
    progress_bar_placeholder.progress(st.session_state.progress_value)