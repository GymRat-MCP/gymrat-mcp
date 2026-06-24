import re


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
    "벤치프레스": ["벤치", "벤치프레스", "바벨벤치", "bench"],
    "인클라인벤치프레스": ["인클", "인클벤치", "인클라인"],
    "스쿼트": ["스쿼트", "스콰트", "백스쿼트", "squat"],
    "데드리프트": ["데드", "데드리프트", "deadlift"],
    "오버헤드프레스": ["오버헤드프레스", "ohp", "숄더프레스"],
    "바벨로우": ["바벨로우", "벤트오버로우", "로우"],
    "풀업": ["풀업", "턱걸이", "pullup"],
    "랫풀다운": ["랫풀", "랫풀다운"],
    "레그프레스": ["레그프레스", "legpress"],
    "레그컬": ["레그컬", "라잉레그컬"],
    "덤벨컬": ["덤벨컬", "이두컬", "바이셉컬"],
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
    needs = []

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
        # 지원 형식:
        # 5x5, 3X10, 4×8, 3*12
        sets = None
        reps = None

        sr = re.search(r"(\d+)\s*[xX×*]\s*(\d+)", seg)

        if sr:
            sets = int(sr.group(1))
            reps = int(sr.group(2))

        # ── 3. 무게 추출 ───────────────────────────────────
        # 세트x반복 부분을 먼저 제거
        # 예: "벤치 70 5x5" → "벤치 70 "
        rest = re.sub(r"\d+\s*[xX×*]\s*\d+", "", seg)

        # 남은 문자열에서 첫 번째 숫자를 무게로 판단
        # 예: "벤치 70 " → 70
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

        # ── 5. 누락된 정보 확인 ────────────────────────────
        # 무게, 세트, 반복 중 빠진 값이 있으면 확인 필요 목록에 추가
        miss = [
            key
            for key in ("weight", "sets", "reps")
            if item[key] is None
        ]

        if miss:
            kor = {
                "weight": "무게",
                "sets": "세트",
                "reps": "반복",
            }

            needs.append(
                f"{name}: {'·'.join(kor[key] for key in miss)} 누락"
            )

    return parsed, needs