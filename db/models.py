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
    persona         = Column(String, default="코치")      # "천사" | "악마" | "코치" | "현실파이터"
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


class ExerciseLibrary(Base):
    """정적 데이터 — seed_exercises.py로 초기 적재, 이후 read-only"""
    __tablename__ = "exercise_library"

    id        = Column(Integer, primary_key=True, autoincrement=True)
    name      = Column(String, nullable=False, unique=True)   # "벤치프레스"
    target    = Column(String, nullable=False)                 # "가슴" | "하체" | ...
    equipment = Column(String, nullable=True)                  # "바벨" | "덤벨" | "맨몸"
    form_cues = Column(JSON, nullable=True)                    # ["어깨 내리기", "코어 긴장"]
