import re
from datetime import date as _date_cls, datetime, timedelta


# ── 상대 날짜 파싱 (P4: 온보딩·백필) ───────────────────────
# "3주 전 벤치 70 했었어" 같은 과거 기록을 실제 날짜로 저장하기 위한 순수 함수.
# 호스트 LLM이 date를 채워주는 게 1차 경로지만, 서버도 결정론적으로 폴백한다.
_WEEKDAY_KO = {"월": 0, "화": 1, "수": 2, "목": 3, "금": 4, "토": 5, "일": 6}


def parse_relative_date(text: str, today: _date_cls | None = None) -> _date_cls | None:
    """한글 상대 날짜 표현을 실제 date로 변환한다(과거 방향).

    지원: 오늘/어제/그제·그저께/그끄제, N일 전, N주 전, 지난주/지지난주,
          N달·N개월 전, 지난달, "월~일요일"(가장 최근 지난 해당 요일).
    인식 불가/빈 문자열이면 None(호출부가 오늘로 폴백).
    """
    if not text:
        return None
    t = text.strip()
    base = today or datetime.now().date()

    if "오늘" in t:
        return base
    if "그끄제" in t or "그끄저께" in t:
        return base - timedelta(days=3)
    if "그제" in t or "그저께" in t:
        return base - timedelta(days=2)
    if "어제" in t:
        return base - timedelta(days=1)
    if "지지난주" in t:
        return base - timedelta(weeks=2)
    if "지난주" in t:
        return base - timedelta(weeks=1)
    if "지난달" in t or "지난 달" in t:
        return base - timedelta(days=30)

    m = re.search(r"(\d+)\s*일\s*전", t)
    if m:
        return base - timedelta(days=int(m.group(1)))
    m = re.search(r"(\d+)\s*주\s*전", t)
    if m:
        return base - timedelta(weeks=int(m.group(1)))
    m = re.search(r"(\d+)\s*(?:달|개월)\s*전", t)
    if m:
        return base - timedelta(days=30 * int(m.group(1)))

    m = re.search(r"([월화수목금토일])\s*요일", t)
    if m:
        target = _WEEKDAY_KO[m.group(1)]
        delta = (base.weekday() - target) % 7
        delta = delta or 7          # 같은 요일이면 '지난' 그 요일(7일 전)
        return base - timedelta(days=delta)

    return None


# ── 볼륨 계산 ──────────────────────────────────────────────
def session_volume(parsed) -> float:
    """
    한 번의 운동 세션에서 총 볼륨을 계산한다.
    볼륨 공식: 무게 × 세트 수 × 반복 수
    예: 벤치 70kg 5세트 5회 → 70 * 5 * 5 = 1750
    """
    if not parsed:
        return 0.0

    total = 0.0

    for item in parsed:
        # 각 운동 항목에서 무게, 세트, 반복 횟수 가져오기
        w = item.get("weight")
        s = item.get("sets")
        r = item.get("reps")

        # 무게/세트/반복 중 하나라도 없으면 볼륨 계산에서 제외
        # 예: 풀업, 맨몸운동, 입력 누락 등
        if w is None or s is None or r is None:
            continue

        # 운동별 볼륨을 누적
        total += w * s * r

    return total


# ── 운동 표준명 사전 ───────────────────────────────────────
_CANON = {
    # key: 저장할 표준 운동명
    # value: 사용자가 입력할 수 있는 별칭들
    # ── 가슴 ──
    "벤치프레스": ["벤치", "벤치프레스", "바벨벤치", "bench"],
    "인클라인벤치프레스": ["인클", "인클벤치", "인클라인", "인클라인벤치프레스"],
    "덤벨벤치프레스": ["덤벨벤치", "덤벨벤치프레스", "dbbench"],
    "딥스": ["딥스", "딥", "dips", "dip"],
    "체스트프레스": ["체스트프레스", "체스트", "머신벤치", "chestpress"],
    "케이블플라이": ["케이블플라이", "플라이", "펙덱", "fly"],
    # ── 등 ──
    "데드리프트": ["데드", "데드리프트", "deadlift"],
    "바벨로우": ["바벨로우", "벤트오버로우", "로우", "row"],
    "풀업": ["풀업", "턱걸이", "pullup", "친업", "chinup"],
    "랫풀다운": ["랫풀", "랫풀다운", "latpulldown"],
    "시티드로우": ["시티드로우", "케이블로우", "seatedrow"],
    # ── 어깨 ──
    "오버헤드프레스": ["오버헤드프레스", "ohp", "숄더프레스", "밀리터리프레스", "shoulderpress"],
    "사이드레터럴레이즈": ["사레레", "레터럴레이즈", "사이드레터럴레이즈", "사이드레이즈", "lateralraise"],
    "페이스풀": ["페이스풀", "facepull"],
    # ── 하체 ──
    "스쿼트": ["스쿼트", "스콰트", "백스쿼트", "squat"],
    "레그프레스": ["레그프레스", "legpress"],
    "레그컬": ["레그컬", "라잉레그컬", "legcurl"],
    "레그익스텐션": ["레그익스텐션", "레그익텐", "legextension"],
    "런지": ["런지", "lunge"],
    "힙쓰러스트": ["힙쓰러스트", "힙스러스트", "hipthrust"],
    "카프레이즈": ["카프레이즈", "카프", "calfraise"],
    # ── 팔 ──
    "덤벨컬": ["덤벨컬", "이두컬", "바이셉컬", "dumbbellcurl"],
    "바벨컬": ["바벨컬", "바벨이두컬", "barbellcurl"],
    "해머컬": ["해머컬", "hammercurl"],
    "트라이셉스익스텐션": ["트라이셉스익스텐션", "삼두익스텐션", "라잉익스텐션", "tricepsextension"],
    "케이블푸시다운": ["케이블푸시다운", "푸시다운", "프레스다운", "pushdown"],
    # ── 코어 ──
    "플랭크": ["플랭크", "plank"],
    "크런치": ["크런치", "윗몸일으키기", "crunch", "situp"],
}


# ── 문자열 정규화 함수 ─────────────────────────────────────
def _key(s: str) -> str:
    """
    운동명을 비교하기 쉽게 변환한다.
    - 앞뒤 공백 제거
    - 대소문자 통일
    - 중간 공백 제거

    예:
    'Bench Press' → 'benchpress'
    ' 벤치 프레스 ' → '벤치프레스'
    """
    return s.strip().lower().replace(" ", "")


# ── 별칭 → 표준명 매핑 생성 ────────────────────────────────
_ALIAS_TO_CANON = {
    _key(alias): canon
    for canon, aliases in _CANON.items()
    for alias in aliases
}


# ── 운동명 표준화 ──────────────────────────────────────────
def normalize_exercise(name: str) -> str:
    """
    사용자가 입력한 운동명을 표준 운동명으로 변환한다.
    등록된 별칭이면 표준명으로 바꾸고,
    등록되지 않은 이름이면 원본을 그대로 반환한다.

    예:
    '벤치' → '벤치프레스'
    'bench' → '벤치프레스'
    '처음보는운동' → '처음보는운동'
    """
    return _ALIAS_TO_CANON.get(_key(name), name.strip())


# ── 누락 정보 확인 메시지 ──────────────────────────────────
_FIELD_KO = {"weight": "무게", "sets": "세트", "reps": "반복"}


def needs_confirmation(parsed: list[dict]) -> list[str]:
    """parsed 항목 중 무게/세트/반복이 빠진 것을 한글 메시지로 만든다.

    자동 채움(_fill_from_history) 후 재계산에도 재사용 → 채워진 항목은
    자연히 목록에서 빠진다.
    예: [{"exercise":"풀업","weight":None,...}] → ["풀업: 무게 누락"]
    """
    msgs = []
    for item in parsed:
        miss = [k for k in ("weight", "sets", "reps") if item.get(k) is None]
        if miss:
            ex = item.get("exercise", "")
            msgs.append(f"{ex}: {'·'.join(_FIELD_KO[k] for k in miss)} 누락")
    return msgs


# ── 운동 기록 파싱 ─────────────────────────────────────────
def parse_workout(raw_text: str) -> tuple[list[dict], list[str]]:
    """
    사용자가 입력한 운동 기록 문자열을 파싱한다.

    입력 예:
    '벤치 70 5x5, 인클 60 3x10'

    반환:
    parsed = [
        {"exercise": "벤치프레스", "weight": 70.0, "sets": 5, "reps": 5},
        {"exercise": "인클라인벤치프레스", "weight": 60.0, "sets": 3, "reps": 10}
    ]

    needs_confirmation = [
        "풀업: 무게 누락"
    ]
    """
    parsed = []

    # 콤마 또는 줄바꿈 기준으로 운동 종목을 나눔
    # 예: "벤치 70 5x5, 인클 60 3x10"
    # → ["벤치 70 5x5", "인클 60 3x10"]
    for seg in re.split(r"[,\n]", raw_text):
        seg = seg.strip()

        # 빈 문자열은 무시
        if not seg:
            continue

        # ── 1. 운동명 추출 ─────────────────────────────────
        # 숫자가 나오기 전까지를 운동명으로 판단
        # 예: "벤치 70 5x5" → "벤치"
        nm = re.match(r"^([^\d]+)", seg)

        # 추출한 운동명을 표준명으로 변환
        # 예: "벤치" → "벤치프레스"
        name = normalize_exercise(nm.group(1)) if nm else seg

        # ── 2. 세트 수와 반복 수 추출 ──────────────────────
        # 매칭된 토큰은 rest에서 지워 무게 추출과 섞이지 않게 한다.
        sets = None
        reps = None
        rest = seg

        def _cut(text, match):
            # 매칭 구간을 공백으로 치환해 남은 문자열에서 제거
            return text[:match.start()] + " " + text[match.end():]

        # 2-1. 세트x반복 묶음 형식: 5x5, 3X10, 4×8, 3*12
        sr = re.search(r"(\d+)\s*[xX×*]\s*(\d+)", rest)
        if sr:
            sets = int(sr.group(1))
            reps = int(sr.group(2))
            rest = _cut(rest, sr)
        else:
            # 2-2. 한글/단위 토큰: "3세트", "10회", "12렙"
            sm = re.search(r"(\d+)\s*세트", rest)
            if sm:
                sets = int(sm.group(1))
                rest = _cut(rest, sm)
            rm = re.search(r"(\d+)\s*(?:회|렙|reps?)", rest)
            if rm:
                reps = int(rm.group(1))
                rest = _cut(rest, rm)

        # ── 3. 무게 추출 ───────────────────────────────────
        # 3-1. 단위 명시("70kg", "70 킬로")를 우선 인식
        wm = re.search(r"(\d+(?:\.\d+)?)\s*(?:kg|킬로그램|킬로)", rest)
        if wm:
            weight = float(wm.group(1))
        else:
            # 3-2. 세트/렙 토큰을 제거한 나머지에서 첫 숫자를 무게로
            wm = re.search(r"(\d+(?:\.\d+)?)", rest)
            weight = float(wm.group(1)) if wm else None

        # ── 4. 파싱 결과 저장 ──────────────────────────────
        item = {
            "exercise": name,
            "weight": weight,
            "sets": sets,
            "reps": reps,
        }

        parsed.append(item)

    # ── 5. 누락된 정보 확인 ────────────────────────────────
    # 무게/세트/반복 중 빠진 값을 한글 메시지로(자동 채움 후 재계산도 이걸 재사용)
    needs = needs_confirmation(parsed)

    return parsed, needs