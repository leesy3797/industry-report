import requests
from bs4 import BeautifulSoup
import time
import re
import random
from data_manager import save_articles_to_db

# 다양한 브라우저 User-Agent 리스트
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:124.0) Gecko/20100101 Firefox/124.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (Linux; Android 13; SM-G991N) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Mobile Safari/537.36",
]

def get_article_details(article_url: str) -> dict:
    """
    개별 기사 URL에 접근하여 제목, 작성일자, 기자, 기사 원문을 추출합니다.
    """
    details = {
        "제목": "N/A",
        "작성일자": "N/A",
        "기자": "N/A",
        "기사 원문": "N/A",
        "기사 URL": article_url
    }
    
    try:
        headers = {"User-Agent": random.choice(USER_AGENTS)}
        response = requests.get(article_url, headers=headers, timeout=10) # 무작위 User-Agent 적용
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')

        # 1. 제목 (기사 제목): og:title 메타 태그가 가장 신뢰할 수 있는 제목 소스
        title_tag = soup.find("meta", property="og:title")
        if title_tag and "content" in title_tag.attrs:
            details["제목"] = title_tag["content"].strip()
        elif soup.title:
            # <title> 태그에서 " | 한국경제" 부분 제거
            full_title = soup.title.string
            if full_title and '|' in full_title:
                details["제목"] = full_title.split('|')[0].strip()
            else:
                details["제목"] = full_title.strip()

        # 2. 작성일자 (article:published_time 메타 태그 사용)
        published_time_tag = soup.find("meta", property="article:published_time")
        if published_time_tag and "content" in published_time_tag.attrs:
            # 예: "2018-03-26T19:14:42+09:00" -> "2018-03-26"
            date_full = published_time_tag["content"].split('T')[0]
            details["작성일자"] = date_full

        # 3. 기자 (dable:author 메타 태그 사용)
        author_tag = soup.find("meta", property="dable:author")
        if author_tag and "content" in author_tag.attrs:
            details["기자"] = author_tag["content"].strip()
        else:
            # GATrackingData에서 기자 정보 추출 시도
            script_tags = soup.find_all("script", type="text/javascript")
            for script in script_tags:
                if script.string and "GATrackingData" in script.string:
                    match = re.search(r"hk_reporter\s*:\s*'([^']+)'", script.string)
                    if match:
                        reporter_info = match.group(1) # 예: '김진성(667)'
                        details["기자"] = reporter_info.split('(')[0].strip()
                        break
        
        # 4. 기사 원문: 가장 일반적인 기사 본문 컨테이너 클래스/ID 시도
        article_body_content = []
        
        # 첫 번째 시도: div#articletxt
        article_div = soup.find("div", id="articletxt")
        if not article_div:
            # 두 번째 시도: div.article-body (더 일반적인 뉴스 본문 클래스)
            article_div = soup.find("div", class_="article-body")
        
        if article_div:
            # 기사 본문 내의 모든 <p> 태그의 텍스트를 조합
            paragraphs = article_div.find_all("p")
            for p in paragraphs:
                text = p.get_text(strip=True)
                # 불필요한 공백/줄바꿈 제거 및 정리
                text = re.sub(r'\s+', ' ', text).strip()
                if text:
                    article_body_content.append(text)
            
            # 최종 기사 원문 결합
            if article_body_content:
                details["기사 원문"] = "\n\n".join(article_body_content)
            else:
                # <p> 태그가 없지만 텍스트가 바로 있는 경우를 대비
                details["기사 원문"] = article_div.get_text(separator="\n", strip=True)
                details["기사 원문"] = re.sub(r'\s*\n\s*', '\n', details["기사 원문"]).strip() # 여러 줄바꿈 하나로
        
    except requests.exceptions.RequestException as e:
        print(f"개별 기사 URL 요청 중 오류 발생 ({article_url}): {e}")
    except Exception as e:
        print(f"개별 기사 파싱 중 오류 발생 ({article_url}): {e}")
        
    return details


def get_hankyung_news_html(
    query: str,
    sort: str,
    area: str = "ALL",
    start_date: str = "2014.01.01",
    end_date: str = "2025.07.31",
    exact_phrase: str = "",
    include_keywords: str = "",
    exclude_keywords: str = "",
    hk_only: bool = True,
    page: int = 1
) -> str:
    """
    한국경제신문 뉴스 검색 URL을 구성하고 GET 요청을 보내 HTML 내용을 반환합니다.
    모든 파라미터는 Streamlit에서 받은 원본 문자열을 그대로 사용합니다.
    """
    base_url = "https://search.hankyung.com/search/news"

    params = {
        "query": query,
        "sort": sort,
        "period": "DATE",
        "area": area,
        "sdate": start_date,
        "edate": end_date,
        "page": page
    }

    if exact_phrase:
        params["exact"] = exact_phrase
    if include_keywords:
        params["include"] = include_keywords
    if exclude_keywords:
        params["except"] = exclude_keywords
    
    params["hk_only"] = "y" if hk_only else "n"

    try:
        response = requests.get(base_url, params=params)
        response.raise_for_status()
        return response.text
    except requests.exceptions.RequestException as e:
        print(f"URL 요청 중 오류 발생: {e}")
        return None


def parse_articles_from_html(html_content: str) -> list[dict]:
    """
    HTML 콘텐츠를 파싱하여 기사 목록과 메타데이터 (주로 URL과 제목)를 추출합니다.
    여기서는 '요약' 대신 'URL'과 '제목'을 우선 추출합니다.
    """
    articles_data = []
    soup = BeautifulSoup(html_content, 'html.parser')

    articles_list = soup.select('ul.article > li')
    
    for article_li in articles_list:
        try:
            title_tag = article_li.select_one('.txt_wrap .tit')
            title = title_tag.get_text(strip=True) if title_tag else "제목 없음"

            url_tag = article_li.select_one('.txt_wrap > a')
            url = url_tag['href'] if url_tag and 'href' in url_tag.attrs else "URL 없음"

            articles_data.append({
                "제목_검색결과": title, # 검색 결과 페이지에서 가져온 제목 (구분용, 최종 DF에는 사용되지 않을 수 있음)
                "URL": url,
            })
        except Exception as e:
            print(f"검색 결과 기사 목록 파싱 중 오류 발생: {e} (HTML: {article_li})")
            continue
    
    return articles_data

def get_total_articles_count(html_content: str) -> int:
    """
    HTML 콘텐츠에서 전체 기사 수를 추출합니다.
    """
    soup = BeautifulSoup(html_content, 'html.parser')
    total_count_element = soup.select_one('.section.hk_news .tit-wrap .tit span')
    if total_count_element:
        total_articles_text = total_count_element.get_text(strip=True)
        match = re.search(r'/ (\d+)건', total_articles_text)
        if match:
            return int(match.group(1))
    return -1

def fetch_all_hankyung_articles(
    query: str,
    sort: str,
    area: str = "ALL",
    start_date: str = "2014.01.01",
    end_date: str = "2025.07.31",
    exact_phrase: str = "",
    include_keywords: str = "",
    exclude_keywords: str = "",
    hk_only: bool = True,
    max_pages: int = None,
    sleep_time: float = 0.5,
    progress_callback=None
) -> list[dict]:
    """
    한국경제신문 검색 결과의 모든 페이지에서 기사 정보를 크롤링합니다.
    각 기사의 상세 페이지로 이동하여 원문을 가져옵니다.
    """
    all_article_urls = []
    fetched_articles_details = []
    current_page = 1
    total_articles_count = -1
    
    # 1단계: 검색 결과 페이지에서 모든 기사 URL 수집
    if progress_callback:
        progress_callback(f"[1/2단계] '{query}' 키워드로 뉴스 검색 결과 URL을 수집 중...", 0.0, 0)

    while True:
        html_content = get_hankyung_news_html(
            query=query,
            sort=sort,
            area=area,
            start_date=start_date,
            end_date=end_date,
            exact_phrase=exact_phrase,
            include_keywords=include_keywords,
            exclude_keywords=exclude_keywords,
            hk_only=hk_only,
            page=current_page
        )

        if html_content is None:
            if progress_callback:
                progress_callback("URL 요청 중 오류가 발생하여 검색 결과 수집을 중단합니다.", 0.0, 0)
            break

        if total_articles_count == -1:
            total_articles_count = get_total_articles_count(html_content)
            if total_articles_count == -1:
                # 총 기사 수 파악 실패 시, 일단 현재 페이지에서 얻은 기사 수만큼만 진행
                if progress_callback:
                    progress_callback("총 기사 수를 파악할 수 없습니다. 검색 결과 페이지의 기사만 수집합니다.", 0.0, 0)
                #total_articles_count = 0 # 의미 없음.
        
        current_page_articles_meta = parse_articles_from_html(html_content)
        if not current_page_articles_meta:
            if progress_callback:
                progress_callback("[1/2단계] 더 이상 검색 결과 기사 URL이 없거나 모든 URL을 가져왔습니다.", 0.49, len(all_article_urls)) # 1단계 거의 완료 표시
            break

        for article_meta in current_page_articles_meta:
            if article_meta["URL"] != "URL 없음":
                all_article_urls.append(article_meta["URL"])

        # 1단계 진행률 업데이트
        if progress_callback and total_articles_count != -1:
            # 1단계의 진행률을 0.0 ~ 0.5 사이로 매핑
            progress_val_step1 = min(len(all_article_urls) / total_articles_count / 2, 0.5) if total_articles_count > 0 else 0.0
            progress_callback(f"[1/2단계] 기사 URL 수집 중... (현재 {len(all_article_urls)}개 수집됨 / 예상 {total_articles_count}개)", 
                              progress_val_step1, total_articles_count)
        elif progress_callback: # 총 기사 수를 모를 때
            progress_callback(f"[1/2단계] 기사 URL 수집 중... (현재 {len(all_article_urls)}개 수집됨)", 
                              min(current_page * 10 / 1000, 0.5), 0) # 최대 1000개 URL을 예상, 0.5까지 진행

        if max_pages and current_page >= max_pages:
            if progress_callback:
                progress_callback(f"[1/2단계 완료] 최대 {max_pages} 페이지까지 URL 수집 완료. 총 {len(all_article_urls)}개.", 0.5, len(all_article_urls))
            break
        
        if total_articles_count != -1 and len(all_article_urls) >= total_articles_count:
             if progress_callback:
                progress_callback(f"[1/2단계 완료] 총 {total_articles_count}개의 기사 URL을 모두 가져왔습니다.", 0.5, total_articles_count)
             break

        current_page += 1
        time.sleep(random.uniform(0, 1)) # 페이지 간 지연

    # 2단계: 수집된 각 URL에서 상세 내용 크롤링
    total_urls_to_crawl = len(all_article_urls)
    if total_urls_to_crawl == 0:
        if progress_callback:
            progress_callback("수집할 기사 URL이 없습니다.", 0.0, 0)
        return []

    if progress_callback:
        progress_callback(f"[2/2단계 시작] 총 {total_urls_to_crawl}개의 기사 상세 내용을 크롤링합니다...", 0.5, total_urls_to_crawl)

    batch = []
    for i, url in enumerate(all_article_urls):
        # 2단계 진행률 계산 (0.5 ~ 1.0 사이로 매핑)
        progress_for_step2 = (i + 1) / total_urls_to_crawl
        overall_progress_value = 0.5 + (0.5 * progress_for_step2) # 0.5 (1단계 완료) + 0.5 * (0.0~1.0)
        
        if progress_callback:
            progress_callback(f"[2/2단계] 기사 상세 내용 크롤링 중... ({i+1}/{total_urls_to_crawl} - {url})", 
                              overall_progress_value, total_urls_to_crawl)

        article_detail = get_article_details(url)
        article_detail["기업명"] = query
        batch.append(article_detail)
        fetched_articles_details.append(article_detail)  # 크롤링 결과 리스트에도 추가
        if len(batch) == 10:
            save_articles_to_db(batch)
            batch = []
        time.sleep(random.uniform(0, 1)) # 0~1초 무작위 지연
    if batch:
        save_articles_to_db(batch)

    if progress_callback:
        progress_callback(f"크롤링 완료. 총 {len(fetched_articles_details)}개의 기사 상세 내용을 수집했습니다.", 1.0, len(fetched_articles_details))
    return fetched_articles_details

if __name__ == '__main__':
    print("크롤러 모듈 단독 실행 테스트:")
    # 테스트를 위한 임시 콜백 함수
    def test_progress_callback(message, progress_val, total_count):
        print(f"Status: {message} | Progress: {progress_val*100:.1f}% | Total: {total_count}")

    test_query = "한화에어로스페이스"
    test_articles = fetch_all_hankyung_articles(
        query=test_query,
        sort="DATE/DESC,RANK/DESC",
        max_pages=1, # 테스트를 위해 1페이지만 가져오도록 설정
        sleep_time=1,
        progress_callback=test_progress_callback
    )
    print("\n--- 수집된 기사 상세 정보 (최대 3개 출력) ---")
    for i, article in enumerate(test_articles[:3]):
        print(f"[{i+1}]")
        print(f"  제목: {article.get('제목', 'N/A')}")
        print(f"  작성일자: {article.get('작성일자', 'N/A')}")
        print(f"  기자: {article.get('기자', 'N/A')}")
        print(f"  URL: {article.get('기사 URL', 'N/A')}")
        print(f"  기사 원문 요약: {article.get('기사 원문', 'N/A')[:200]}...") # 원문이 너무 길 수 있으니 일부만 출력
        print("-" * 50)
    print(f"총 {len(test_articles)}개의 기사 상세 내용을 테스트로 가져왔습니다.")