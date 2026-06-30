"""GymRat MCP — FastMCP 서버 진입점

server.py는 얇게 유지한다: 툴 등록만. 로직은 tools/ 안에.
전송: Streamable HTTP (원격 Endpoint 등록용).
"""
import os

from fastmcp import FastMCP

from db.session import init_db, SessionLocal
from db.models import ExerciseLibrary
from db.seed_exercises import seed
from tools import profile, logging_tools, analysis, routine, coaching

mcp = FastMCP("gymrat-mcp")


# ---- 프로필 ----
@mcp.tool()
def get_profile(user_id: str) -> dict:
    """사용자의 저장된 PT 프로필(목표·경력·부상·페르소나)을 조회한다."""
    return profile.get_profile(user_id)


@mcp.tool()
def update_profile(user_id: str, goal: str | None = None,
                   experience: str | None = None,
                   injuries: str | None = None,
                   persona: str | None = None,
                   summary_context: str | None = None) -> dict:
    """프로필을 생성/부분 갱신한다(전달된 필드만).
    goal: 증량|감량|유지. experience: 초보|중급|고급. persona: 천사|악마|코치|현실파이터.
    injuries: 부위를 포함한 자유 텍스트(예: "오른쪽 어깨 회전근개")—루틴에서 자극 동작 회피에 사용.
    값은 반드시 한글로 보내라(영문/변형도 내부 정규화하지만 한글이 가장 정확)."""
    return profile.update_profile(user_id, goal, experience, injuries,
                                  persona, summary_context)


# ---- 기록 ----
@mcp.tool()
def log_weight(user_id: str, weight: float, body_fat: float | None = None,
               date: str | None = None) -> dict:
    """체중(kg)과 선택적 체지방률을 기록한다."""
    return logging_tools.log_weight(user_id, weight, body_fat, date)


@mcp.tool()
def log_inbody(user_id: str, weight: float | None = None,
               skeletal_muscle: float | None = None,
               body_fat_pct: float | None = None,
               measured_date: str | None = None,
               raw_note: str | None = None) -> dict:
    """인바디 사진에서 추출한 수치를 저장하고 프로필에 반영한다."""
    return logging_tools.log_inbody(user_id, weight, skeletal_muscle,
                                    body_fat_pct, measured_date, raw_note)


@mcp.tool()
def log_workout(user_id: str, raw_text: str,
                exercises: list[dict] = None,
                date: str = None,
                confirm_with_history: bool = True) -> dict:
    """운동 기록을 저장한다.
    raw_text: 사용자가 말한 원문 그대로.
    exercises: 원문을 파싱한 구조화 배열. 각 항목은
    {exercise: str, weight: float|null, sets: int|null, reps: int|null}.
    맨몸운동은 weight=null. 반드시 exercise/weight/sets/reps 키로 분해해 넘겨라.
    confirm_with_history=True(기본)면 weight 누락 시 이전 기록에서 자동으로 채운다.
    """
    return logging_tools.log_workout(
        user_id, raw_text, exercises, date, confirm_with_history)


@mcp.tool()
def log_meal(user_id: str, photo_analysis: str,
             meal_time: str | None = None) -> dict:
    """식단 사진 분석 결과를 저장하고 질적 코멘트를 단다(수치 처방 X)."""
    return logging_tools.log_meal(user_id, photo_analysis, meal_time)


# ---- 분석 ----
@mcp.tool()
def analyze_trend(user_id: str, metric: str = "weight",
                  period_days: int = 30) -> dict:
    """추세 분석. metric: weight|volume|inbody|meal."""
    return analysis.analyze_trend(user_id, metric, period_days)


# ---- 처방·코칭 ----
@mcp.tool()
def generate_routine(user_id: str, focus: str | None = None,
                     available_days: int = 3,
                     session_minutes: int | None = None) -> dict:
    """목표·이력 기반 운동 루틴을 처방한다(점진적 과부하 + 자세 큐 + 부상 회피).
    focus(선택): 반드시 한글 부위명 하나로 — 가슴|등|어깨|하체|이두|삼두|팔|코어|종아리.
    "lower body" 같은 영문/변형은 내부에서 한글로 매핑하며, 미지정·미인식 시
    available_days(1~6, 범위 밖은 클램프) 기반 분할로 폴백한다(빈 루틴 반환 안 함).
    session_minutes: 분 단위(종목 수 산정에 사용)."""
    return routine.generate_routine(user_id, focus, available_days, session_minutes)


@mcp.tool()
def generate_meal_plan(user_id: str, goal_override: str | None = None,
                       preferences: str | None = None,
                       schedule: list[str] | None = None) -> dict:
    """질적 식단 가이드를 끼니별로 구성하고 톡캘린더 알림 이벤트를 만든다."""
    return coaching.generate_meal_plan(user_id, goal_override, preferences, schedule)


@mcp.tool()
def get_recommendation(user_id: str) -> dict:
    """식단·추세·방향성을 종합한 질적 코칭 한 마디."""
    return coaching.get_recommendation(user_id)


if __name__ == "__main__":
    init_db()
    # 운동 라이브러리가 비어있으면(새 DB) 1회 적재
    _s = SessionLocal()
    try:
        if _s.query(ExerciseLibrary).count() == 0:
            seed()
    finally:
        _s.close()
    # Streamable HTTP 전송으로 기동 (원격 Endpoint)
    # PORT는 호스팅 환경(Lightsail/PaaS)이 주입할 수 있으므로 env 우선
    mcp.run(transport="http", host="0.0.0.0", port=int(os.getenv("PORT", "8000")))
