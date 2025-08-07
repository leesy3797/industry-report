import asyncio
import aiohttp
from bs4 import BeautifulSoup
import time
import re
import random
from async_data_manager import save_articles_to_db
import requests

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:124.0) Gecko/20100101 Firefox/124.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (Linux; Android 13; SM-G991N) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Mobile Safari/537.36",
]

# 비동기 버전의 기사 상세 정보 추출 함수 (Semaphore 인자 추가)
async def get_article_details(session: aiohttp.ClientSession, article_url: str, semaphore: asyncio.Semaphore) -> dict:
    """
    개별 기사 URL에 비동기적으로 접근하여 제목, 작성일자, 기자, 기사 원문을 추출합니다.
    semaphore를 사용하여 동시 접속 수를 제어합니다.
    """
    details = {
        "제목": "N/A",
        "작성일자": "N/A",
        "기자": "N/A",
        "기사 원문": "N/A",
        "기사 URL": article_url
    }
    
    # 세마포어를 사용하여 동시 실행 제한
    async with semaphore:
        try:
            headers = {"User-Agent": random.choice(USER_AGENTS)}
            async with session.get(article_url, headers=headers, timeout=10) as response:
                response.raise_for_status()
                text = await response.text()
                soup = BeautifulSoup(text, 'html.parser')

                title_tag = soup.find("meta", property="og:title")
                if title_tag and "content" in title_tag.attrs:
                    details["제목"] = title_tag["content"].strip()
                elif soup.title:
                    full_title = soup.title.string
                    if full_title and '|' in full_title:
                        details["제목"] = full_title.split('|')[0].strip()
                    else:
                        details["제목"] = full_title.strip()

                published_time_tag = soup.find("meta", property="article:published_time")
                if published_time_tag and "content" in published_time_tag.attrs:
                    date_full = published_time_tag["content"].split('T')[0]
                    details["작성일자"] = date_full

                author_tag = soup.find("meta", property="dable:author")
                if author_tag and "content" in author_tag.attrs:
                    details["기자"] = author_tag["content"].strip()
                else:
                    script_tags = soup.find_all("script", type="text/javascript")
                    for script in script_tags:
                        if script.string and "GATrackingData" in script.string:
                            match = re.search(r"hk_reporter\s*:\s*'([^']+)'", script.string)
                            if match:
                                reporter_info = match.group(1)
                                details["기자"] = reporter_info.split('(')[0].strip()
                                break
                
                article_body_content = []
                article_div = soup.find("div", id="articletxt")
                if not article_div:
                    article_div = soup.find("div", class_="article-body")
                
                if article_div:
                    paragraphs = article_div.find_all("p")
                    for p in paragraphs:
                        text = p.get_text(strip=True)
                        text = re.sub(r'\s+', ' ', text).strip()
                        if text:
                            article_body_content.append(text)
                    
                    if article_body_content:
                        details["기사 원문"] = "\n\n".join(article_body_content)
                    else:
                        details["기사 원문"] = article_div.get_text(separator="\n", strip=True)
                        details["기사 원문"] = re.sub(r'\s*\n\s*', '\n', details["기사 원문"]).strip()
                
        except aiohttp.ClientError as e:
            # 429 Too Many Requests 등의 오류 메시지 확인 가능
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
    # (이 함수는 변경 없음)
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
    # (이 함수는 변경 없음)
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
                "제목_검색결과": title,
                "URL": url,
            })
        except Exception as e:
            print(f"검색 결과 기사 목록 파싱 중 오류 발생: {e} (HTML: {article_li})")
            continue
    
    return articles_data

def get_total_articles_count(html_content: str) -> int:
    # (이 함수는 변경 없음)
    soup = BeautifulSoup(html_content, 'html.parser')
    total_count_element = soup.select_one('.section.hk_news .tit-wrap .tit span')
    if total_count_element:
        total_articles_text = total_count_element.get_text(strip=True)
        match = re.search(r'/ (\d+)건', total_articles_text)
        if match:
            return int(match.group(1))
    return -1


# 비동기 버전의 전체 기사 크롤링 함수 (Semaphore 적용)
async def fetch_all_hankyung_articles(
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
    progress_callback=None,
    username: str = None
) -> list[dict]:
    """
    한국경제신문 검색 결과의 모든 페이지에서 기사 정보를 크롤링합니다.
    각 기사의 상세 페이지로 이동하여 원문을 비동기적으로 가져옵니다.
    """
    if not username:
        print("오류: 사용자명이 제공되지 않아 크롤링을 시작할 수 없습니다.")
        if progress_callback:
            progress_callback("오류: 사용자명이 제공되지 않아 크롤링을 시작할 수 없습니다.", 0.0, 0)
        return []

    all_article_urls = []
    fetched_articles_details = []
    current_page = 1
    total_articles_count = -1
    
    if progress_callback:
        progress_callback(f"[1/2단계] '{query}' 키워드로 뉴스 검색 결과 URL을 수집 중... (사용자: {username})", 0.0, 0)

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
                if progress_callback:
                    progress_callback("총 기사 수를 파악할 수 없습니다. 검색 결과 페이지의 기사만 수집합니다.", 0.0, 0)
        
        current_page_articles_meta = parse_articles_from_html(html_content)
        if not current_page_articles_meta:
            if progress_callback:
                progress_callback("[1/2단계] 더 이상 검색 결과 기사 URL이 없거나 모든 URL을 가져왔습니다.", 0.49, len(all_article_urls))
            break

        for article_meta in current_page_articles_meta:
            if article_meta["URL"] != "URL 없음":
                all_article_urls.append(article_meta["URL"])

        if progress_callback and total_articles_count != -1:
            progress_val_step1 = min(len(all_article_urls) / total_articles_count / 2, 0.5) if total_articles_count > 0 else 0.0
            progress_callback(f"[1/2단계] 기사 URL 수집 중... (현재 {len(all_article_urls)}개 수집됨 / 예상 {total_articles_count}개)", 
                              progress_val_step1, total_articles_count)
        elif progress_callback:
            progress_callback(f"[1/2단계] 기사 URL 수집 중... (현재 {len(all_article_urls)}개 수집됨)", 
                              min(current_page * 10 / 1000, 0.5), 0)

        if max_pages and current_page >= max_pages:
            if progress_callback:
                progress_callback(f"[1/2단계 완료] 최대 {max_pages} 페이지까지 URL 수집 완료. 총 {len(all_article_urls)}개.", 0.5, len(all_article_urls))
            break
        
        if total_articles_count != -1 and len(all_article_urls) >= total_articles_count:
            if progress_callback:
                progress_callback(f"[1/2단계 완료] 총 {total_articles_count}개의 기사 URL을 모두 가져왔습니다.", 0.5, total_articles_count)
            break

        current_page += 1
        time.sleep(random.uniform(0, 1))

    # 2단계: 수집된 각 URL에서 상세 내용 크롤링 (비동기 처리, Semaphore 적용)
    total_urls_to_crawl = len(all_article_urls)
    if total_urls_to_crawl == 0:
        if progress_callback:
            progress_callback("수집할 기사 URL이 없습니다.", 0.0, 0)
        return []

    if progress_callback:
        progress_callback(f"[2/2단계 시작] 총 {total_urls_to_crawl}개의 기사 상세 내용을 비동기적으로 크롤링합니다... (사용자: {username})", 0.5, total_urls_to_crawl)

    # ⭐ 수정된 부분: 세마포어 생성
    # 동시에 실행될 작업을 20개로 제한합니다. (숫자는 서버 부하에 따라 조절 가능)
    semaphore = asyncio.Semaphore(100) 

    async with aiohttp.ClientSession() as session:
        tasks = []
        for url in all_article_urls:
            # ⭐ 수정된 부분: 세마포어를 인자로 전달
            tasks.append(get_article_details(session, url, semaphore))
        
        batch = []
        for i, task in enumerate(asyncio.as_completed(tasks)):
            article_detail = await task
            article_detail["기업명"] = query
            fetched_articles_details.append(article_detail)
            
            progress_for_step2 = (i + 1) / total_urls_to_crawl
            overall_progress_value = 0.5 + (0.5 * progress_for_step2)
            if progress_callback:
                progress_callback(f"[2/2단계] 기사 상세 내용 크롤링 중... ({i+1}/{total_urls_to_crawl} 완료)", 
                                  overall_progress_value, total_urls_to_crawl)

            batch.append(article_detail)
            if len(batch) == 10:
                await save_articles_to_db(batch, username)
                batch = []
            
        if batch:
            await save_articles_to_db(batch, username)

    if progress_callback:
        progress_callback(f"크롤링 완료. 총 {len(fetched_articles_details)}개의 기사 상세 내용을 수집했습니다.", 1.0, len(fetched_articles_details))
    
    return fetched_articles_details

if __name__ == '__main__':
    print("크롤러 모듈 단독 실행 테스트 (비동기):")
    async def main():
        def test_progress_callback(message, progress_val, total_count):
            print(f"Status: {message} | Progress: {progress_val*100:.1f}% | Total: {total_count}")

        test_query = "한화에어로스페이스"
        test_username = "테스트사용자"
        test_articles = await fetch_all_hankyung_articles(
            query=test_query,
            sort="DATE/DESC,RANK/DESC",
            max_pages=2, # 테스트를 위해 2페이지로 제한
            progress_callback=test_progress_callback,
            username=test_username
        )
        print("\n--- 수집된 기사 상세 정보 (최대 3개 출력) ---")
        for i, article in enumerate(test_articles[:3]):
            print(f"[{i+1}]")
            print(f"  제목: {article.get('제목', 'N/A')}")
            print(f"  작성일자: {article.get('작성일자', 'N/A')}")
            print(f"  기자: {article.get('기자', 'N/A')}")
            print(f"  URL: {article.get('기사 URL', 'N/A')}")
            print(f"  기사 원문 요약: {article.get('기사 원문', 'N/A')[:200]}...")
            print("-" * 50)
        print(f"총 {len(test_articles)}개의 기사 상세 내용을 테스트로 가져왔습니다.")

    asyncio.run(main())