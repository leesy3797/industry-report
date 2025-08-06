# report_generator.py (Updated with prompts.py)
import os
import time
import datetime
import sqlite3
from typing import List, Dict, Any
from dotenv import load_dotenv
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.prompts import PromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langchain.chains import create_history_aware_retriever, create_retrieval_chain
from langchain.chains.combine_documents import create_stuff_documents_chain
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain.schema import Document
import streamlit as st
import pandas as pd
import numpy as np
from tenacity import retry, wait_exponential, stop_after_attempt, retry_if_exception_type

# 기존 data_manager 모듈에서 기사 로드 함수만 임포트
from data_manager import load_articles_from_db

# 새롭게 분리한 프롬프트 파일을 임포트
from prompts import MONTHLY_REPORT_PROMPT, YEARLY_REPORT_PROMPT, KEYWORD_SUMMARY_PROMPT, COMPANY_TREND_ANALYSIS_PROMPT

# .env 파일 로드
load_dotenv()

# LangSmith 설정
if os.getenv("LANGCHAIN_API_KEY"):
    os.environ["LANGCHAIN_TRACING_V2"] = "true"
else:
    print("경고: LangSmith API 키가 설정되지 않아 LangSmith 트레이싱이 비활성화됩니다.")

# Google API 키 확인
if not os.getenv("GOOGLE_API_KEY"):
    raise ValueError("GOOGLE_API_KEY 환경 변수가 설정되어 있지 않습니다.")

# API 호출 제한 관리 (1분에 60회)
MAX_CALLS_PER_MINUTE = 10
API_CALL_INTERVAL_SECONDS = 60.0 / MAX_CALLS_PER_MINUTE
last_call_time = 0

# 보고서 DB 파일 설정
REPORTS_DATABASE_FILE = "reports.db"

# --- LLM 모델 초기화 (vector_db_manager에서 가져오는 대신 여기에 정의) ---
@st.cache_resource
def get_llm_model():
    """Gemini 2.0 Flash 모델 인스턴스를 캐시하여 반환합니다."""
    return ChatGoogleGenerativeAI(model="gemini-2.0-flash-lite", temperature=0.1)

# --- 보고서 DB 관리 함수 (data_manager에서 이동) ---
def initialize_reports_db():
    """보고서 저장용 SQLite 데이터베이스를 초기화합니다."""
    conn = None
    try:
        conn = sqlite3.connect(REPORTS_DATABASE_FILE)
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                report_type TEXT NOT NULL,
                company TEXT NOT NULL,
                year INTEGER NOT NULL,
                month INTEGER,
                content TEXT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(report_type, company, year, month)
            );
        """)
        conn.commit()
        print(f"보고서 데이터베이스 '{REPORTS_DATABASE_FILE}' 및 'reports' 테이블이 성공적으로 초기화되었습니다.")
    except sqlite3.Error as e:
        print(f"보고서 데이터베이스 초기화 중 오류 발생: {e}")
    finally:
        if conn:
            conn.close()

def save_report_to_db(report_type: str, company: str, year: int, content: str, month: int = None):
    """생성된 보고서를 SQLite 데이터베이스에 저장합니다."""
    conn = None
    try:
        conn = sqlite3.connect(REPORTS_DATABASE_FILE)
        cursor = conn.cursor()
        cursor.execute("""
            INSERT OR REPLACE INTO reports (report_type, company, year, month, content)
            VALUES (?, ?, ?, ?, ?)
        """, (report_type, company, year, month, content))
        conn.commit()
    except sqlite3.Error as e:
        print(f"보고서 저장 중 오류 발생: {e}")
    finally:
        if conn:
            conn.close()

def load_reports_from_db(report_type: str, company: str, year: int, month: int = None) -> list:
    """DB에서 특정 조건에 맞는 보고서를 로드합니다."""
    conn = None
    reports = []
    try:
        conn = sqlite3.connect(REPORTS_DATABASE_FILE)
        conn.row_factory = sqlite3.Row  # 컬럼 이름으로 접근 가능하게 설정
        cursor = conn.cursor()
        
        if month:
            cursor.execute("""
                SELECT content FROM reports
                WHERE report_type = ? AND company = ? AND year = ? AND month = ?
            """, (report_type, company, year, month))
        else:
            cursor.execute("""
                SELECT content FROM reports
                WHERE report_type = ? AND company = ? AND year = ?
            """, (report_type, company, year))
            
        rows = cursor.fetchall()
        reports = [dict(row) for row in rows]
        
    except sqlite3.Error as e:
        print(f"보고서 로드 중 오류 발생: {e}")
    finally:
        if conn:
            conn.close()
    return reports

# --- 기타 유틸리티 함수 (기존 코드 유지) ---
@retry(
    wait=wait_exponential(multiplier=1, min=4, max=10),
    stop=stop_after_attempt(10),
    retry=retry_if_exception_type(Exception)
)
def _call_llm_with_retry(chain, inputs):
    """LLM 호출에 재시도 로직을 적용하고 Rate Limit을 관리합니다."""
    global last_call_time
    current_time = time.time()
    elapsed_time = current_time - last_call_time

    if elapsed_time < API_CALL_INTERVAL_SECONDS:
        time.sleep(API_CALL_INTERVAL_SECONDS - elapsed_time)
        
    result = chain.invoke(inputs)
    last_call_time = time.time()
    return result

def _postprocess_report_output(report_content: str) -> str:
    """
    Gemini 모델에서 생성된 보고서 텍스트의 항목 부호 앞에 줄바꿈을 적용합니다.
    """
    processed_text = report_content
    processed_text = processed_text.replace("○ ", "\n  ○ ")
    processed_text = processed_text.replace("- ", "\n    - ")
    processed_text = processed_text.replace("• ", "\n      • ")
    processed_text = processed_text.replace("□ ", "\n□ ")
    
    # 불필요한 줄바꿈 제거
    processed_text = processed_text.replace("\n\n  ○", "\n  ○")
    processed_text = processed_text.replace("\n\n    -", "\n    -")
    processed_text = processed_text.replace("\n\n      •", "\n      •")
    processed_text = processed_text.replace("\n\n□ ", "\n□ ")
    return processed_text.strip()

# --- 페이지 1: 연도별 핵심 이슈 (MapReduce 요약 -> 월별/연간 통합) ---
def _generate_page_1_yearly_issues(query: str, progress_callback=None):
    """
    최신 기사의 최소/최대 연도를 파악하고, 각 연도별로 월별 요약을 만든 후,
    이를 종합하여 최종 연도별 보고서를 생성합니다.
    """
    llm = get_llm_model()

    # DB에 리포트 저장용 테이블 초기화
    initialize_reports_db()

    # 기사 데이터 로드 및 연도 파악
    all_articles = load_articles_from_db()
    if not all_articles:
        message = "데이터베이스에 크롤링된 기사가 없습니다. 먼저 뉴스를 크롤링하고 임베딩하세요."
        if progress_callback:
            progress_callback(message, 0.0, 'warning')
        return f"## 1. 연도별 핵심 이슈\n\n{message}"

    df = pd.DataFrame(all_articles)
    df.columns = ['id', 'title', 'publish_date', 'author', 'content', 'url', 'suitability_score', 'company']
    # st.dataframe(df)

    df['date'] = pd.to_datetime(df['publish_date'], format='%Y-%m-%d', errors = 'coerce')
    df['year'] = df['date'].dt.year
    df['month'] = df['date'].dt.month

    min_year = int(df['year'].min())
    max_year = int(df['year'].max())
    
    if pd.isna(min_year) or pd.isna(max_year):
        message = "기사 데이터에 유효한 연도 정보가 없습니다."
        if progress_callback:
            progress_callback(message, 0.0, 'warning')
        return f"## 1. 연도별 핵심 이슈\n\n{message}"
    else:
        message = f"{min_year}~{max_year}까지 레포트 작성이 가능합니다.."
        time.sleep(3)
        if progress_callback:
            progress_callback(message, 0.0, 'info')

    yearly_report_texts = []
    total_years = max_year - min_year + 1
    yearly_progress_step = 1.0 / total_years if total_years > 0 else 0.0

    for year in range(max_year, min_year - 1, -1):
        year_progress_base = 1 - (max_year - year + 1) / total_years
        
        # 해당 연도의 모든 적합한 기사를 가져옴
        # yearly_articles_df = df[(df['year'] == year) & (df['suitability_score'] == 1)]
        yearly_articles_df = df[(df['year'] == year)]
        
        if yearly_articles_df.empty:
            message = f"[{year}년] 해당 연도에 적합한 기사가 없습니다. 연간 보고서를 건너뜁니다."
            if progress_callback:
                progress_callback(message, year_progress_base, 'info')
            # time.sleep(1)
            continue

        monthly_summaries = []
        for month in range(1, 13):
            month_progress = year_progress_base + (month / 12) * yearly_progress_step
            monthly_articles_df = yearly_articles_df[yearly_articles_df['month'] == month]

            if monthly_articles_df.empty:
                message = f"[{year}년 {month:02d}월] 기사가 없습니다. 건너뜁니다."
                if progress_callback:
                    progress_callback(message, month_progress, 'info')
                # time.sleep(1)
                continue

            # 이전에 생성된 월별 보고서가 있는지 확인하고 있으면 로드
            existing_report = load_reports_from_db(report_type="monthly", company=query, year=year, month=month)
            if existing_report:
                monthly_summaries.append(existing_report[0]['content'])
                message = f"[{year}년 {month:02d}월] 기존 월별 요약 로드 완료."
                if progress_callback:
                    progress_callback(message, month_progress, 'info')
                # time.sleep(1)
                continue

            message = f"[리포트 생성] {year}년 {month:02d}월 월별 핵심 이슈 요약 중..."
            if progress_callback:
                progress_callback(message, month_progress, 'progress')
            # time.sleep(1)
            
            # DataFrame을 리스트 오브 딕셔너리로 변환
            articles_list = monthly_articles_df.to_dict('records')
            
            articles_text = "\n---\n".join([
                f"**제목:** {a['title']}\n**작성일:** {a['publish_date']}\n**기사 본문:** {a['content']}"
                for a in articles_list
            ])
            
            # 외부 파일에서 프롬프트 템플릿 로드
            monthly_prompt = PromptTemplate.from_template(MONTHLY_REPORT_PROMPT)
            monthly_chain = monthly_prompt | llm | StrOutputParser()

            try:
                monthly_report_raw = _call_llm_with_retry(
                    monthly_chain,
                    {'articles': articles_text, 'company': query, 'year': year, 'month': month}
                )
                monthly_report_content = _postprocess_report_output(monthly_report_raw)
                monthly_summaries.append(monthly_report_content)
                save_report_to_db(
                    report_type="monthly",
                    company=query,
                    year=year,
                    month=month,
                    content=monthly_report_content
                )
                if progress_callback:
                    progress_callback(f"[{year}년 {month:02d}월] 월별 요약 완료. DB에 저장.", month_progress, 'info')
                # time.sleep(1)
            except Exception as e:
                message = f"[{year}년 {month:02d}월] 월별 요약 실패: {e}"
                if progress_callback:
                    progress_callback(message, month_progress, 'error')
                continue

        # 해당 연도의 월별 요약 데이터가 있으면 연간 보고서 생성
        if monthly_summaries:
            year_progress_final = year_progress_base + yearly_progress_step # 연간 보고서 시작
            message = f"[리포트 생성] {year}년 연간 핵심 이슈 요약 중..."
            if progress_callback:
                progress_callback(message, year_progress_final - (yearly_progress_step * 0.25), 'progress')
            
            # 이전에 생성된 연간 보고서가 있는지 확인하고 있으면 로드
            existing_yearly_report = load_reports_from_db(report_type="yearly", company=query, year=year)
            if existing_yearly_report:
                yearly_report_texts.append(existing_yearly_report[0]['content'])
                message = f"[{year}년] 기존 연간 보고서 로드 완료."
                if progress_callback:
                    progress_callback(message, year_progress_final, 'info')
                # time.sleep(1)
                continue

            articles_text = "\n---\n".join(monthly_summaries)
            
            # 외부 파일에서 프롬프트 템플릿 로드
            yearly_prompt = PromptTemplate.from_template(YEARLY_REPORT_PROMPT)
            yearly_chain = yearly_prompt | llm | StrOutputParser()

            try:
                yearly_report_raw = _call_llm_with_retry(
                    yearly_chain,
                    {'articles': articles_text, 'company': query, 'year': year}
                )
                yearly_report_content = _postprocess_report_output(yearly_report_raw)
                yearly_report_texts.append(yearly_report_content)
                save_report_to_db(
                    report_type="yearly",
                    company=query,
                    year=year,
                    content=yearly_report_content
                )
                if progress_callback:
                    progress_callback(f"[{year}년] 연간 보고서 생성 완료. DB에 저장.", year_progress_final, 'info')
            except Exception as e:
                message = f"[{year}년] 연간 보고서 생성 실패: {e}"
                if progress_callback:
                    progress_callback(message, year_progress_final, 'error')
                continue
    
    # 생성된 모든 연간 보고서들을 합쳐서 반환
    if not yearly_report_texts:
        return "## 1. 연도별 핵심 이슈\n\n분석할 연간 데이터가 없습니다."
        
    final_page_content = "\n\n---\n\n".join(yearly_report_texts)
    
    return f"## 1. 연도별 핵심 이슈\n\n{final_page_content}"
    # return final_page_content

# --- Helper function to load yearly reports content ---
def _load_yearly_reports_content(company: str, progress_callback=None, database_file=REPORTS_DATABASE_FILE) -> List[str]:
    """
    데이터베이스에서 특정 회사에 대한 모든 'yearly' 보고서의 내용을 불러옵니다.
    최신 연도부터 정렬하여 반환합니다.
    """
    conn = None
    yearly_reports_content = []
    try:
        conn = sqlite3.connect(REPORTS_DATABASE_FILE)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT content FROM reports
            WHERE report_type = 'yearly' AND company = ?
            ORDER BY year DESC
        """, (company,))
        
        rows = cursor.fetchall()
        yearly_reports_content = [row['content'] for row in rows]
        
    except sqlite3.Error as e:
        error_message = f"데이터베이스에서 연간 보고서 로드 중 오류 발생: {e}"
        print(error_message)
        if progress_callback:
            progress_callback(error_message, 0.0, 'error')
        return []
    finally:
        if conn:
            conn.close()
    return yearly_reports_content

def _generate_page_2_keyword_summary(query: str, progress_callback=None):
    """
    데이터베이스에서 모든 연간 보고서를 로드하여 핵심 키워드를 기반으로 요약 보고서를 생성합니다.
    이미 생성된 보고서가 있다면 해당 보고서를 반환합니다.
    """
    llm = get_llm_model()
    initialize_reports_db()

    # Check if the report already exists in the database for the current year
    current_year = datetime.datetime.now().year
    existing_report_content = load_reports_from_db(
        report_type="keyword",
        company=query,
        year=current_year
    )
    
    if existing_report_content:
        message = f"'{query}'에 대한 핵심 키워드 요약 보고서가 이미 생성되어 있습니다. 기존 보고서를 로드합니다."
        if progress_callback:
            progress_callback(message, 1.0, 'info')
        time.sleep(1)
        return f"## 2. 핵심 키워드 요약\n\n{existing_report_content}"

    # 헬퍼 함수를 사용하여 연간 보고서 내용 불러오기
    yearly_reports_content = _load_yearly_reports_content(query, progress_callback)
    
    if not yearly_reports_content:
        message = "생성된 연간 보고서가 없습니다. 먼저 연간 보고서를 생성해야 키워드 요약을 진행할 수 있습니다."
        if progress_callback:
            progress_callback(message, 0.0, 'warning')
        return f"## 2. 핵심 키워드 요약\n\n{message}"

    combined_reports_text = "\n\n---\n\n".join(yearly_reports_content)

    message = f"[리포트 생성] '{query}'에 대한 핵심 키워드 요약 생성 중..."
    if progress_callback:
        progress_callback(message, 0.5, 'progress')
    
    # 외부 파일에서 프롬프트 템플릿 로드
    keyword_summary_prompt = PromptTemplate.from_template(KEYWORD_SUMMARY_PROMPT)
    keyword_summary_chain = keyword_summary_prompt | llm | StrOutputParser()

    try:
        keyword_summary_raw = _call_llm_with_retry(
            keyword_summary_chain,
            {'company': query, 'annual_reports': combined_reports_text}
        )
        keyword_summary_content = _postprocess_report_output(keyword_summary_raw)
        
        # 키워드 요약 보고서를 DB에 저장
        save_report_to_db(
            report_type="keyword",
            company=query,
            year=current_year, 
            month=None,
            content=keyword_summary_content
        )
        if progress_callback:
            progress_callback(f"'{query}'에 대한 핵심 키워드 요약 완료. DB에 저장.", 1.0, 'info')
        
        return f"## 2. 핵심 키워드 요약\n\n{keyword_summary_content}"

    except Exception as e:
        message = f"핵심 키워드 요약 생성 실패: {e}"
        if progress_callback:
            progress_callback(message, 1.0, 'error')
        return f"## 2. 핵심 키워드 요약\n\n{message}"


def _generate_page_3_company_trend_analysis(query: str, progress_callback=None):
    """
    데이터베이스에서 모든 연간 보고서를 로드하고, 이를 바탕으로 기업의 주요 트렌드를 분석하는 보고서를 생성합니다.
    이미 생성된 보고서가 있다면 해당 보고서를 반환합니다.
    """
    llm = get_llm_model()
    initialize_reports_db()

    # Check if the report already exists in the database for the current year
    current_year = datetime.datetime.now().year
    existing_report_content = load_reports_from_db(
        report_type="trend",
        company=query,
        year=current_year
    )
    
    if existing_report_content:
        message = f"'{query}'에 대한 기업 트렌드 분석 보고서가 이미 생성되어 있습니다. 기존 보고서를 로드합니다."
        if progress_callback:
            progress_callback(message, 1.0, 'info')
        time.sleep(1)
        return f"## 3. 기업 트렌드 분석\n\n{existing_report_content}"

    # 헬퍼 함수를 사용하여 연간 보고서 내용 불러오기
    yearly_reports_content = _load_yearly_reports_content(query, progress_callback)
    
    if not yearly_reports_content:
        message = "생성된 연간 보고서가 없습니다. 먼저 연간 보고서를 생성해야 기업 트렌드 분석을 진행할 수 있습니다."
        if progress_callback:
            progress_callback(message, 0.0, 'warning')
        return f"## 3. 기업 트렌드 분석\n\n{message}"

    combined_reports_text = "\n\n---\n\n".join(yearly_reports_content)

    message = f"[리포트 생성] '{query}'에 대한 기업 트렌드 분석 보고서 생성 중..."
    if progress_callback:
        progress_callback(message, 0.5, 'progress')

    # 외부 파일에서 프롬프트 템플릿 로드
    company_trend_analysis_prompt = PromptTemplate.from_template(COMPANY_TREND_ANALYSIS_PROMPT)
    company_trend_analysis_chain = company_trend_analysis_prompt | llm | StrOutputParser()

    try:
        company_trend_analysis_raw = _call_llm_with_retry(
            company_trend_analysis_chain,
            {'company': query, 'annual_reports': combined_reports_text}
        )
        company_trend_analysis_content = _postprocess_report_output(company_trend_analysis_raw)
        
        # 기업 트렌드 분석 보고서를 DB에 저장
        save_report_to_db(
            report_type="trend",
            company=query,
            year=current_year, 
            month=None,
            content=company_trend_analysis_content
        )
        if progress_callback:
            progress_callback(f"'{query}'에 대한 기업 트렌드 분석 보고서 완료. DB에 저장.", 1.0, 'info')
        
        return f"## 3. 기업 트렌드 분석\n\n{company_trend_analysis_content}"

    except Exception as e:
        message = f"기업 트렌드 분석 보고서 생성 실패: {e}"
        if progress_callback:
            progress_callback(message, 1.0, 'error')
        return f"## 3. 기업 트렌드 분석\n\n{message}"


