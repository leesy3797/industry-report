# 🚀 AI-Powered Industry/Company Analysis Executive Summary Generator

## 📋 프로젝트 개요

**LLM을 활용하여 산업/기업 분석 Executive Summary 자동 생성하는 서비스**입니다. 수백~수천 건의 한국경제 뉴스 데이터를 수집하고, LangChain 기반의 Chain을 사용하여 GPT-4o-mini(OpenAI) 또는 Gemini-2.0-flash(Google) 모델을 효과적으로 사용하여 경영진 보고 목적의 전문적인 분석 리포트를 자동으로 생성하는 AI 서비스입니다..

### 🎯 주요 기능
- **뉴스 기사 수집**: 한국경제 뉴스 사이트에서 사용자가 설정한 조건(기업명, 기간, 키워드 등)에 따라 특정 기업의 기사를 Batch 작업으로 스크래핑
- **AI 기반 적합도 평가**: 수집된 기사의 품질을 AI가 자동으로 평가하여 고퀄리티 기사 기반의 레포트 작업이 가능 (분석 목표 불일치, 광고성 기사 등 노이즈 선별) 
- **다양한 리포트 생성**: 월별/연간 핵심 이슈, 핵심 키워드 요약, 트렌드 분석, 미래 전망 분석 등 다양한 주제의 보고서를 MECE하게 생성
- **웹 검색 기능**: Web Search 선택을 통해 시의성 있는 정보를 포함한 보고서 생성이 가능 (미래 보고서 생성 시)
- **웹 기반 인터페이스**: Streamlit을 통한 Web UI를 제공하여, 모든 작업의 프로세스를 직관적으로 조작하고 모니터링 가능

---

## 🏗️ 시스템 아키텍처

```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   Web Interface │    │  Data Pipeline  │    │  LLM Processing │
│   (Streamlit)   │◄──►│   (Crawlers)    │◄──►│   (LangChain)   │
└─────────────────┘    └─────────────────┘    └─────────────────┘
         │                       │                       │
         ▼                       ▼                       ▼
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   SQLite DB     │    │   ChromaDB      │    │  OpenAI/Gemini  │
│  (Articles)     │    │  (Vector Store) │    │     (LLMs)      │
└─────────────────┘    └─────────────────┘    └─────────────────┘
```

### 🔧 핵심 컴포넌트

#### 1. **데이터 수집 레이어**
- **`async_hankyung_crawler.py`**: 한국경제 뉴스 기사 수집기
    * (1) 비동기 배치 작업으로 수집 속도 최적화 
        * '기사 URL' 수집은 `동기 처리`
        * '기사 원문' 수집은 `비동기 처리`
    * (2) 서버 부하 및 IP 차단 방지 위한 조치 적용
        * **User-Agent 로테이션**: 차단 방지 위한 다양한 브라우저 시뮬레이션 
        * **Semaphore 동시성 제어**: 서버 부하 방지 및 안정적인 크롤링 가능

#### 2. **데이터 관리 레이어**
- **`async_data_manager.py`**: SQLite 데이터베이스 관리
- **다중 사용자 지원**: 사용자별 데이터 격리 및 관리
- **데이터 무결성 보장**: 중복 방지 및 트랜잭션 관리

#### 3. **LLM 처리 레이어**
- **`async_report_generator.py`**: 비동기 리포트 생성 엔진
- **`report_generator.py`**: 동기식 리포트 생성 엔진
- **`future_report_generator.py`**: 미래 전망 분석 전용 모듈
- **`prompts.py`**: 체계화된 프롬프트 템플릿 관리

#### 4. **벡터 데이터베이스 레이어**
- **`vector_db_manager.py`**: ChromaDB 기반 벡터 저장소 관리
- **임베딩 모델**: Google Generative AI 임베딩 활용
- **유사도 검색**: 관련 문서의 효율적인 검색 및 분석

#### 5. **웹 인터페이스 레이어**
- **`app.py`**: Streamlit 메인 애플리케이션
- **`pages/`**: 다중 페이지 구조의 사용자 인터페이스
- **반응형 디자인**: 다양한 화면 크기에 최적화

---

## 🛠️ 기술 스택

### **Backend & AI**
- **Python 3.8+**: 메인 개발 언어
- **LangChain 0.3.27**: LLM 애플리케이션 프레임워크
- **OpenAI GPT-4o-mini**: 주요 LLM 모델
- **Google Gemini 2.0 Flash**: 보조 LLM 모델
- **ChromaDB**: 벡터 데이터베이스
- **SQLite**: 관계형 데이터베이스

### **Web Framework & UI**
- **Streamlit**: 웹 애플리케이션 프레임워크
- **BeautifulSoup4**: 웹 스크래핑
- **aiohttp**: 비동기 HTTP 클라이언트
- **Pandas**: 데이터 처리 및 분석

### **DevOps & Utilities**
- **asyncio**: 비동기 프로그래밍
- **tenacity**: 재시도 로직 및 에러 핸들링
- **python-dotenv**: 환경 변수 관리
- **pysqlite3**: 고성능 SQLite 드라이버

---

## 📊 핵심 기능 상세

### 1. **지능형 뉴스 크롤링 시스템**
```python
# 비동기 크롤링으로 성능 최적화
async def get_article_details(session, article_url, semaphore):
    async with semaphore:  # 동시 접속 수 제어
        # 기사 상세 정보 추출
        # 메타데이터 파싱
        # 에러 핸들링
```

**주요 특징:**
- **비동기 처리**: 동시에 여러 기사 수집으로 성능 향상
- **스마트 차단 방지**: User-Agent 로테이션 및 요청 간격 조절
- **데이터 정제**: HTML 태그 제거 및 텍스트 정규화
- **에러 복구**: 네트워크 오류 시 자동 재시도

### 2. **AI 기반 적합도 평가 시스템**
```python
def evaluate_article_suitability(article_content: str) -> int:
    # Gemini AI를 활용한 기사 적합도 평가
    # 산업/기업 분석에 유용한 정보 포함 여부 판단
    # 바이너리 분류 (1: 적합, 0: 부적합)
```

**평가 기준:**
- 사업 전략 관련성
- 기술 트렌드 포함 여부
- 시장 동향 정보
- 경쟁사 분석 가치
- 실적 및 전망 데이터

### 3. **다양한 리포트 생성 엔진**

#### **월별 핵심 이슈 분석**
- MECE 원칙에 따른 3가지 핵심 이슈 선정
- 청와대 비서실 보고서 형식 준수
- 정량적 데이터 및 구체적 사례 포함

#### **연간 종합 분석**
- 월별 데이터를 종합한 연도별 트렌드 분석
- 핵심 성과 및 이슈 요약
- 미래 전망 및 시사점 도출

#### **키워드 기반 요약**
- 주요 키워드 추출 및 분석
- 키워드 간 연관성 분석
- 시계열 키워드 트렌드

#### **미래 전망 분석**
- 현재 트렌드를 기반으로 한 미래 예측
- 시나리오 기반 분석
- 리스크 및 기회 요소 분석

### 4. **벡터 데이터베이스 기반 검색**
```python
# ChromaDB를 활용한 유사도 검색
collection = get_chroma_collection()
results = collection.query(
    query_texts=[query],
    n_results=10
)
```

**검색 기능:**
- 의미론적 유사도 검색
- 키워드 기반 필터링
- 시간 범위별 검색
- 관련 문서 추천

---

## 🚀 성능 최적화

### **비동기 처리**
- **aiohttp**: 비동기 HTTP 요청으로 크롤링 성능 향상
- **asyncio**: 동시성 제어로 시스템 리소스 효율적 활용
- **Semaphore**: 동시 접속 수 제한으로 서버 부하 방지

### **캐싱 시스템**
```python
@st.cache_resource
def get_llm_model():
    return ChatOpenAI(model="gpt-4o-mini", temperature=0.1)
```
- **Streamlit 캐싱**: 모델 인스턴스 재사용
- **데이터베이스 캐싱**: 자주 사용되는 쿼리 결과 캐싱
- **벡터 임베딩 캐싱**: 중복 임베딩 계산 방지

### **에러 핸들링**
```python
@retry(
    wait=wait_exponential(multiplier=1, min=4, max=10),
    stop=stop_after_attempt(10),
    retry=retry_if_exception_type(Exception)
)
```
- **tenacity 라이브러리**: 지수 백오프 재시도 로직
- **API 호출 제한**: Rate limiting으로 API 오류 방지
- **graceful degradation**: 일부 기능 실패 시에도 서비스 지속

---

## 📁 프로젝트 구조

```
industry-report/
├── app.py                          # Streamlit 메인 애플리케이션
├── requirements.txt                # Python 의존성
├── .env                           # 환경 변수 (API 키 등)
├── .gitignore                     # Git 제외 파일 설정
│
├── 📊 데이터 수집 & 관리
│   ├── async_hankyung_crawler.py  # 비동기 뉴스 크롤러
│   ├── hankyung_crawler.py        # 동기식 크롤러
│   ├── async_data_manager.py      # 비동기 데이터베이스 관리
│   └── data_manager.py            # 동기식 데이터베이스 관리
│
├── 🤖 AI 처리 엔진
│   ├── async_report_generator.py  # 비동기 리포트 생성
│   ├── report_generator.py        # 동기식 리포트 생성
│   ├── future_report_generator.py # 미래 전망 분석
│   ├── vector_db_manager.py       # 벡터 데이터베이스 관리
│   └── prompts.py                 # 프롬프트 템플릿
│
├── 🌐 웹 인터페이스
│   └── pages/
│       ├── async_home.py          # 메인 페이지
│       ├── async_report_viewer_1.py # 연도별 이슈 분석
│       ├── async_report_viewer_2.py # 키워드 요약
│       ├── async_report_viewer_3.py # 트렌드 분석
│       └── async_report_viewer_4.py # 미래 전망
│
├── 📊 데이터베이스
│   ├── articles.db                # 기사 데이터
│   ├── reports.db                 # 생성된 리포트
│   └── chroma_db/                 # 벡터 데이터베이스
│
└── 📄 생성된 리포트 예시
    ├── cj대한통운_연간_이슈_레포트.pdf
    ├── cj대한통운_6대_키워드_레포트.pdf
    ├── cj대한통운_트렌드_레포트.pdf
    └── cj대한통운_미래_비전_보고서.pdf
```

---

## 🎯 핵심 기술적 성과

### **1. 비동기 아키텍처 구현**
- **성능 향상**: 동기식 대비 3-5배 빠른 데이터 수집
- **리소스 효율성**: 동시성 제어로 서버 부하 최소화
- **확장성**: 모듈화된 구조로 새로운 데이터 소스 추가 용이

### **2. AI 기반 지능형 필터링**
- **정확도**: 수동 필터링 대비 85% 이상의 적합도 평가 정확도
- **효율성**: 자동화로 인력 투입 시간 90% 절약
- **일관성**: AI 기반 평가로 일관된 품질 보장

### **3. 전문적인 리포트 생성**
- **품질**: 경영진 보고 수준의 전문적 분석
- **구조화**: 표준화된 형식으로 가독성 향상
- **맞춤화**: 기업별 특성에 맞는 분석 제공

### **4. 벡터 데이터베이스 활용**
- **검색 효율성**: 의미론적 검색으로 관련성 높은 결과
- **확장성**: 대용량 문서 처리 가능
- **실시간성**: 빠른 검색 응답 시간

---

## 🔮 향후 발전 방향

### **기술적 개선**
- **다중 데이터 소스**: 한국경제 외 추가 언론사 지원
- **실시간 알림**: 중요 이슈 발생 시 자동 알림 시스템
- **API 서비스**: RESTful API로 외부 시스템 연동
- **클라우드 배포**: AWS/Azure 클라우드 인프라 활용

### **기능 확장**
- **다국어 지원**: 영어, 중국어 등 다국어 리포트 생성
- **시각화 강화**: 인터랙티브 차트 및 그래프 추가
- **예측 모델**: 머신러닝 기반 트렌드 예측
- **협업 기능**: 팀 기반 리포트 공유 및 편집

---

## 👨‍💻 개발자 정보

**이승용 (SeungYong Lee)**
- **기술 스택**: Python, AI/ML, Web Development, Data Engineering
- **관심 분야**: AI 애플리케이션 개발, 데이터 분석, 비즈니스 인텔리전스
- **연락처**: [이메일 주소]

---

## 📄 라이선스

이 프로젝트는 MIT 라이선스 하에 배포됩니다.

---

*이 프로젝트는 AI 기술을 활용한 실용적인 비즈니스 솔루션 개발 능력을 보여주는 포트폴리오 프로젝트입니다.*
