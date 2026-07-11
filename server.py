"""GymRat MCP — FastMCP 서버 진입점

server.py는 얇게 유지한다: 툴 등록만. 로직은 tools/ 안에.
전송: Streamable HTTP (원격 Endpoint 등록용).
"""
import os

from fastmcp import FastMCP

from db.session import init_db, SessionLocal
from db.models import ExerciseLibrary
from db.seed_exercises import seed
from tools import profile, logging_tools, analysis, routine, coaching, admin

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
                   summary_context: str | None = None,
                   available_equipment: str | None = None,
                   disliked_exercises: str | None = None) -> dict:
    """프로필을 생성/부분 갱신한다(전달된 필드만).
    goal: 증량|감량|유지. experience: 초보|중급|고급. persona: 천사|악마|코치|현실파이터.
    injuries: 부위를 포함한 자유 텍스트(예: "오른쪽 어깨 회전근개")—루틴에서 자극 동작 회피에 사용.
    available_equipment: 보유 장비(예: "덤벨,맨몸" 또는 "풀짐"/"헬스장")—루틴이 가능한 종목만 처방.
      "풀짐/헬스장"이면 필터 없음. 홈트 유저가 못 쓰는 바벨 종목을 받지 않게 한다.
    disliked_exercises: 싫어하거나 못 하는 종목(예: "버피,레그익스텐션")—루틴에서 제외.
    값은 반드시 한글로 보내라(영문/변형도 내부 정규화하지만 한글이 가장 정확)."""
    return profile.update_profile(user_id, goal, experience, injuries,
                                  persona, summary_context,
                                  available_equipment, disliked_exercises)


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
    """인바디 사진에서 추출한 수치를 저장하고 프로필에 반영한다.
    응답에 assistant_message가 있으면 사용자에게 이 문장을 우선 전달한다."""
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
    {exercise: str, weight: float|null, sets: int|null, reps: int|null, date?: str}.
    맨몸운동은 weight=null. 반드시 exercise/weight/sets/reps 키로 분해해 넘겨라.
    date(선택): "3주 전 벤치 70 했었어" 같은 과거 온보딩이면 항목별 date에
    "YYYY-MM-DD" 또는 "3주 전"/"어제" 상대표현을 넣어라(항목마다 다른 날짜 가능).
    date 파라미터: 세션 전체가 특정 과거 날짜면 여기에 넣는다(상대표현 인식).
    confirm_with_history=True(기본)면 weight 누락 시 이전 기록에서 자동으로 채운다.
    응답에 assistant_message가 있으면 사용자에게 이 문장을 우선 전달한다.
    """
    return logging_tools.log_workout(
        user_id, raw_text, exercises, date, confirm_with_history)


@mcp.tool()
def edit_workout(user_id: str, log_id: int,
                 exercises: list[dict] = None,
                 raw_text: str = None,
                 date: str = None) -> dict:
    """기존 운동 기록을 수정한다(오타 교정·날짜 정정).
    log_id: 수정할 기록 id(get_exercise_history/기록 조회로 확인).
    exercises: 수정된 전체 종목 배열(부분 수정도 전체를 다시 채워 넘긴다).
      각 항목 {exercise, weight, sets, reps, date?}. date는 "2026-06-01" 또는
      "3주 전" 같은 상대표현도 가능.
    date: 세션 전체 날짜를 옮길 때. 응답 note를 사용자에게 전달한다."""
    return logging_tools.edit_workout(user_id, log_id, exercises, raw_text, date)


@mcp.tool()
def delete_workout(user_id: str, log_id: int) -> dict:
    """잘못 남긴 운동 기록을 삭제한다(연결된 세트도 함께 제거, 통계 반영).
    log_id: 삭제할 기록 id. 모르면 먼저 get_recent_workouts로 확인한다.
    응답 note를 사용자에게 전달한다."""
    return logging_tools.delete_workout(user_id, log_id)


@mcp.tool()
def get_recent_workouts(user_id: str, limit: int = 10) -> dict:
    """최근 운동 기록을 log_id와 함께 조회한다(수정·삭제 대상 식별용).
    "아까 그거 지워줘/고쳐줘"처럼 특정 기록을 가리키면, edit_workout·delete_workout를
    부르기 전에 먼저 이 툴로 올바른 log_id를 확인한다(사용자는 id를 모른다).
    반환 workouts의 각 항목은 {log_id, date, exercises[], summary}."""
    return logging_tools.get_recent_workouts(user_id, limit)


@mcp.tool()
def log_meal(user_id: str, photo_analysis: str,
             meal_time: str | None = None) -> dict:
    """식단 텍스트를 저장하고 질적 코멘트를 단다(수치 처방 X).
    photo_analysis는 기존 호환용 이름이며, 사진 분석이 없으면 사용자의 식단 원문을 넣는다.
    응답에 pending_confirmation=true가 있으면 사용자에게 assistant_message로 확인 질문을 하고,
    답변을 confirm_meal_details로 넘겨 최종 저장한다.
    응답에 assistant_message가 있으면 사용자에게 이 문장을 우선 전달한다."""
    return logging_tools.log_meal(user_id, photo_analysis, meal_time)


@mcp.tool()
def confirm_meal_details(
    user_id: str,
    original_meal_text: str,
    clarification_text: str,
    meal_time: str | None = None,
) -> dict:
    """애매한 식단 기록의 보충 답변을 받아 최종 저장한다.
    log_meal이 pending_confirmation=true를 반환했을 때 사용한다.
    original_meal_text에는 최초 식단 원문, clarification_text에는 사용자의 추가 답변을 넣는다.
    응답에 assistant_message가 있으면 사용자에게 이 문장을 우선 전달한다."""
    return logging_tools.confirm_meal_details(
        user_id, original_meal_text, clarification_text, meal_time)


# ---- 분석 ----
@mcp.tool()
def analyze_trend(user_id: str, metric: str = "weight",
                  period_days: int = 30) -> dict:
    """추세 분석. metric: weight|volume|inbody|meal.
    응답에 assistant_message가 있으면 사용자에게 이 문장을 우선 전달한다."""
    return analysis.analyze_trend(user_id, metric, period_days)


@mcp.tool()
def get_exercise_history(user_id: str, exercise: str,
                         period_days: int = 90) -> dict:
    """특정 종목의 힘 추세를 보여준다("내 벤치가 는다"를 숫자로).
    exercise: 종목명(벤치/스쿼트/데드 등 — 서버가 정규화). 날짜별 최고중량·추정 1RM·볼륨
    시계열과 e1RM 방향성(up|down|flat)·변화율을 반환한다. 워밍업 세트는 통계 제외.
    응답에 assistant_message가 있으면 사용자에게 이 문장을 우선 전달한다."""
    return analysis.get_exercise_history(user_id, exercise, period_days)


@mcp.tool()
def get_weekly_recap(user_id: str, week_offset: int = 0) -> dict:
    """주간 운동 리캡 — 세션수·총 볼륨·부위별 볼륨·지난주 대비 변화·신규 PR·
    보완 부위를 한 번에 요약한다. week_offset=0은 최근 7일, 1은 그 이전 주.
    응답 note/nudges/assistant_message가 있으면 사용자에게 우선 전달한다."""
    return analysis.get_weekly_recap(user_id, week_offset)


@mcp.tool()
def get_goal_projection(user_id: str, exercise: str, target_weight: float,
                        by_date: str | None = None) -> dict:
    """목표 무게 도달 예상일을 투영한다("9월까지 벤치 100kg").
    exercise: 종목명(서버가 정규화). target_weight: 목표 추정 1RM(kg).
    by_date(선택, "YYYY-MM-DD"): 이 시점 안에 닿을지(on_track) 판정.
    최근 e1RM 상승률로 선형 투영하며, 정체·하락이면 도달 시점을 잡지 않는다.
    응답에 assistant_message가 있으면 사용자에게 이 문장을 우선 전달한다."""
    return analysis.get_goal_projection(user_id, exercise, target_weight, by_date)


# ---- 처방·코칭 ----
@mcp.tool()
def generate_routine(user_id: str, focus: str | None = None,
                     available_days: int = 3,
                     session_minutes: int | None = None) -> dict:
    """목표·이력 기반 운동 루틴을 처방한다(점진적 과부하 + 자세 큐 + 부상 회피).
    focus(선택): 반드시 한글 부위명 하나로 — 가슴|등|어깨|하체|이두|삼두|팔|코어|종아리.
    "lower body" 같은 영문/변형은 내부에서 한글로 매핑하며, 미지정·미인식 시
    available_days(1~6, 범위 밖은 클램프) 기반 분할로 폴백한다(빈 루틴 반환 안 함).
    session_minutes: 분 단위(종목 수 산정에 사용).
    ⚠️ 반드시 exercises 배열(종목·무게·세트·반복)을 사용자에게 목록으로 보여줘라.
    assistant_message에도 '오늘의 종목' 목록이 포함돼 있으니 이 문장을 우선 전달한다."""
    return routine.generate_routine(user_id, focus, available_days, session_minutes)


@mcp.tool()
def generate_meal_plan(user_id: str, goal_override: str | None = None,
                       preferences: str | None = None,
                       schedule: list[str] | None = None) -> dict:
    """질적 식단 가이드를 끼니별로 구성하고 톡캘린더 알림 이벤트를 만든다.
    응답에 assistant_message가 있으면 사용자에게 이 문장을 우선 전달한다."""
    return coaching.generate_meal_plan(user_id, goal_override, preferences, schedule)


@mcp.tool()
def suggest_meal_adjustment(
    user_id: str,
    current_meal_text: str | None = None,
    meal_time: str | None = None,
    goal_override: str | None = None,
    current_context: dict | None = None,
) -> dict:
    """현재 식사·최근 식단·몸 정보·운동량을 묶어 질적 식단 조정을 제안한다.
    current_context에는 이번 대화에서 입력받은 height_cm, weight_kg,
    weekly_sessions 같은 값을 넣는다. BMI는 참고 신호로만 쓰며 수치 처방은 하지 않는다.
    응답에 assistant_message가 있으면 사용자에게 이 문장을 우선 전달한다."""
    return coaching.suggest_meal_adjustment(
        user_id, current_meal_text, meal_time, goal_override, current_context)


@mcp.tool()
def get_recommendation(
    user_id: str,
    persona_override: str | None = None,
    goal_override: str | None = None,
    current_context: dict | None = None,
) -> dict:
    """식단·추세·방향성을 종합한 질적 코칭 한 마디.
    current_context에는 이번 대화에서 입력받은 수치 데이터(예: weekly_sessions,
    target_weekly_sessions, session_minutes, fatigue, sleep_quality)를 넣는다.
    current_context/persona_override/goal_override는 DB 기본값보다 우선한다.
    응답에 assistant_message가 있으면 사용자에게 이 문장을 우선 전달한다."""
    return coaching.get_recommendation(
        user_id, persona_override, goal_override, current_context)


# ---- 관리/테스트 ----
@mcp.tool()
def reset_user_data(user_id: str) -> dict:
    """사용자의 모든 기록·프로필을 삭제해 완전 초기 상태로 되돌린다(테스트용).
    운동 로그·세트·체중·인바디·식단·프로그램·프로필을 전부 지운다.
    운동 라이브러리(정적 데이터)는 유지된다. ⚠️ 되돌릴 수 없으니
    사용자가 '초기화/처음부터/리셋'을 명확히 요청했을 때만 호출한다.
    응답에 assistant_message가 있으면 사용자에게 이 문장을 우선 전달한다."""
    return admin.reset_user_data(user_id)


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
