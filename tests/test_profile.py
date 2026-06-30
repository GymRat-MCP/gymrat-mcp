"""profile 정규화 단위 테스트 — DB 불필요(순수 함수)"""
from tools.profile import normalize_goal, normalize_experience


def test_normalize_experience_variants():
    assert normalize_experience("초보자") == "초보"
    assert normalize_experience("입문") == "초보"
    assert normalize_experience("beginner") == "초보"
    assert normalize_experience("중급자") == "중급"
    assert normalize_experience("Intermediate") == "중급"
    assert normalize_experience("고급") == "고급"
    assert normalize_experience("상급자") == "고급"


def test_normalize_goal_variants():
    assert normalize_goal("벌크업") == "증량"
    assert normalize_goal("bulk") == "증량"
    assert normalize_goal("다이어트") == "감량"
    assert normalize_goal("cutting") == "감량"
    assert normalize_goal("유지") == "유지"
    assert normalize_goal("maintain") == "유지"


def test_normalize_preserves_unknown_and_none():
    # 미인식 값은 파괴하지 않고 보존
    assert normalize_goal("내맘대로목표") == "내맘대로목표"
    assert normalize_experience(None) is None
    assert normalize_goal(None) is None
