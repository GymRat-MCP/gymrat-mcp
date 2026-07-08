from sqlalchemy import (
    create_engine, Column, String, Float, Integer,
    Date, DateTime, Text, JSON
)
from sqlalchemy.orm import declarative_base
from datetime import datetime, timezone

Base = declarative_base()


class User(Base):
    __tablename__ = "users"

    id              = Column(String, primary_key=True)   # 카카오 user_id
    goal            = Column(String, nullable=True)       # "증량" | "감량" | "유지"
    experience      = Column(String, nullable=True)       # "초보" | "중급" | "고급"
    injuries        = Column(Text, nullable=True)         # 자유 텍스트
    available_equipment = Column(Text, nullable=True)     # 보유 장비 자유 텍스트(예: "덤벨,맨몸" / "풀짐"). 루틴 종목 필터
    disliked_exercises  = Column(Text, nullable=True)     # 싫어/못하는 종목(예: "버피,레그익스텐션"). 루틴에서 제외
    persona         = Column(String, default="천사")      # "천사" | "악마" | "코치" | "현실파이터"
    summary_context = Column(Text, nullable=True)         # 최근 대화 요약 (호스트 LLM 참조용)
    created_at      = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at      = Column(DateTime, default=lambda: datetime.now(timezone.utc),
                             onupdate=lambda: datetime.now(timezone.utc))


class WeightLog(Base):
    __tablename__ = "weight_logs"

    id         = Column(Integer, primary_key=True, autoincrement=True)
    user_id    = Column(String, nullable=False)
    date       = Column(Date, nullable=False)
    weight     = Column(Float, nullable=False)            # kg
    body_fat   = Column(Float, nullable=True)             # % (선택)
    logged_at  = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class InbodyLog(Base):
    __tablename__ = "inbody_logs"

    id               = Column(Integer, primary_key=True, autoincrement=True)
    user_id          = Column(String, nullable=False)
    measured_date    = Column(Date, nullable=False)
    weight           = Column(Float, nullable=True)
    skeletal_muscle  = Column(Float, nullable=True)       # kg
    body_fat_pct     = Column(Float, nullable=True)       # %
    raw_note         = Column(Text, nullable=True)        # 호스트 LLM 추출 원문
    logged_at        = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class WorkoutLog(Base):
    __tablename__ = "workout_logs"

    id          = Column(Integer, primary_key=True, autoincrement=True)
    user_id     = Column(String, nullable=False)
    date        = Column(Date, nullable=False)
    raw_text    = Column(Text, nullable=True)             # 사용자 원문
    parsed      = Column(JSON, nullable=True)             # 파싱 결과 [{exercise, weight, sets, reps}]
    logged_at   = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class MealLog(Base):
    __tablename__ = "meal_logs"

    id               = Column(Integer, primary_key=True, autoincrement=True)
    user_id          = Column(String, nullable=False)
    meal_time        = Column(String, nullable=True)      # "아침" | "점심" | "저녁" | "간식"
    photo_analysis   = Column(Text, nullable=True)        # 호스트 LLM 분석 원문
    qualitative_note = Column(Text, nullable=True)        # PT쌤 코멘트
    logged_at        = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class Program(Base):
    """주기화 프로그램 상태 — 유저당 1개 활성 블록(Phase 3, #15).

    generate_routine이 history 카운트가 아니라 이 프로그램의 '주차'를 읽어
    진행하고, deload_every 주마다 자동 디로드 주간을 잡는다.
    week는 started_at 기준으로 파생(호출마다 write 불필요, 결정론적).
    """
    __tablename__ = "programs"

    id           = Column(Integer, primary_key=True, autoincrement=True)
    user_id      = Column(String, nullable=False, unique=True)   # 유저당 1개 활성 프로그램
    split_type   = Column(Integer, nullable=False)               # 주당 훈련일(=available_days)
    started_at   = Column(Date, nullable=False)                  # 블록 시작일(주차 파생 기준)
    deload_every = Column(Integer, default=4)                    # N주마다 디로드 주간
    week_index   = Column(Integer, default=0)                    # 참고용 캐시(파생값과 동기)
    updated_at   = Column(DateTime, default=lambda: datetime.now(timezone.utc),
                          onupdate=lambda: datetime.now(timezone.utc))


class ExerciseLibrary(Base):
    """정적 데이터 — seed_exercises.py로 초기 적재, 이후 read-only"""
    __tablename__ = "exercise_library"

    id         = Column(Integer, primary_key=True, autoincrement=True)
    name       = Column(String, nullable=False, unique=True)   # 영문 "barbell bench press" (출력 시 호스트 LLM이 한글화)
    target     = Column(String, nullable=False)                # "가슴" | "하체" | ...
    equipment  = Column(String, nullable=True)                 # "바벨" | "덤벨" | "맨몸"
    form_cues  = Column(JSON, nullable=True)                   # 영문 단계 배열(출력 시 호스트 LLM이 한글화)
    secondary  = Column(JSON, nullable=True)                   # 보조근육(영문) ["forearms", ...]
    difficulty = Column(String, nullable=True)                 # 휴리스틱 "초보" | "중급"
    media      = Column(JSON, nullable=True)                   # {"image": "...", "gif": "..."} 경로(v1 미사용)
