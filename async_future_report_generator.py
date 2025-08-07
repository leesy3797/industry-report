# __import__('pysqlite3')
# import sys
# sys.modules['sqlite3'] = sys.modules.pop('pysqlite3')

import datetime
import os
import re
import hashlib
import time
import asyncio 
from typing import List, Optional
import sqlite3
from tenacity import retry, stop_after_attempt, wait_exponential, RetryError
from dotenv import load_dotenv
from langchain_google_genai import GoogleGenerativeAIEmbeddings
from langchain_openai import ChatOpenAI, OpenAIEmbeddings

from langchain.prompts import PromptTemplate
from langchain_core.output_parsers import StrOutputParser

from langchain_chroma.vectorstores import Chroma
from langchain_community.utilities import GoogleSerperAPIWrapper
from langchain.schema import Document
from langchain_community.document_loaders import UnstructuredURLLoader
import asyncio 
from langchain_text_splitters import RecursiveCharacterTextSplitter
import requests

# 외부 모듈에서 필요한 함수 임포트 (원본 코드에서 가져옴)
# 이 파일 외부에 정의되어 있다고 가정합니다.
from prompts import FUTURE_STRATEGY_ROADMAP_PROMPT
from async_report_generator import get_llm_model, initialize_reports_db, save_report_to_db, load_reports_from_db, _postprocess_report_output

load_dotenv() 

# --- 헬퍼 함수 정의 ---

def _mock_progress_callback(message, progress, status):
    """
    progress_callback이 제공되지 않았을 경우 사용되는 mock 함수
    """
    print(f"📊 [Progress: {int(progress*100)}%] {status.upper()}: {message}")

@retry(stop=stop_after_attempt(5), wait=wait_exponential(multiplier=1, min=4, max=30))
async def _get_serper_results_with_retry(serper_search_tool, query_string: str, company_name: str, username: str, num_results=10) -> List[Document]:
    """
    Serper API를 사용하여 검색을 수행하고, 각 결과의 링크를 통해 원본 웹 페이지 콘텐츠를 가져와
    LangChain Document 객체 리스트로 반환합니다.
    """
    print(f"  [Serper 검색] '{query_string}' (상위 {num_results}개 결과)")
    
    results = serper_search_tool.results(query_string) 
    
    extracted_docs = []
    processed_links = set() 

    if 'organic' in results:
        for organic_result in results['organic']:
            link = organic_result.get('link')
            title = organic_result.get('title', 'N/A')
            snippet = organic_result.get('snippet', 'N/A')

            if link and link not in processed_links:
                try:
                    res = requests.get(link, timeout = 10)
                    loader = UnstructuredURLLoader(urls=[link])
                    documents = await loader.aload() 
                    
                    if documents and documents[0].page_content:
                        full_content = documents[0].page_content
                        full_content = re.sub(r'\s+', ' ', full_content).strip()
                        if len(full_content) < 100:
                            continue
                        
                        page_content = f"{full_content}"
                        metadata = {
                            "source": link,
                            "title": title,
                            "position": organic_result.get('position', -1),
                            "query_origin": query_string,
                            "fetched_type": "full_content",
                            "company_name": company_name,
                            "username": username  # ✅ 메타데이터에 username 추가
                        }
                        extracted_docs.append(Document(page_content=page_content, metadata=metadata))
                        processed_links.add(link)
                    else:
                        if len(snippet) > 50:
                            page_content = f"제목: {title}\n내용: {snippet} (원본 로드 실패)"
                            print(f"  (원본 로드 실패) 검색어: {query_string} URL: {link}")
                            metadata = {
                                "source": link, "title": title, "position": organic_result.get('position', -1),
                                "query_origin": query_string, "fetched_type": "snippet_fallback",
                                "company_name": company_name,
                                "username": username  # ✅ 메타데이터에 username 추가
                            }
                            extracted_docs.append(Document(page_content=page_content, metadata=metadata))
                except Exception as e:
                    if len(snippet) > 50:
                        page_content = f"제목: {title}\n내용: {snippet} (원본 로드 실패)"
                        print(f"  (원본 로드 실패) 검색어: {query_string} URL: {link}")
                        metadata = {
                            "source": link, "title": title, "position": organic_result.get('position', -1),
                            "query_origin": query_string, "fetched_type": "snippet_fallback",
                            "company_name": company_name,
                            "username": username  # ✅ 메타데이터에 username 추가
                        }
                        extracted_docs.append(Document(page_content=page_content, metadata=metadata))
            else:
                if len(snippet) > 50:
                    page_content = f"제목: {title}\n내용: {snippet} (링크 없거나 중복)"
                    metadata = {
                        "source": link if link else "N/A", "title": title, "position": organic_result.get('position', -1),
                        "query_origin": query_string, "fetched_type": "snippet_only",
                        "company_name": company_name,
                        "username": username  # ✅ 메타데이터에 username 추가
                    }
                    extracted_docs.append(Document(page_content=page_content, metadata=metadata))

    # AnswerBox, KnowledgeGraph 등 스니펫 정보 추가
    if 'answerBox' in results and 'snippet' in results['answerBox']:
        ab_content = re.sub(r'\s+', ' ', results['answerBox']['snippet']).strip()
        page_content = f"AnswerBox 제목: {results['answerBox'].get('title', 'N/A')}\n내용: {ab_content}"
        metadata = {"source": results['answerBox'].get('link', 'N/A'), "title": results['answerBox'].get('title', 'N/A') or "Answer Box", "query_origin": query_string, "fetched_type": "answer_box_snippet", "company_name": company_name, "username": username} # ✅ 메타데이터에 username 추가
        extracted_docs.append(Document(page_content=page_content, metadata=metadata))
    
    if 'knowledgeGraph' in results and 'snippet' in results['knowledgeGraph']:
        kg_content = re.sub(r'\s+', ' ', results['knowledgeGraph']['snippet']).strip()
        page_content = f"KnowledgeGraph 제목: {results['knowledgeGraph'].get('title', 'N/A')}\n내용: {kg_content}"
        metadata = {"source": results['knowledgeGraph'].get('link', 'N/A'), "title": results['knowledgeGraph'].get('title', 'N/A') or "Knowledge Graph", "query_origin": query_string, "fetched_type": "knowledge_graph_snippet", "company_name": company_name, "username": username} # ✅ 메타데이터에 username 추가
        extracted_docs.append(Document(page_content=page_content, metadata=metadata))

    return extracted_docs


async def _generate_page_4_future_report(query: str, username: str, progress_callback=None, perform_serper_search: bool = True) -> str:
    """
    주어진 회사(query)에 대한 미래 전략 로드맵 보고서를 생성합니다.
    - 웹 검색을 통해 최신 정보를 수집합니다. (perform_serper_search가 True일 경우)
    - 수집된 문서를 벡터스토어에 저장하고 관련성 높은 문서를 선별합니다.
    - 선별된 문서를 기반으로 LLM을 호출하여 보고서를 작성합니다.
    - 최종 보고서를 DB에 저장하고 반환합니다.
    
    Args:
        query (str): 분석할 회사 이름.
        username (str): 보고서를 요청한 사용자 이름.
        progress_callback (callable, optional): 진행 상황을 알리는 콜백 함수.
                                                (message, progress, status) 형태.
        perform_serper_search (bool): Serper 검색을 수행할지 여부. False이면 기존 DB에서만 검색.
    Returns:
        str: 생성된 보고서 내용.
    """
    if progress_callback is None:
        progress_callback = _mock_progress_callback

    report_type = "future"
    current_year = datetime.datetime.now().year

    progress_callback(f"'{query}'에 대한 미래 전략 로드맵 보고서 생성 준비 중...", 0.1, 'progress')
    
    try:
        # 1. LLM 및 DB 초기화
        llm = get_llm_model() 
        await initialize_reports_db()

        # 2. DB에서 기존 보고서 확인
        existing_report_content = await load_reports_from_db(
            username=username, report_type=report_type, query=query, year=current_year
        )
        if existing_report_content:
            progress_callback(f"✅ '{query}'에 대한 기존 보고서가 발견되었습니다. 기존 보고서를 로드합니다.", 1.0, 'info')
            return existing_report_content

        progress_callback(f"👍 기존 보고서를 찾을 수 없습니다. 새로운 보고서를 생성합니다.", 0.15, 'info')

        # 3. Serper API 및 벡터스토어 초기화
        serper_search = GoogleSerperAPIWrapper(
            gl='kr', hl='ko', serper_api_key=os.environ['SERPER_API_KEY']
        )
        vectorstore = Chroma(
            collection_name='future_report_search',
            # embedding_function=GoogleGenerativeAIEmbeddings(
            #     model='models/text-embedding-004',
            #     api_key=os.environ['GOOGLE_API_KEY']
            # ),
            embedding_function = OpenAIEmbeddings(
                model="text-embedding-3-small",
            ),
            persist_directory="./chroma_db"
        )
        progress_callback("✅ 검색 도구 및 벡터스토어 초기화 완료.", 0.2, 'progress')

        raw_serper_docs_for_vectorstore: List[Document] = []

        # 🚀 Serper 검색 조건부 실행
        if perform_serper_search:
            progress_callback(f"🔎 Serper 검색을 시작합니다.", 0.25, 'progress')
            search_queries = [
                f"{query}의 미래 전략", 
                f"{query}의 신사업 동향",
                f"{query}의 미래 먹거리",
                f"{query}의 미래 신사업"
            ]
            progress_callback(f"🔎 사전 정의된 검색 쿼리 ({len(search_queries)}개)를 사용합니다.", 0.25, 'progress')
            
            seen_serper_doc_hashes = set() # 중복 문서 방지를 위한 집합

            for i, search_q in enumerate(search_queries):
                current_progress = 0.25 + (0.35 * ((i + 1) / len(search_queries)))
                progress_callback(f"🔍 검색 쿼리 실행 중 ({i+1}/{len(search_queries)}): '{search_q}'", current_progress, 'progress')
                try:
                    docs_for_query = await _get_serper_results_with_retry(serper_search, search_q, query, username) # ✅ username 전달
                    for doc in docs_for_query:
                        doc_hash = hashlib.sha256(doc.page_content.encode('utf-8')).hexdigest() 
                        if doc_hash not in seen_serper_doc_hashes:
                            raw_serper_docs_for_vectorstore.append(doc)
                            seen_serper_doc_hashes.add(doc_hash)
                except (RetryError, Exception) as e:
                    progress_callback(f"오류: '{search_q}' 검색 실패: {e}", current_progress, 'warning')
                    continue

            if not raw_serper_docs_for_vectorstore:
                progress_callback(f"⚠️ '{query}'에 대한 새로운 웹 검색 결과가 없습니다. 기존 벡터스토어에서 검색을 시도합니다.", 0.6, 'warning')
            else:
                progress_callback(f"✅ 총 {len(raw_serper_docs_for_vectorstore)}개의 고유한 검색 결과 수집 완료.", 0.6, 'progress')

                # 5. 문서 분할 및 벡터스토어 저장 (새로운 문서만 추가)
                text_splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=100)
                unique_docs_splits = text_splitter.split_documents(raw_serper_docs_for_vectorstore)
                
                # ChromaDB에 추가하기 전에 현재 DB에 이미 존재하는 ID를 필터링
                current_db_ids = set(vectorstore.get(
                    where={"$and": [{"company_name": query}, {"username": username}]}, 
                    include=['metadatas']
                )['ids']) 
                documents_to_add = []
                ids_to_add = []
                
                for doc in unique_docs_splits:
                    # 문서 내용과 소스를 기반으로 고유 ID 생성
                    doc_id = hashlib.sha256(f"{doc.metadata.get('source', '')}_{doc.page_content}".encode('utf-8')).hexdigest()
                    if doc_id not in current_db_ids: # 🚀 이미 DB에 없는 ID만 추가
                        # metadata에 username이 있는지 확인 후 추가
                        if "username" not in doc.metadata:
                            doc.metadata["username"] = username
                        documents_to_add.append(doc)
                        ids_to_add.append(doc_id)
                
                if documents_to_add:
                    progress_callback(f"📦 중복을 제외하고 {len(documents_to_add)}개의 새로운 청크를 벡터스토어에 저장 중...", 0.65, 'progress')
                    batch_size = 80
                    for i in range(0, len(documents_to_add), batch_size):
                        vectorstore.add_documents(
                            documents=documents_to_add[i : i + batch_size],
                            ids=ids_to_add[i : i + batch_size]
                        )
                        await asyncio.sleep(10) # 대량 추가 후 ChromaDB의 안정성을 위해 잠시 대기
                    progress_callback("✅ 새로운 검색 결과 벡터스토어 저장 완료.", 0.7, 'progress')
                else:
                    progress_callback("ℹ️ 새로운 검색 결과 중 벡터스토어에 추가할 문서가 없습니다 (모두 중복).", 0.7, 'info')
        else:
            progress_callback("⏭️ Serper 검색 단계가 비활성화되었습니다. 기존 벡터스토어에서 정보를 가져옵니다.", 0.6, 'info')

        # 6. 벡터스토어에서 관련도 높은 문서 검색
        # company_name 메타데이터를 사용하여 필터링
        retriever = vectorstore.as_retriever(
            search_type="mmr", 
            search_kwargs={
                "k": 20,
                "filter": {"$and": [{"company_name": query}, {"username": username}]} # ✅ 필터에 $and 연산자 추가
            }
        )
        query_statement = f"{query}의 현재 역량, 미래 성장 동력, 기술 로드맵, 장기적인 시장 포지셔닝 및 사업 포트폴리오 다각화 전략에 대한 통찰력 있는 분석 자료"
        retrieved_docs = retriever.invoke(query_statement) 
        
        if not retrieved_docs:
            raise ValueError(f"⚠️ '{query}'에 대한 관련성 높은 문서를 벡터스토어에서 찾지 못했습니다. Serper 검색이 비활성화되었거나 기존 데이터가 부족할 수 있습니다.")
        
        context_data = "\n\n".join([doc.page_content for doc in retrieved_docs])
        progress_callback(f"✅ 관련성 높은 문서 {len(retrieved_docs)}개 선별 완료.", 0.8, 'progress')
        
        # 7. LLM을 통해 보고서 생성
        future_roadmap_prompt = PromptTemplate.from_template(FUTURE_STRATEGY_ROADMAP_PROMPT)
        future_roadmap_chain = future_roadmap_prompt | llm | StrOutputParser()
        roadmap_raw = future_roadmap_chain.invoke(
            {'company': query, 'context': context_data}
        )
        roadmap_content = _postprocess_report_output(roadmap_raw)

        # 8. 생성된 보고서를 DB에 저장
        await save_report_to_db( 
            username=username, report_type=report_type, query=query, year=current_year, month=None, content=roadmap_content # ✅ username 전달
        )
        
        progress_callback(f"🎉 '{query}'에 대한 미래 전략 로드맵 보고서 생성 및 DB 저장 완료.", 1.0, 'info')
        return roadmap_content

    except Exception as e:
        message = f"❌ 보고서 생성 실패: {e}"
        progress_callback(message, 1.0, 'error')
        print(message)
        return message

if __name__ == '__main__':
    test_query = "cj대한통운"
    test_user_a = "이승용" # ✅ 사용자 A
    # test_user_b = "user_b" # ✅ 사용자 B
    
    # 🚀 첫 번째 실행: Serper 검색 수행 (user_a를 위한 새로운 데이터 수집)
    print(f"\n--- 첫 번째 실행: '{test_query}' for '{test_user_a}' (Serper 검색 포함) ---")
    final_report_first_run = asyncio.run(_generate_page_4_future_report(test_query, username=test_user_a, perform_serper_search=True))
    print("\n--- 첫 번째 실행 최종 보고서 ---")
    print(final_report_first_run)

    # 🚀 두 번째 실행: Serper 검색 건너뛰기 (user_a의 기존 DB에서 검색)
    print(f"\n--- 두 번째 실행: '{test_query}' for '{test_user_a}' (Serper 검색 건너뛰고 기존 DB 사용) ---")
    final_report_second_run = asyncio.run(_generate_page_4_future_report(test_query, username=test_user_a, perform_serper_search=False))
    print("\n--- 두 번째 실행 최종 보고서 ---")
    print(final_report_second_run)
    
    # # 🚀 세 번째 실행: Serper 검색 수행 (user_b를 위한 새로운 데이터 수집)
    # print(f"\n--- 세 번째 실행: '{test_query}' for '{test_user_b}' (Serper 검색 포함) ---")
    # final_report_third_run = asyncio.run(_generate_page_4_future_report(test_query, username=test_user_b, perform_serper_search=True))
    # print("\n--- 세 번째 실행 최종 보고서 ---")
    # print(final_report_third_run)