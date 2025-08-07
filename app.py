import streamlit as st

# 앱 전체의 기본 페이지 설정을 합니다. (이 부분은 유지)
st.set_page_config(
    page_title="홈 | 레포트 작성",
    page_icon="🏠",
    layout="wide"
)

# st.Page를 사용하여 페이지들을 정의합니다. (이 부분도 유지)
pages = [
    # st.Page("pages/home.py", title="[Home] 레포트 작성", icon="🏠", default=True),
    st.Page("pages/async_home.py", title="[Home] 레포트 작성", icon="🏠", default=True),
    st.Page("pages/async_report_viewer_1.py", title="[1] 연도별 핵심 이슈 분석", icon="📊"),
    st.Page("pages/async_report_viewer_2.py", title="[2] 핵심 키워드 요약", icon="📝"),
    st.Page("pages/async_report_viewer_3.py", title="[3] 기업 트렌드 분석", icon="📈"),
    st.Page("pages/async_report_viewer_4.py", title="[4] 미래 모습 보고서", icon="🚀")
]

# 네비게이션 메뉴를 생성하고, 선택된 페이지 객체를 가져옵니다. (이 부분도 유지)
selected_page = st.navigation(pages)

# 가장 중요한 부분: 선택된 페이지를 실행합니다.
# 이 줄이 실행되면, selected_page가 가리키는 파일 (예: pages/report_viewer_2.py)의
# 모든 콘텐츠가 렌더링되고, 이 이후의 app.py 코드는 더 이상 해당 페이지의 일부로 동작하지 않습니다.
selected_page.run()

# --- 중요 ---
# 이 아래에는 어떤 페이지가 선택되든 항상 보여야 하는 공통 요소만 두어야 합니다.
# 예를 들어, 모든 페이지의 사이드바 하단에 로고나 저작권 정보 등을 표시하고 싶다면 여기에 작성합니다.
# 개별 페이지의 콘텐츠(예: "환영합니다! 이곳에서 새로운 레포트를 작성할 수 있습니다.")는
# 해당 페이지 파일(예: app.py 자체 또는 다른 report_viewer_X.py 파일) 내부에 있어야 합니다.

# --- 사이드바 공통 요소 ---
with st.sidebar:
    # 기존 문구
    st.info("👍 이승용님에게 따봉하나 날려주세요!")

    # 따봉 횟수를 저장할 세션 상태 초기화
    if "thumbs_up_count" not in st.session_state:
        st.session_state.thumbs_up_count = 0

    # 버튼 클릭 시 실행될 함수
    def send_thumbs_up():
        st.session_state.thumbs_up_count += 1
        st.toast("따봉 감사합니다! 🙌")
        st.balloons()

    # 따봉 버튼 추가
    st.button("따봉 날리기", on_click=send_thumbs_up, use_container_width=True)

    # 현재 따봉 횟수 표시
    if st.session_state.thumbs_up_count > 0:
        st.markdown(f"### 현재 따봉 횟수: {st.session_state.thumbs_up_count}회")

    st.write("") # 간격 조절용 빈 줄

    st.write("Created by SeungYong Lee✨")
