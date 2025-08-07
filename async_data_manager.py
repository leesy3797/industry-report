import aiosqlite # 비동기 SQLite 드라이버 임포트
import pandas as pd
import os
import asyncio # 비동기 테스트를 위해 필요
import datetime # 리포트 저장 시 사용
from typing import List, Dict, Any, Optional

DATABASE_FILE = "articles.db" # 데이터베이스 파일 이름
REPORTS_DATABASE_FILE = "reports.db" # 리포트 데이터베이스 파일 이름

async def initialize_db():
    """
    SQLite 데이터베이스를 비동기적으로 초기화하고 articles 테이블을 생성합니다.
    테이블이 이미 존재하면 생성하지 않습니다.
    """
    try:
        async with aiosqlite.connect(DATABASE_FILE) as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS articles (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT NOT NULL, -- 사용자명 컬럼 추가
                    title TEXT NOT NULL,
                    publish_date TEXT,
                    author TEXT,
                    content TEXT,
                    url TEXT UNIQUE NOT NULL, -- URL은 사용자별로 고유해야 함
                    suitability_score INTEGER DEFAULT NULL,
                    company TEXT -- 기업명 컬럼 추가
                );
            """)
            await db.commit()
        print(f"데이터베이스 '{DATABASE_FILE}' 및 'articles' 테이블이 성공적으로 비동기 초기화되었습니다.")
    except aiosqlite.Error as e:
        print(f"데이터베이스 비동기 초기화 중 오류 발생: {e}")

async def initialize_reports_db():
    """
    SQLite 데이터베이스를 비동기적으로 초기화하고 reports 테이블을 생성합니다.
    """
    try:
        async with aiosqlite.connect(REPORTS_DATABASE_FILE) as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS reports (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT NOT NULL, -- 사용자명 컬럼 추가
                    report_type TEXT NOT NULL,
                    company TEXT NOT NULL,
                    year INTEGER NOT NULL,
                    month INTEGER,
                    content TEXT,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(report_type, company, year, month)
                );
            """)
            await db.commit()
        print(f"데이터베이스 '{REPORTS_DATABASE_FILE}' 및 'reports' 테이블이 성공적으로 비동기 초기화되었습니다.")
    except aiosqlite.Error as e:
        print(f"리포트 데이터베이스 비동기 초기화 중 오류 발생: {e}")


async def reset_articles_db(username: str = None): # username 인자 추가
    """
    기존 articles.db 파일을 삭제하고, 새로 비동기적으로 초기화하거나 특정 사용자의 기사만 삭제합니다.
    username이 제공되면 해당 사용자의 기사만 삭제합니다.
    """
    try:
        async with aiosqlite.connect(DATABASE_FILE) as db:
            if username:
                await db.execute("DELETE FROM articles WHERE username = ?;", (username,))
                print(f"'{username}' 사용자의 기사가 데이터베이스에서 비동기적으로 삭제되었습니다.")
            else:
                # 모든 사용자 기사 삭제 (기존 동작)
                await db.execute("DELETE FROM articles;")
                print(f"모든 기사가 데이터베이스에서 비동기적으로 삭제되었습니다.")
            await db.commit()
    except aiosqlite.Error as e:
        print(f"데이터베이스 비동기 리셋 중 오류 발생: {e}")
    # 삭제 후 테이블이 비어있을 수 있으므로 초기화는 initialize_db에서 처리
    await initialize_db() # 테이블 구조는 유지하되, 데이터만 삭제 후 다시 초기화

async def save_articles_to_db(articles: list[dict], username: str): # username 인자 추가
    """
    크롤링된 기사 목록을 SQLite 데이터베이스에 비동기적으로 저장합니다.
    기사 URL이 이미 존재하면 해당 기사는 저장하지 않습니다 (중복 방지).
    """
    if not articles:
        print("저장할 기사가 없습니다.")
        return

    try:
        async with aiosqlite.connect(DATABASE_FILE) as db:
            # 중복 방지를 위한 사전 조회 (사용자명과 URL 기준으로 중복 체크)
            existing_urls = set()
            async with db.execute("SELECT url FROM articles WHERE username = ?;", (username,)) as cursor:
                async for row in cursor:
                    existing_urls.add(row[0])

            articles_to_insert = []
            for article in articles:
                url = article.get("기사 URL")
                company = article.get("기업명") or article.get("company")
                
                if not url or not article.get("제목") or not article.get("기사 원문"):
                    print(f"경고: 필수 정보(제목, URL, 기사 원문)가 누락된 기사가 있습니다. 건너뜁니다: {article.get('제목', 'N/A')}")
                    continue

                # 사용자별로 URL이 고유하도록 체크
                if url not in existing_urls:
                    articles_to_insert.append((
                        username, # 사용자명 추가
                        article.get("제목"),
                        article.get("작성일자"),
                        article.get("기자"),
                        article.get("기사 원문"),
                        url,
                        company
                    ))
                else:
                    print(f"알림: '{username}' 사용자의 이미 존재하는 기사입니다. 건너뜁니다: {article.get('제목')} - {url}")

            if articles_to_insert:
                await db.executemany("""
                    INSERT INTO articles (username, title, publish_date, author, content, url, company)
                    VALUES (?, ?, ?, ?, ?, ?, ?);
                """, articles_to_insert)
                await db.commit()
                print(f"총 {len(articles_to_insert)}개의 새로운 기사가 데이터베이스에 비동기적으로 저장되었습니다.")
            else:
                print("새로 저장할 기사가 없습니다 (모두 이미 존재하거나 유효하지 않음).")

    except aiosqlite.Error as e:
        print(f"데이터베이스 비동기 저장 중 오류 발생: {e}")

async def load_articles_from_db(username: str = None) -> list[dict]: # username 인자 추가 (선택 사항)
    """
    SQLite 데이터베이스에서 기사를 비동기적으로 불러와 리스트[dict] 형태로 반환합니다.
    username이 제공되면 해당 사용자의 기사만 불러옵니다.
    """
    articles = []
    try:
        async with aiosqlite.connect(DATABASE_FILE) as db:
            if username:
                cursor = await db.execute("SELECT id, username, title, publish_date, author, content, url, suitability_score, company FROM articles WHERE username = ?;", (username,))
            else:
                cursor = await db.execute("SELECT id, username, title, publish_date, author, content, url, suitability_score, company FROM articles;")
            
            async for row in cursor:
                articles.append({
                    "id": row[0],
                    "username": row[1], # 사용자명 추가
                    "제목": row[2],
                    "작성일자": row[3],
                    "기자": row[4],
                    "기사 원문": row[5],
                    "기사 URL": row[6],
                    "suitability_score": row[7],
                    "기업명": row[8]
                })
        print(f"데이터베이스에서 총 {len(articles)}개의 기사를 비동기적으로 불러왔습니다.")
    except aiosqlite.Error as e:
        print(f"데이터베이스에서 기사를 비동기적으로 불러오는 중 오류 발생: {e}")
    return articles

async def update_article_suitability_score(article_id: int, score: int):
    """
    주어진 기사 ID에 대해 AI 적합도 점수(suitability_score)를 비동기적으로 업데이트합니다.
    """
    try:
        async with aiosqlite.connect(DATABASE_FILE) as db:
            await db.execute(
                "UPDATE articles SET suitability_score = ? WHERE id = ?;",
                (score, article_id)
            )
            await db.commit()
        # print(f"기사 ID {article_id}의 적합도 점수가 {score}로 비동기 업데이트되었습니다.")
    except aiosqlite.Error as e:
        print(f"기사 ID {article_id}의 적합도 점수 비동기 업데이트 중 오류 발생: {e}")

async def save_report_to_db(username: str, report_type: str, query: str, content: str, year: int = datetime.datetime.now().year, month: Optional[int] = None):
    """
    생성된 리포트를 reports.db에 비동기적으로 저장합니다.
    기존에 동일한 리포트가 있으면 메시지만 출력하고 저장하지 않습니다.
    """
    try:
        async with aiosqlite.connect(REPORTS_DATABASE_FILE) as db:
            # 중복 방지를 위해 username, report_type, company, year, month를 기준으로 체크
            # 월별 보고서: year와 month를 모두 사용
            # 연간/키워드/트렌드 보고서: month는 NULL로 처리
            
            # 먼저 기존에 동일한 조건의 레코드가 있는지 확인
            if report_type == "monthly":
                cursor = await db.execute(
                    "SELECT id FROM reports WHERE username = ? AND report_type = ? AND company = ? AND year = ? AND month = ?;",
                    (username, report_type, query, year, month)
                )
            else:
                cursor = await db.execute(
                    "SELECT id FROM reports WHERE username = ? AND report_type = ? AND company = ? AND year = ? AND month IS NULL;",
                    (username, report_type, query, year)
                )
            existing_report = await cursor.fetchone()

            if existing_report:
                # 이미 존재하면 메시지만 출력하고 함수 종료
                if report_type == "monthly":
                    print(f"알림: {year}년 {month}월 '{query}'에 대한 '{report_type}' 리포트가 이미 존재합니다. 새로운 내용을 저장하지 않습니다.")
                else:
                    print(f"알림: {year}년 '{query}'에 대한 '{report_type}' 리포트가 이미 존재합니다. 새로운 내용을 저장하지 않습니다.")
                return
            else:
                # 존재하지 않으면 새로 삽입
                await db.execute(
                    "INSERT INTO reports (username, report_type, company, content, year, month, timestamp) VALUES (?, ?, ?, ?, ?, ?, ?);",
                    (username, report_type, query, content, year, month, datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
                )
                print(f"리포트 '{report_type}' (쿼리: '{query}', 연도: '{year}', 월: '{month}')가 '{username}' 사용자로 저장되었습니다.")
            
            await db.commit()
            
    except aiosqlite.Error as e:
        print(f"리포트 저장 중 오류 발생: {e}")

async def load_reports_from_db(username: str = None, report_type: str = None, query: str = None, year: int = None, month: int = None) -> list[dict]:
    """
    reports.db에서 리포트를 비동기적으로 불러옵니다.
    username, report_type, query, year, month를 기준으로 필터링할 수 있습니다.
    """
    reports = []
    try:
        async with aiosqlite.connect(REPORTS_DATABASE_FILE) as db:
            query_parts = []
            params = []

            if username:
                query_parts.append("username = ?")
                params.append(username)
            if report_type:
                query_parts.append("report_type = ?")
                params.append(report_type)
            if query:
                query_parts.append("company = ?")
                params.append(query)
            
            # year와 month 컬럼을 직접 필터링
            if year:
                query_parts.append("year = ?")
                params.append(year)
            # month가 None일 경우, month 컬럼이 NULL인 레코드를 찾음
            if month:
                query_parts.append("month = ?")
                params.append(month)
            
            sql = "SELECT id, username, report_type, company, content, timestamp, year, month FROM reports"
            if query_parts:
                sql += " WHERE " + " AND ".join(query_parts)
            sql += " ORDER BY timestamp DESC;"

            cursor = await db.execute(sql, tuple(params))
            
            async for row in cursor:
                reports.append({
                    "id": row[0],
                    "username": row[1],
                    "report_type": row[2],
                    "company": row[3],
                    "content": row[4],
                    "timestamp": row[5],
                    "year": row[6],
                    "month": row[7]
                })
        print(f"데이터베이스에서 총 {len(reports)}개의 리포트를 비동기적으로 불러왔습니다.")
    except aiosqlite.Error as e:
        print(f"리포트 불러오는 중 오류 발생: {e}")
    return reports

# 모듈 단독 실행 시 테스트 코드
if __name__ == "__main__":
    print("--- data_manager.py 모듈 테스트 시작 ---")
    
    async def test_main():
        # 기존 DB 파일이 있다면 삭제 (테스트용)
        if os.path.exists(DATABASE_FILE):
            os.remove(DATABASE_FILE)
            print(f"기존 '{DATABASE_FILE}' 파일 삭제.")
        if os.path.exists(REPORTS_DATABASE_FILE):
            os.remove(REPORTS_DATABASE_FILE)
            print(f"기존 '{REPORTS_DATABASE_FILE}' 파일 삭제.")

        await initialize_db()
        await initialize_reports_db()

        test_username_1 = "이승용"
        test_username_2 = "김철수"

        # 가상의 크롤링 데이터
        test_articles_1 = [
            {"제목": "한화에어로스페이스, 2024년 역대 최대 실적 달성", "작성일자": "2024-02-15", "기자": "김한국", "기사 원문": "한화에어로스페이스가 2024년...", "기사 URL": "http://www.hankyung.com/news/article_1", "기업명": "한화에어로스페이스"},
            {"제목": "우주산업 경쟁 심화, 한화에어로스페이스의 전략은?", "작성일자": "2023-11-01", "기자": "이우주", "기사 원문": "전 세계 우주 산업의 경쟁이...", "기사 URL": "http://www.hankyung.com/news/article_2", "기업명": "한화에어로스페이스"},
            {"제목": "단풍놀이, 이번 주말이 절정", "작성일자": "2024-10-20", "기자": "박자연", "기사 원문": "가을 단풍이 절정에 달하며...", "기사 URL": "http://www.hankyung.com/news/article_3", "기업명": "한화에어로스페이스"} 
        ]
        test_articles_2 = [
            {"제목": "삼성전자, AI 반도체 시장 선도", "작성일자": "2024-05-20", "기자": "박반도", "기사 원문": "삼성전자가 AI 반도체...", "기사 URL": "http://www.hankyung.com/news/article_samsung1", "기업명": "삼성전자"},
        ]

        print("\n--- 첫 번째 사용자 기사 목록 비동기 저장 시도 ---")
        await save_articles_to_db(test_articles_1, test_username_1)

        print("\n--- 두 번째 사용자 기사 목록 비동기 저장 시도 ---")
        await save_articles_to_db(test_articles_2, test_username_2)

        print(f"\n--- DB에서 '{test_username_1}' 사용자의 기사 불러오기 ---")
        loaded_articles_1 = await load_articles_from_db(test_username_1)
        for article in loaded_articles_1:
            print(f"- ID: {article['id']}, 사용자: {article['username']}, 제목: {article['제목']}, URL: {article['기사 URL']}")

        print(f"\n--- DB에서 '{test_username_2}' 사용자의 기사 불러오기 ---")
        loaded_articles_2 = await load_articles_from_db(test_username_2)
        for article in loaded_articles_2:
            print(f"- ID: {article['id']}, 사용자: {article['username']}, 제목: {article['제목']}, URL: {article['기사 URL']}")
        
        print("\n--- 적합도 점수 비동기 업데이트 테스트 ---")
        if loaded_articles_1:
            article_id_to_update = loaded_articles_1[0]['id']
            print(f"기사 ID {article_id_to_update}의 적합도 점수를 1로 비동기 업데이트 시도...")
            await update_article_suitability_score(article_id_to_update, 1)

        print("\n--- 리포트 비동기 저장 테스트 ---")
        await save_report_to_db(test_username_1, "연간 이슈 분석", "한화에어로스페이스", "한화에어로스페이스 연간 이슈 분석 리포트 내용...")
        await save_report_to_db(test_username_2, "미래 모습 보고서", "삼성전자", "삼성전자 미래 모습 보고서 내용...")

        print(f"\n--- '{test_username_1}' 사용자의 리포트 불러오기 ---")
        loaded_reports_1 = await load_reports_from_db(test_username_1)
        for report in loaded_reports_1:
            print(f"- ID: {report['id']}, 사용자: {report['username']}, 유형: {report['report_type']}, 기업명: {report['company']}")

        print("\n--- data_manager.py 모듈 테스트 종료 ---")
    
    asyncio.run(test_main())
