# async_report_generator.py
import os
import time
import datetime
import re
import asyncio
from typing import List, Dict, Any, Optional
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
from langchain_openai import ChatOpenAI  # <-- 이 부분을 ChatOpenAI로 변경

# data_manager 모듈에서 기사 로드 함수를 비동기 버전으로 임포트
from async_data_manager import (
    load_articles_from_db,
    save_report_to_db,
    initialize_reports_db,
    load_reports_from_db
)

# 새롭게 분리한 프롬프트 파일을 임포트
from prompts import MONTHLY_REPORT_PROMPT, YEARLY_REPORT_PROMPT, KEYWORD_SUMMARY_PROMPT, COMPANY_TREND_ANALYSIS_PROMPT


try:
    __import__('pysqlite3')
    import sys
    import pysqlite3 as sqlite3

    sys.modules['sqlite3'] = sys.modules.pop('pysqlite3')
    print("Using pysqlite3 library.")
except ImportError:
    # Fallback to standard sqlite3 if pysqlite3 is not available
    import sqlite3
    print("Could not import pysqlite3, falling back to sqlite3.") 

# .env 파일 로드
load_dotenv()

# LangSmith 설정 (수정됨)
if os.getenv("LANGSMITH_API_KEY"):
    os.environ["LANGSMITH_TRACING_V2"] = "true"
else:
    print("경고: LangSmith API 키가 설정되지 않아 LangSmith 트레이싱이 비활성화됩니다.")

# Google API 키 확인
if not os.getenv("GOOGLE_API_KEY"):
    raise ValueError("GOOGLE_API_KEY 환경 변수가 설정되어 있지 않습니다.")

if not os.getenv("OPENAI_API_KEY"):
    raise ValueError("OPENAI_API_KEY 환경 변수가 설정되어 있지 않습니다.")


# API 호출 제한 관리 (1분에 60회)
MAX_CALLS_PER_MINUTE = 10
API_CALL_INTERVAL_SECONDS = 60.0 / MAX_CALLS_PER_MINUTE
last_call_time = 0

# --- LLM 모델 초기화 ---
# @st.cache_resource
# def get_llm_model():
#     return ChatGoogleGenerativeAI(model="gemini-2.5-flash-lite", temperature=0.1)

@st.cache_resource
def get_llm_model():
    return ChatOpenAI(model="gpt-4o-mini", temperature=0.1) # <-- 모델과 temperature를 설정

# --- 기타 유틸리티 함수 ---
@retry(
    wait=wait_exponential(multiplier=1, min=4, max=10),
    stop=stop_after_attempt(10),
    retry=retry_if_exception_type(Exception)
)
async def _call_llm_with_ainvoke(chain, inputs):
    global last_call_time
    current_time = time.time()
    elapsed_time = current_time - last_call_time

    if elapsed_time < API_CALL_INTERVAL_SECONDS:
        await asyncio.sleep(API_CALL_INTERVAL_SECONDS - elapsed_time)
        
    result = await chain.ainvoke(inputs)
    last_call_time = time.time()
    return result

def _postprocess_report_output(content: str) -> str:
    processed_text = content
    processed_text = processed_text.replace("○ ", "\n  ○ ")
    processed_text = processed_text.replace("- ", "\n    - ")
    processed_text = processed_text.replace("• ", "\n      • ")
    processed_text = processed_text.replace("□ ", "\n□ ")
    
    processed_text = processed_text.replace("\n\n  ○", "\n  ○")
    processed_text = processed_text.replace("\n\n    -", "\n    -")
    processed_text = processed_text.replace("\n\n      •", "\n      •")
    processed_text = processed_text.replace("\n\n□ ", "\n□ ")
    return processed_text.strip()

# --- 페이지 1: 연도별 핵심 이슈 ---
async def _generate_page_1_yearly_issues(query: str, username: str, progress_callback=None):
    llm = get_llm_model()
    await initialize_reports_db()

    all_articles = await load_articles_from_db(username=username)
    if not all_articles:
        message = "데이터베이스에 크롤링된 기사가 없습니다. 먼저 뉴스를 크롤링하고 임베딩하세요."
        if progress_callback:
            progress_callback(message, 0.0, 'warning')
        return f"## 1. 연도별 핵심 이슈\n\n{message}"

    df = pd.DataFrame(all_articles)
    df.columns = ['id', 'username', 'title', 'publish_date', 'author', 'content', 'url', 'suitability_score', 'company']

    df['date'] = pd.to_datetime(df['publish_date'], format='%Y-%m-%d', errors='coerce')
    df = df.dropna(subset=['date'])

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
        message = f"{min_year}~{max_year}까지 레포트 작성이 가능합니다."
        if progress_callback:
            progress_callback(message, 0.0, 'info')

    yearly_report_texts = {}
    
    monthly_tasks = []
    for year in range(min_year, max_year + 1):
        yearly_articles_df = df[(df['year'] == year) & (df['company'] == query)& (df['username'] == username)]
        if yearly_articles_df.empty:
            continue

        for month in range(1, 13):
            monthly_articles_df = yearly_articles_df[yearly_articles_df['month'] == month]
            if monthly_articles_df.empty:
                continue
            
            existing_reports = await load_reports_from_db(
                username=username, report_type="monthly", query=query, year=year, month=month
            )
            if existing_reports:
                monthly_content = existing_reports[0]['content']
                monthly_tasks.append(
                    asyncio.create_task(
                        asyncio.to_thread(lambda: (year, month, monthly_content))
                    )
                )
            else:
                articles_text = "\n---\n".join([
                    f"**제목:** {a['title']}\n**작성일:** {a['publish_date']}\n**기사 본문:** {a['content']}"
                    for _, a in monthly_articles_df.iterrows()
                ])
                monthly_tasks.append(
                    _async_generate_monthly_report_task(llm, query, year, month, articles_text, username)
                )

    if not monthly_tasks:
        message = "분석할 월별 데이터가 없습니다."
        if progress_callback:
            progress_callback(message, 1.0, 'warning')
        return f"## 1. 연도별 핵심 이슈\n\n{message}"

    monthly_results = await asyncio.gather(*monthly_tasks)
    monthly_summaries = {}
    for result in monthly_results:
        year, month, content = result
        if year not in monthly_summaries:
            monthly_summaries[year] = []
        monthly_summaries[year].append(content)
        
    yearly_tasks = []
    for year in range(min_year, max_year + 1):
        if year in monthly_summaries:
            existing_reports = await load_reports_from_db(
                username=username, report_type="yearly", query=query, year=year
            )
            if existing_reports:
                yearly_report_texts[year] = existing_reports[0]['content']
            else:
                combined_monthly_content = "\n---\n".join(monthly_summaries[year])
                yearly_tasks.append(
                    _async_generate_yearly_report_task(llm, query, year, combined_monthly_content, username)
                )

    yearly_results = await asyncio.gather(*yearly_tasks)
    for result in yearly_results:
        year, content = result
        yearly_report_texts[year] = content

    if not yearly_report_texts:
        return "## 1. 연도별 핵심 이슈\n\n분석할 연간 데이터가 없습니다."
        
    final_page_content = "\n\n---\n\n".join([
        yearly_report_texts[year] for year in sorted(yearly_report_texts.keys(), reverse=True)
    ])
    
    if progress_callback:
        progress_callback(f"연간 핵심 이슈 보고서 생성 완료.", 1.0, 'info')

    return f"## 1. 연도별 핵심 이슈\n\n{final_page_content}"

async def _async_generate_monthly_report_task(llm, query, year, month, articles_text, username):
    monthly_prompt = PromptTemplate.from_template(MONTHLY_REPORT_PROMPT)
    monthly_chain = monthly_prompt | llm | StrOutputParser()
    try:
        monthly_report_raw = await _call_llm_with_ainvoke(
            monthly_chain,
            {'articles': articles_text, 'company': query, 'year': year, 'month': month}
        )
        monthly_content = _postprocess_report_output(monthly_report_raw)
        await save_report_to_db(
            username=username, report_type="monthly", query=query, year=year, month=month, content=monthly_content
        )
        return (year, month, monthly_content)
    except Exception as e:
        print(f"월별 보고서 생성 실패 ({year}-{month}): {e}")
        return (year, month, f"보고서 생성 실패: {e}")

async def _async_generate_yearly_report_task(llm, query, year, combined_monthly_content, username):
    yearly_prompt = PromptTemplate.from_template(YEARLY_REPORT_PROMPT)
    yearly_chain = yearly_prompt | llm | StrOutputParser()
    try:
        yearly_report_raw = await _call_llm_with_ainvoke(
            yearly_chain,
            {'articles': combined_monthly_content, 'company': query, 'year': year}
        )
        yearly_content = _postprocess_report_output(yearly_report_raw)
        await save_report_to_db(
            username=username, report_type="yearly", query=query, year=year, content=yearly_content
        )
        return (year, yearly_content)
    except Exception as e:
        print(f"연간 보고서 생성 실패 ({year}): {e}")
        return (year, f"보고서 생성 실패: {e}")

# --- Helper function to load yearly reports content (비동기 버전) ---
async def _load_yearly_reports_content(company: str, username: str, progress_callback=None) -> List[str]:
    reports = await load_reports_from_db(username=username, report_type="yearly", query=company)
    reports.sort(key=lambda x: x['year'], reverse=True)
    return [report['content'] for report in reports]

# --- 페이지 2: 핵심 키워드 요약 (비동기 적용) ---
async def _generate_page_2_keyword_summary(query: str, username: str, progress_callback=None):
    llm = get_llm_model()
    await initialize_reports_db()

    current_year = datetime.datetime.now().year
    existing_reports = await load_reports_from_db(
        username=username, report_type="keyword", query=query, year=current_year
    )
    
    if existing_reports:
        message = f"'{query}'에 대한 핵심 키워드 요약 보고서가 이미 생성되어 있습니다. 기존 보고서를 로드합니다."
        if progress_callback:
            progress_callback(message, 1.0, 'info')
        return f"## 2. 핵심 키워드 요약\n\n{existing_reports[0]['content']}"

    yearly_reports_content = await _load_yearly_reports_content(query, username, progress_callback)
    
    if not yearly_reports_content:
        message = "생성된 연간 보고서가 없습니다. 먼저 연간 보고서를 생성해야 키워드 요약을 진행할 수 있습니다."
        if progress_callback:
            progress_callback(message, 0.0, 'warning')
        return f"## 2. 핵심 키워드 요약\n\n{message}"

    combined_reports_text = "\n\n---\n\n".join(yearly_reports_content)

    message = f"[리포트 생성] '{query}'에 대한 핵심 키워드 요약 생성 중..."
    if progress_callback:
        progress_callback(message, 0.5, 'progress')
    
    keyword_summary_prompt = PromptTemplate.from_template(KEYWORD_SUMMARY_PROMPT)
    keyword_summary_chain = keyword_summary_prompt | llm | StrOutputParser()

    try:
        keyword_summary_raw = await _call_llm_with_ainvoke(
            keyword_summary_chain,
            {'company': query, 'annual_reports': combined_reports_text}
        )
        keyword_summary_content = _postprocess_report_output(keyword_summary_raw)
        
        await save_report_to_db(
            username=username, report_type="keyword", query=query, year=current_year, content=keyword_summary_content
        )
        
        if progress_callback:
            progress_callback(f"'{query}'에 대한 핵심 키워드 요약 완료. DB에 저장.", 1.0, 'info')
        
        return f"## 2. 핵심 키워드 요약\n\n{keyword_summary_content}"

    except Exception as e:
        message = f"핵심 키워드 요약 생성 실패: {e}"
        if progress_callback:
            progress_callback(message, 1.0, 'error')
        return f"## 2. 핵심 키워드 요약\n\n{message}"

# --- 페이지 3: 기업 트렌드 분석 (비동기 적용) ---
async def _generate_page_3_company_trend_analysis(query: str, username: str, progress_callback=None):
    llm = get_llm_model()
    await initialize_reports_db()

    current_year = datetime.datetime.now().year
    existing_reports = await load_reports_from_db(
        username=username, report_type="trend", query=query, year=current_year
    )
    
    if existing_reports:
        message = f"'{query}'에 대한 기업 트렌드 분석 보고서가 이미 생성되어 있습니다. 기존 보고서를 로드합니다."
        if progress_callback:
            progress_callback(message, 1.0, 'info')
        return f"## 3. 기업 트렌드 분석\n\n{existing_reports[0]['content']}"

    yearly_reports_content = await _load_yearly_reports_content(query, username, progress_callback)
    
    if not yearly_reports_content:
        message = "생성된 연간 보고서가 없습니다. 먼저 연간 보고서를 생성해야 기업 트렌드 분석을 진행할 수 있습니다."
        if progress_callback:
            progress_callback(message, 0.0, 'warning')
        return f"## 3. 기업 트렌드 분석\n\n{message}"

    combined_reports_text = "\n\n---\n\n".join(yearly_reports_content)

    message = f"[리포트 생성] '{query}'에 대한 기업 트렌드 분석 보고서 생성 중..."
    if progress_callback:
        progress_callback(message, 0.5, 'progress')

    company_trend_analysis_prompt = PromptTemplate.from_template(COMPANY_TREND_ANALYSIS_PROMPT)
    company_trend_analysis_chain = company_trend_analysis_prompt | llm | StrOutputParser()

    try:
        company_trend_analysis_raw = await _call_llm_with_ainvoke(
            company_trend_analysis_chain,
            {'company': query, 'annual_reports': combined_reports_text}
        )
        company_trend_analysis_content = _postprocess_report_output(company_trend_analysis_raw)
        
        await save_report_to_db(
            username=username, report_type="trend", query=query, year=current_year, content=company_trend_analysis_content
        )
        
        if progress_callback:
            progress_callback(f"'{query}'에 대한 기업 트렌드 분석 보고서 완료. DB에 저장.", 1.0, 'info')
        
        return f"## 3. 기업 트렌드 분석\n\n{company_trend_analysis_content}"

    except Exception as e:
        message = f"기업 트렌드 분석 보고서 생성 실패: {e}"
        if progress_callback:
            progress_callback(message, 1.0, 'error')
        return f"## 3. 기업 트렌드 분석\n\n{message}"

# 모듈 단독 실행 시 테스트 코드
if __name__ == '__main__':
    test_query = "한화에어로스페이스"
    test_username = "이승용"

    async def main():
        def test_progress_callback(message, progress_val, status):
            print(f"Status: {message} | Progress: {progress_val*100:.1f}% | Status: {status}")

        print(f"\n--- 연도별 핵심 이슈 분석 보고서 생성 테스트 (사용자: {test_username}) ---")
        yearly_report = await _generate_page_1_yearly_issues(test_query, test_username, test_progress_callback)
        print(yearly_report)

        print(f"\n--- 핵심 키워드 요약 보고서 생성 테스트 (사용자: {test_username}) ---")
        keyword_summary_report = await _generate_page_2_keyword_summary(test_query, test_username, test_progress_callback)
        print(keyword_summary_report)

        print(f"\n--- 기업 트렌드 분석 보고서 생성 테스트 (사용자: {test_username}) ---")
        company_trend_report = await _generate_page_3_company_trend_analysis(test_query, test_username, test_progress_callback)
        print(company_trend_report)

    asyncio.run(main())