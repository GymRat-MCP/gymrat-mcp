"""기존 WorkoutLog.parsed 를 ExerciseSet 로 1회 백필(P0).

듀얼라이트 도입 이전에 쌓인 세션 기록을 세트 단위 테이블로 전개한다.
log_id 로 이미 백필된 로그는 건너뛰므로 여러 번 돌려도 안전(idempotent).

실행:
    python -m db.backfill_exercise_sets
배포(도커):
    docker compose -f docker-compose.prod.yml exec server python -m db.backfill_exercise_sets
"""
from db.session import SessionLocal, init_db
from db.models import WorkoutLog, ExerciseSet
from tools.logging_tools import _expand_to_sets


def backfill() -> dict:
    session = SessionLocal()
    created = 0
    scanned = 0
    skipped = 0
    try:
        # 이미 세트가 있는 로그 id 집합(중복 방지)
        done = {row[0] for row in session.query(ExerciseSet.log_id)
                .filter(ExerciseSet.log_id.isnot(None)).distinct()}
        for log in session.query(WorkoutLog).order_by(WorkoutLog.id):
            scanned += 1
            if log.id in done:
                skipped += 1
                continue
            rows = _expand_to_sets(log.parsed or [], log.user_id, log.date, log.id)
            for r in rows:
                session.add(r)
            created += len(rows)
        session.commit()
        return {"scanned": scanned, "skipped": skipped, "created_sets": created}
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


if __name__ == "__main__":
    init_db()   # 스키마 최신화(0003 포함) 보장 후 백필
    result = backfill()
    print(f"백필 완료: 스캔 {result['scanned']}개 로그, "
          f"건너뜀 {result['skipped']}개, 생성 {result['created_sets']}세트")
