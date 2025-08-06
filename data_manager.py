import sqlite3
import pandas as pd
import os

DATABASE_FILE = "articles.db" # 데이터베이스 파일 이름

def initialize_db():
    """
    SQLite 데이터베이스를 초기화하고 articles 테이블을 생성합니다.
    테이블이 이미 존재하면 생성하지 않습니다.
    """
    conn = None
    try:
        conn = sqlite3.connect(DATABASE_FILE)
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS articles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                publish_date TEXT,
                author TEXT,
                content TEXT,
                url TEXT UNIQUE NOT NULL,
                suitability_score INTEGER DEFAULT NULL,
                company TEXT -- 기업명 컬럼 추가
            );
        """)
        conn.commit()
        print(f"데이터베이스 '{DATABASE_FILE}' 및 'articles' 테이블이 성공적으로 초기화되었습니다.")
    except sqlite3.Error as e:
        print(f"데이터베이스 초기화 중 오류 발생: {e}")
    finally:
        if conn:
            conn.close()

def reset_articles_db():
    """
    기존 articles.db 파일을 삭제하고, 새로 초기화합니다.
    """
    import os
    if os.path.exists(DATABASE_FILE):
        os.remove(DATABASE_FILE)
        print(f"기존 '{DATABASE_FILE}' 파일 삭제.")
    initialize_db()

def save_articles_to_db(articles: list[dict]):
    """
    크롤링된 기사 목록을 SQLite 데이터베이스에 저장합니다.
    기사 URL이 이미 존재하면 해당 기사는 저장하지 않습니다 (중복 방지).
    """
    if not articles:
        print("저장할 기사가 없습니다.")
        return

    conn = None
    try:
        conn = sqlite3.connect(DATABASE_FILE)
        cursor = conn.cursor()
        
        # 중복 방지를 위한 사전 조회
        existing_urls = set()
        cursor.execute("SELECT url FROM articles;")
        for row in cursor.fetchall():
            existing_urls.add(row[0])

        articles_to_insert = []
        for article in articles:
            url = article.get("기사 URL")
            company = article.get("기업명") or article.get("company")
            # 필수 필드 체크
            if not url or not article.get("제목") or not article.get("기사 원문"):
                print(f"경고: 필수 정보(제목, URL, 기사 원문)가 누락된 기사가 있습니다. 건너뜁니다: {article.get('제목', 'N/A')}")
                continue

            if url not in existing_urls:
                articles_to_insert.append((
                    article.get("제목"),
                    article.get("작성일자"),
                    article.get("기자"),
                    article.get("기사 원문"),
                    url,
                    company
                ))
            else:
                print(f"알림: 이미 존재하는 기사입니다. 건너뜁니다: {article.get('제목')} - {url}")

        if articles_to_insert:
            cursor.executemany("""
                INSERT INTO articles (title, publish_date, author, content, url, company)
                VALUES (?, ?, ?, ?, ?, ?);
            """, articles_to_insert)
            conn.commit()
            print(f"총 {len(articles_to_insert)}개의 새로운 기사가 데이터베이스에 저장되었습니다.")
        else:
            print("새로 저장할 기사가 없습니다 (모두 이미 존재하거나 유효하지 않음).")

    except sqlite3.Error as e:
        print(f"데이터베이스 저장 중 오류 발생: {e}")
    finally:
        if conn:
            conn.close()

def load_articles_from_db() -> list[dict]:
    """
    SQLite 데이터베이스에서 모든 기사를 불러와 리스트[dict] 형태로 반환합니다.
    """
    conn = None
    articles = []
    try:
        conn = sqlite3.connect(DATABASE_FILE)
        cursor = conn.cursor()
        cursor.execute("SELECT id, title, publish_date, author, content, url, suitability_score, company FROM articles;")
        rows = cursor.fetchall()
        
        for row in rows:
            articles.append({
                "id": row[0],
                "제목": row[1],
                "작성일자": row[2],
                "기자": row[3],
                "기사 원문": row[4],
                "기사 URL": row[5],
                "suitability_score": row[6],
                "기업명": row[7]
            })
        print(f"데이터베이스에서 총 {len(articles)}개의 기사를 불러왔습니다.")
    except sqlite3.Error as e:
        print(f"데이터베이스에서 기사를 불러오는 중 오류 발생: {e}")
    finally:
        if conn:
            conn.close()
    return articles

def update_article_suitability_score(article_id: int, score: int):
    """
    주어진 기사 ID에 대해 AI 적합도 점수(suitability_score)를 업데이트합니다.
    """
    conn = None
    try:
        conn = sqlite3.connect(DATABASE_FILE)
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE articles SET suitability_score = ? WHERE id = ?;",
            (score, article_id)
        )
        conn.commit()
        # print(f"기사 ID {article_id}의 적합도 점수가 {score}로 업데이트되었습니다.")
    except sqlite3.Error as e:
        print(f"기사 ID {article_id}의 적합도 점수 업데이트 중 오류 발생: {e}")
    finally:
        if conn:
            conn.close()

# 모듈 단독 실행 시 테스트 코드
if __name__ == "__main__":
    print("--- data_manager.py 모듈 테스트 시작 ---")
    
    # 기존 DB 파일이 있다면 삭제 (테스트용)
    if os.path.exists(DATABASE_FILE):
        os.remove(DATABASE_FILE)
        print(f"기존 '{DATABASE_FILE}' 파일 삭제.")

    initialize_db()

    # 가상의 크롤링 데이터
    test_articles_1 = [
        {"제목": "한화에어로스페이스, 2024년 역대 최대 실적 달성", "작성일자": "2024.02.15", "기자": "김한국", "기사 원문": "한화에어로스페이스가 2024년...", "기사 URL": "http://www.hankyung.com/news/article_1", "기업명": "한화에어로스페이스"},
        {"제목": "우주산업 경쟁 심화, 한화에어로스페이스의 전략은?", "작성일자": "2023.11.01", "기자": "이우주", "기사 원문": "전 세계 우주 산업의 경쟁이...", "기사 URL": "http://www.hankyung.com/news/article_2", "기업명": "한화에어로스페이스"},
        {"제목": "단풍놀이, 이번 주말이 절정", "작성일자": "2024.10.20", "기자": "박자연", "기사 원문": "가을 단풍이 절정에 달하며...", "기사 URL": "http://www.hankyung.com/news/article_3", "기업명": "한화에어로스페이스"} # 부적합 예상 기사
    ]

    print("\n--- 첫 번째 기사 목록 저장 시도 ---")
    save_articles_to_db(test_articles_1)

    print("\n--- DB에서 기사 불러오기 ---")
    loaded_articles_1 = load_articles_from_db()
    for article in loaded_articles_1:
        print(f"- ID: {article['id']}, 제목: {article['제목']}, URL: {article['기사 URL']}, 적합도: {article['suitability_score']}, 기업: {article['기업명']}")

    # 중복 및 새로운 기사 포함 테스트
    test_articles_2 = [
        {"제목": "한화에어로스페이스, 2024년 역대 최대 실적 달성", "작성일자": "2024.02.15", "기자": "김한국", "기사 원문": "한화에어로스페이스가 2024년...", "기사 URL": "http://www.hankyung.com/news/article_1", "기업명": "한화에어로스페이스"}, # 중복
        {"제목": "한화비전, AI 기반 보안 솔루션 강화", "작성일자": "2024.01.10", "기자": "정보기술", "기사 원문": "한화비전이 인공지능 기술을...", "기사 URL": "http://www.hankyung.com/news/article_4", "기업명": "한화비전"} # 새로운 기사
    ]

    print("\n--- 두 번째 기사 목록 저장 시도 (중복 및 새 기사) ---")
    save_articles_to_db(test_articles_2)

    print("\n--- DB에서 최종 기사 불러오기 ---")
    loaded_articles_2 = load_articles_from_db()
    for article in loaded_articles_2:
        print(f"- ID: {article['id']}, 제목: {article['제목']}, URL: {article['기사 URL']}, 적합도: {article['suitability_score']}, 기업: {article['기업명']}")
    
    print("\n--- 적합도 점수 업데이트 테스트 ---")
    # 예시: ID 1번 기사의 적합도를 1 (적합)으로 업데이트
    if loaded_articles_2:
        article_id_to_update = loaded_articles_2[0]['id'] # 첫 번째 기사 ID
        print(f"기사 ID {article_id_to_update}의 적합도 점수를 1로 업데이트 시도...")
        update_article_suitability_score(article_id_to_update, 1)

        # 예시: ID 3번 기사의 적합도를 0 (부적합)으로 업데이트 (단풍놀이 기사)
        # 실제 데이터에서 ID 3번이 '단풍놀이' 기사였으므로 테스트용으로 사용
        print(f"기사 ID 3의 적합도 점수를 0으로 업데이트 시도 (단풍놀이 기사)...")
        update_article_suitability_score(3, 0)

        print("\n--- 업데이트 후 DB에서 다시 불러오기 ---")
        loaded_articles_after_update = load_articles_from_db()
        for article in loaded_articles_after_update:
            print(f"- ID: {article['id']}, 제목: {article['제목']}, 적합도: {article['suitability_score']}, 기업: {article['기업명']}")


    print("\n--- data_manager.py 모듈 테스트 종료 ---")