import os
import chromadb
from google import genai
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.prompts import PromptTemplate
from langchain_core.output_parsers import StrOutputParser
from dotenv import load_dotenv
import pandas as pd
import time
import re
import streamlit as st
from tenacity import retry, stop_after_attempt, wait_fixed, wait_exponential, retry_if_exception_type

# 순환 참조 방지 및 가독성을 위해 상위 모듈에서 필요한 함수들을 미리 임포트
from data_manager import update_article_suitability_score, load_articles_from_db

# ChromaDB의 네이티브 임베딩 함수를 임포트
import chromadb.utils.embedding_functions as embedding_functions

# .env 파일에서 환경 변수 로드
load_dotenv()

# Google API 키 설정
if "GOOGLE_API_KEY" not in os.environ:
    raise ValueError("GOOGLE_API_KEY 환경 변수가 설정되어 있지 않습니다. .env 파일 또는 시스템 환경 변수를 확인해주세요.")

# ChromaDB 설정
CHROMA_PERSIST_DIR = "./chroma_db"
COLLECTION_NAME = "hankyung_news_articles"

# --- 모델 초기화를 st.cache_resource 로 감싸서 RuntimeError 방지 ---
@st.cache_resource
def get_llm_suitability_model():
    """Gemini 2.0 Flash 모델 인스턴스를 캐시하여 반환합니다."""
    # ChatGoogleGenerativeAI는 GOOGLE_API_KEY 환경 변수를 자동으로 사용합니다.
    return ChatGoogleGenerativeAI(model="gemini-2.0-flash", temperature=0.1)

@st.cache_resource
def get_embedding_model():
    """ChromaDB의 GoogleGenerativeAIEmbeddingFunction 인스턴스를 캐시하여 반환합니다."""
    return embedding_functions.GoogleGenerativeAiEmbeddingFunction(api_key=os.environ["GOOGLE_API_KEY"], model_name="models/text-embedding-004")

# ChromaDB 클라이언트 및 컬렉션 함수는 변경 없음 (이미 지연 로딩됨)
def get_chroma_client():
    """ChromaDB 클라이언트를 반환합니다."""
    return chromadb.PersistentClient(path=CHROMA_PERSIST_DIR)

def get_chroma_collection():
    """ChromaDB 컬렉션을 반환합니다. 없으면 생성합니다."""
    client = get_chroma_client()
    collection = client.get_or_create_collection(name=COLLECTION_NAME, embedding_function=get_embedding_model())
    return collection

# 기존 단일 기사 적합도 평가 함수는 그대로 유지
@retry(
    stop=stop_after_attempt(5), # 5번 재시도
    wait=wait_exponential(multiplier=1, min=1, max=10), # 1초, 2초, 4초... 지수 백오프
    retry=retry_if_exception_type(Exception) # 모든 예외에 대해 재시도 (API 오류 포함)
)
def evaluate_article_suitability(article_content: str) -> int:
    """
    Gemini 2.0 Flash를 사용하여 기사의 산업/기업 분석 적합도를 평가하고 바이너리 (1:적합, 0:부적합) 반환.
    tenacity를 사용하여 API 호출 오류 및 Rate Limit에 대응합니다.
    """
    llm_suitability_model = get_llm_suitability_model()
    prompt_template = PromptTemplate.from_template(
        """다음 기사 내용이 특정 기업의 산업/기업 분석 리포트 작성에 유용한 정보(예: 사업, 기술, 시장, 경쟁사, 실적, 전략, 트렌드 등)를 포함하는지 평가해주세요.
        응답은 '적합' 또는 '부적합'으로만 해주세요.
        
        기사 내용:
        {article_content}
        
        평가 결과: """
    )
    
    chain = prompt_template | llm_suitability_model | StrOutputParser()
    
    response = chain.invoke({"article_content": article_content}).strip().lower()
    if "적합" in response:
        return 1 # 적합
    else:
        return 0 # 부적합

# --- 1. 새로운 배치 적합도 평가 함수 추가 ---
@retry(
    stop=stop_after_attempt(5), # 5번 재시도
    wait=wait_fixed(2), # 배치 호출은 일정한 2초 대기
    retry=retry_if_exception_type(Exception)
)
def evaluate_articles_in_batch(article_contents: list[str]) -> list[int]:
    """
    여러 기사의 적합도를 한 번의 배치 호출로 평가합니다.
    langchain의 chain.batch()를 사용하며, tenacity로 전체 배치 호출의 안정성을 높입니다.
    """
    llm_suitability_model = get_llm_suitability_model()
    prompt_template = PromptTemplate.from_template(
        """다음 기사 내용이 특정 기업의 산업/기업 분석 리포트 작성에 유용한 정보(예: 사업, 기술, 시장, 경쟁사, 실적, 전략, 트렌드 등)를 포함하는지 평가해주세요.
        응답은 '적합' 또는 '부적합'으로만 해주세요.

        기사 내용:
        {article_content}

        평가 결과: """
    )
    chain = prompt_template | llm_suitability_model | StrOutputParser()

    # 각 기사 내용에 대한 Prompt 템플릿 변수 목록 생성
    inputs = [{"article_content": content} for content in article_contents]
    
    # 배치 호출
    responses = chain.batch(inputs)

    # 응답을 1 또는 0으로 파싱
    suitability_scores = []
    for response in responses:
        if response.strip().lower() == '적합':
            suitability_scores.append(1)
        else:
            suitability_scores.append(0)
    
    return suitability_scores

# --- 2. embed_and_store_articles_to_chroma 함수 수정 (배치 처리 로직 도입) ---
def embed_and_store_articles_to_chroma(
    articles: list[dict],
    progress_callback=None
):
    """
    기사 목록을 배치로 적합도 판정 후 임베딩하여 ChromaDB에 저장합니다.
    적합도 판정 및 ChromaDB 저장 과정 모두 배치로 처리하여 속도를 향상시킵니다.
    """
    collection = get_chroma_collection()
    
    total_articles = len(articles)
    suitable_count = 0

    if progress_callback:
        progress_callback(f"[벡터 DB] 총 {total_articles}개 기사 적합도 판정 및 임베딩 준비 중...", 0.0)

    # 배치 사이즈 설정 (적절한 값으로 튜닝 필요)
    # Gemini API의 Rate Limit을 고려하여 너무 크지 않게 설정하는 것이 중요
    batch_size = 10
    
    for i in range(0, total_articles, batch_size):
        article_batch = articles[i:i + batch_size]
        
        # 아직 판정되지 않은 기사만 골라내기
        articles_to_evaluate = [
            (idx, article) 
            for idx, article in enumerate(article_batch) 
            if article.get("suitability_score") is None or article.get("suitability_score") not in [0, 1]
        ]
        
        if articles_to_evaluate:
            print(f"--- {i+1}번째 배치 ({len(articles_to_evaluate)}개 기사) 적합도 판정 시작 ---")
            
            # 1. 배치 적합도 판정
            try:
                # 판정 대상 기사 내용만 추출
                contents_to_evaluate = [art[1]["기사 원문"] for art in articles_to_evaluate]
                # 배치 API 호출
                batch_scores = evaluate_articles_in_batch(contents_to_evaluate)
                
                # 결과 적용 및 SQLite에 업데이트
                for (batch_idx, article), score in zip(articles_to_evaluate, batch_scores):
                    article_id = article["id"]
                    article["suitability_score"] = score
                    update_article_suitability_score(article_id, score)
                
                print(f"--- {len(articles_to_evaluate)}개 기사 적합도 판정 완료. ChromaDB 임베딩 대기 중 ---")
                
            except Exception as e:
                print(f"경고: 배치 적합도 평가 중 오류 발생 (Tenacity 재시도 후에도 실패): {e}. 이 배치({i}-{i+batch_size-1})의 모든 기사를 부적합으로 처리합니다.")
                for _, article in articles_to_evaluate:
                    article_id = article["id"]
                    article["suitability_score"] = 0
                    update_article_suitability_score(article_id, 0)
            
            # API Rate Limit을 위해 배치 처리 간 충분한 시간 지연
            # 이 시간은 API 할당량에 따라 튜닝이 필요
            time.sleep(30) 
            
        # 2. 적합도 기준 필터링 및 임베딩 준비
        documents_to_add = []
        metadatas_to_add = []
        ids_to_add = []
        
        for article in article_batch:
            suitability_score = article.get("suitability_score")
            
            if suitability_score == 1:
                chroma_article_id = f"article_{article['id']}"
                
                # ChromaDB에 이미 해당 ID의 문서가 있는지 확인 (재임베딩 방지)
                existing_documents = collection.get(ids=[chroma_article_id], include=[])
                if existing_documents and existing_documents['ids']:
                    print(f"알림: 기사 '{article.get('제목', 'N/A')}' (ID: {article['id']})는 이미 ChromaDB에 임베딩되어 있습니다. 건너뜁니다.")
                    continue
                
                documents_to_add.append(article["기사 원문"])
                metadatas_to_add.append({
                    "sqlite_id": article["id"],
                    "title": article.get("제목", "N/A"),
                    "publish_date": article.get("작성일자", "N/A"),
                    "author": article.get("기자", "N/A"),
                    "url": article["기사 URL"],
                    "suitability_score": suitability_score
                })
                ids_to_add.append(chroma_article_id)
                suitable_count += 1
            else:
                print(f"알림: 기사 '{article.get('제목', 'N/A')}' (ID: {article['id']})는 부적합 판정되어 필터링됩니다.")

        # 3. ChromaDB에 배치 임베딩 및 저장
        if documents_to_add:
            try:
                print(f"ChromaDB에 {len(documents_to_add)}개의 적합한 기사 배치 임베딩 및 저장 중...")
                # ChromaDB의 add 메서드 자체에 tenacity를 직접 적용하기는 어렵지만,
                # 내부적으로 임베딩 함수가 호출될 때 발생할 수 있는 네트워크 오류 등은 ChromaDB가 어느 정도 처리합니다.
                collection.add(
                    documents=documents_to_add,
                    metadatas=metadatas_to_add,
                    ids=ids_to_add,
                )
                print(f"총 {len(documents_to_add)}개의 기사 배치 저장 완료.")
                # ChromaDB 임베딩 API 호출 간에도 충분한 시간 지연
                time.sleep(30)
            except Exception as e:
                print(f"ChromaDB 배치 저장 중 오류 발생: {e}")
                # 이 경우 실패한 배치에 대한 재시도 로직을 여기에 추가하거나 로그 남기기
        else:
            print(f"배치({i}-{i+batch_size-1})에 적합한 기사가 없어 ChromaDB에 저장할 내용이 없습니다.")

        if progress_callback:
            progress_val = min(1.0, (i + batch_size) / total_articles)
            progress_callback(f"[벡터 DB] 기사 판정 및 임베딩 중... ({i+batch_size}/{total_articles} 완료, 적합: {suitable_count}개)", progress_val)

    if progress_callback:
        progress_callback(f"[벡터 DB] 모든 기사 처리 완료. 최종 적합 기사: {suitable_count}개.", 1.0)
    print(f"모든 기사 처리 완료. 최종 적합 기사: {suitable_count}개.")

def get_chroma_status():
    """ChromaDB 컬렉션의 기본 정보를 반환합니다."""
    collection = get_chroma_collection()
    count = collection.count()
    
    # 적합도 점수 분포 (SQLite에서 불러와서 계산)
    articles_from_db = load_articles_from_db()
    
    suitability_scores = [a["suitability_score"] for a in articles_from_db if a["suitability_score"] in [0, 1]]
    
    score_counts = pd.Series(suitability_scores).value_counts().sort_index().to_dict()
    
    return {
        "총 문서 수 (ChromaDB)": count,
        "기사 적합도 점수 분포 (SQLite 기준)": score_counts,
        "SQLite에 저장된 전체 기사 수": len(articles_from_db)
    }

def search_chroma_by_query(query_text: str, k: int = 5, filter_dict: dict = None):
    """
    ChromaDB에서 쿼리 텍스트로 유사한 문서를 검색합니다.
    """
    collection = get_chroma_collection()
    try:
        results = collection.query(
            query_texts=[query_text],
            n_results=k,
            where=filter_dict, # 메타데이터 필터링
            include=['documents', 'metadatas', 'distances']
        )
        
        formatted_results = []
        if results and results['ids']:
            for i in range(len(results['ids'][0])):
                formatted_results.append({
                    "id": results['ids'][0][i],
                    "score": results['distances'][0][i], # score는 숫자(float) 그대로 유지
                    "title": results['metadatas'][0][i].get('title', 'N/A'),
                    "publish_date": results['metadatas'][0][i].get('publish_date', 'N/A'),
                    "suitability_score": "적합" if results['metadatas'][0][i].get('suitability_score') == 1 else "부적합",
                    "url": results['metadatas'][0][i].get('url', 'N/A'),
                    "content_preview": results['documents'][0][i][:200] + "..." # 본문 미리보기
                })
        return formatted_results
    except Exception as e:
        print(f"ChromaDB 검색 중 오류 발생: {e}")
        return []

# 모듈 단독 실행 시 테스트 코드 (실제 Streamlit 환경에서 실행될 때는 호출되지 않음)
if __name__ == "__main__":
    print("--- vector_db_manager.py 모듈 테스트 시작 ---")
    
    # 테스트용 임시 기사 데이터 생성 (실제 DB 연동을 위해 더미 데이터 포함)
    test_articles_for_embedding = [
        {"id": 1, "제목": "한화에어로스페이스, 대규모 우주 발사체 계약 체결", "작성일자": "2024.07.25", "기자": "김우주", "기사 원문": "한화에어로스페이스는 최근 NURI 발사체 개발에 기여하며 대규모 국제 우주 발사체 계약을 성공적으로 체결했다. 이는 회사의 미래 성장 동력 확보에 중요한 전환점이 될 것으로 보인다. 이번 계약으로 한화에어로스페이스의 항공우주 기술력이 다시 한번 입증되었다. 이 기사는 산업 분석에 매우 적합하다.", "기사 URL": "http://test.com/a1", "suitability_score": None},
        {"id": 2, "제목": "최신 AI 기술 동향과 산업 영향", "작성일자": "2024.07.20", "기자": "이혁신", "기사 원문": "최근 생성형 AI 기술의 발전이 산업 전반에 미치는 영향이 커지고 있다. 특히 데이터 센터와 관련된 반도체 수요가 폭증하고 있으며, 이는 IT 기업들의 투자 확대로 이어지고 있다. 하지만 AI 윤리 문제에 대한 논의도 활발하다. 이 기사는 산업 분석에 적합하다.", "기사 URL": "http://test.com/a2", "suitability_score": None},
        {"id": 3, "제목": "주말 날씨, 전국적으로 맑음", "작성일자": "2024.07.28", "기자": "박기상", "기사 원문": "이번 주말은 전국적으로 맑고 화창한 날씨가 예상된다. 나들이하기 좋은 기온을 유지하며 가을의 정취를 만끽할 수 있을 것이다. 미세먼지 농도도 낮아 공기가 깨끗할 것으로 보인다. 이 기사는 산업 분석에 전혀 적합하지 않다.", "기사 URL": "http://test.com/a3", "suitability_score": None}, # 부적합 예상
        {"id": 4, "제목": "한화시스템, 해양 무인 시스템 개발 가속화", "작성일자": "2024.07.10", "기자": "최방산", "기사 원문": "한화시스템이 국방 및 해양 산업 분야에서 무인 시스템 개발에 박차를 가하고 있다. 자율 운항 선박 및 수중 드론 기술을 고도화하여 미래 해양 방어 체계를 구축하는 데 기여할 계획이다. 이는 스마트 방산 분야에서의 리더십을 강화할 것이다. 이 기사는 기업 분석에 매우 적합하다.", "기사 URL": "http://test.com/a4", "suitability_score": None}
    ]

    # data_manager 임포트 및 DB 초기화
    initialize_db()

    # 기존 ChromaDB 데이터 삭제 (테스트용)
    if os.path.exists(CHROMA_PERSIST_DIR):
        import shutil
        shutil.rmtree(CHROMA_PERSIST_DIR)
        print(f"기존 ChromaDB '{CHROMA_PERSIST_DIR}' 폴더 삭제.")

    # 테스트 데이터 DB에 저장 (ChromaDB에 넣기 전 DB에 있어야 함)
    print("테스트 기사를 SQLite DB에 저장 중...")
    save_articles_to_db(test_articles_for_embedding)
    
    print("저장 완료.")

    # Streamlit 캐시를 사용하므로, 실제 Streamlit 환경처럼 동작하도록 get_chroma_collection 호출
    collection = get_chroma_collection()
    print(f"ChromaDB 컬렉션 '{COLLECTION_NAME}' 준비 완료. 현재 문서 수: {collection.count()}")

    print("\n--- 기사 적합도 판정 및 임베딩 저장 시도 (첫 번째 실행) ---")
    def test_progress_callback(message, progress_val):
        print(f"Status: {message} | Progress: {progress_val*100:.1f}%")

    # DB에서 기사를 다시 로드하여 임베딩 함수에 전달
    articles_from_db_for_test = load_articles_from_db()
    embed_and_store_articles_to_chroma(
        articles=articles_from_db_for_test,
        progress_callback=test_progress_callback
    )

    print("\n--- ChromaDB 저장 후 현황 확인 (첫 번째 실행) ---")
    status = get_chroma_status()
    print(f"총 저장된 문서 수 (ChromaDB): {status['총 문서 수 (ChromaDB)']}")
    print(f"SQLite에 저장된 전체 기사 수: {status['SQLite에 저장된 전체 기사 수']}")
    print(f"기사 적합도 점수 분포 (SQLite 기준): {status['기사 적합도 점수 분포 (SQLite 기준)']}")

    print("\n--- 기사 적합도 판정 및 임베딩 저장 시도 (두 번째 실행 - 재임베딩 방지 확인) ---")
    # 두 번째 실행: 이미 임베딩된 기사는 건너뛰는지 확인
    articles_from_db_for_test_re_run = load_articles_from_db()
    embed_and_store_articles_to_chroma(
        articles=articles_from_db_for_test_re_run,
        progress_callback=test_progress_callback
    )

    print("\n--- ChromaDB 저장 후 현황 확인 (두 번째 실행) ---")
    status_re_run = get_chroma_status()
    print(f"총 저장된 문서 수 (ChromaDB): {status_re_run['총 문서 수 (ChromaDB)']}")
    print(f"SQLite에 저장된 전체 기사 수: {status_re_run['SQLite에 저장된 전체 기사 수']}")
    print(f"기사 적합도 점수 분포 (SQLite 기준): {status_re_run['기사 적합도 점수 분포 (SQLite 기준)']}")


    print("\n--- ChromaDB 검색 테스트 ---")
    search_query = "한화에어로스페이스 우주 사업 계획"
    search_results = search_chroma_by_query(search_query, k=2)
    print(f"\n검색 쿼리: '{search_query}'")
    for res in search_results:
        # score는 float로 반환되므로, 출력 시에만 포맷팅 적용
        print(f"- ID: {res['id']}, 점수: {res['score']:.4f}, 제목: {res['title']}, 적합도: {res['suitability_score']}")
        print(f"  URL: {res['url']}")
        print(f"  내용 미리보기: {res['content_preview']}")

    search_query_filtered = "AI 기술 트렌드"
    search_results_filtered = search_chroma_by_query(search_query_filtered, k=2, filter_dict={"suitability_score": 1})
    print(f"\n필터링 검색 쿼리: '{search_query_filtered}' (적합도 == 1)")
    if search_results_filtered:
        for res in search_results_filtered:
            # score는 float로 반환되므로, 출력 시에만 포맷팅 적용
            print(f"- ID: {res['id']}, 점수: {res['score']:.4f}, 제목: {res['title']}, 적합도: {res['suitability_score']}")
            print(f"  URL: {res['url']}")
            print(f"  내용 미리보기: {res['content_preview']}")
    else:
        print("필터링 조건에 맞는 검색 결과가 없습니다.")

    print("\n--- vector_db_manager.py 모듈 테스트 종료 ---")
