"""운동 라이브러리 원천 데이터셋 → data/exercises.json 변환 (재현용).

원천: hasaneyldrm/exercises-dataset (data/exercises.json, 1,324종)
  https://github.com/hasaneyldrm/exercises-dataset
  ⚠️ 라이선스: educational and non-commercial only — 상용 배포 전 재검토 필요.

영문 muscle/equipment → 한글 매핑, instruction_steps.en → form_cues(영문 유지,
루틴 출력 시 호스트 LLM이 한글화), 휴리스틱 difficulty 부여.
종목명(name)은 영문 그대로 유지(런타임 호스트 LLM이 한글화).

    # 원천 raw JSON을 받아서:
    python -m db.build_exercises path/to/raw_exercises.json
    # → data/exercises.json 갱신
"""
import json
import sys
from pathlib import Path

OUT_PATH = Path(__file__).parent.parent / "data" / "exercises.json"

# muscle-level target(19종) → 한글 부위. 루틴 엔진의 부위 질의 기준.
TARGET_KO = {
    "pectorals": "가슴", "serratus anterior": "가슴",
    "lats": "등", "upper back": "등", "traps": "등",
    "delts": "어깨",
    "biceps": "이두",
    "triceps": "삼두",
    "forearms": "전완",
    "abs": "코어", "spine": "코어",
    "glutes": "하체", "quads": "하체", "hamstrings": "하체",
    "adductors": "하체", "abductors": "하체",
    "calves": "종아리",
    "levator scapulae": "목",
    "cardiovascular system": "유산소",
}

# equipment(28종) → 한글
EQUIPMENT_KO = {
    "body weight": "맨몸",
    "dumbbell": "덤벨",
    "cable": "케이블",
    "barbell": "바벨", "olympic barbell": "바벨",
    "ez barbell": "바벨", "trap bar": "바벨",
    "leverage machine": "머신", "smith machine": "머신", "sled machine": "머신",
    "band": "밴드", "resistance band": "밴드",
    "kettlebell": "케틀벨",
    "weighted": "가중",
    "stability ball": "볼", "bosu ball": "볼", "medicine ball": "볼",
    "assisted": "보조머신",
    "rope": "로프",
    "roller": "롤러", "wheel roller": "롤러",
    "hammer": "해머",
    "upper body ergometer": "유산소머신", "skierg machine": "유산소머신",
    "stationary bike": "유산소머신", "elliptical machine": "유산소머신",
    "stepmill machine": "유산소머신",
    "tire": "기타",
}

# 휴리스틱 난이도 — 데이터셋에 Level 없음. 바벨/케틀벨 컴파운드성 = 중급, 그 외 = 초보.
_INTERMEDIATE_EQUIP = {
    "barbell", "olympic barbell", "ez barbell", "trap bar", "kettlebell",
}


def _difficulty(equipment: str) -> str:
    return "중급" if equipment in _INTERMEDIATE_EQUIP else "초보"


def convert(raw_items: list[dict]) -> list[dict]:
    out = []
    for it in raw_items:
        equip_en = it.get("equipment", "")
        steps = (it.get("instruction_steps") or {}).get("en") or []
        if not steps and it.get("instructions", {}).get("en"):
            steps = [it["instructions"]["en"]]
        out.append({
            "name": it["name"],                                  # 영문 유지
            "target": TARGET_KO.get(it.get("target"), "기타"),    # 한글 부위
            "equipment": EQUIPMENT_KO.get(equip_en, "기타"),      # 한글 장비
            "form_cues": steps,                                  # 영문 단계(런타임 한글화)
            "secondary": it.get("secondary_muscles", []),        # 영문 보조근(원본)
            "difficulty": _difficulty(equip_en),                 # 휴리스틱
            "media": {                                           # 경로만 보관(v1 미사용)
                "image": it.get("image"),
                "gif": it.get("gif_url"),
            },
        })
    return out


def main():
    if len(sys.argv) < 2:
        print("usage: python -m db.build_exercises <raw_exercises.json>")
        raise SystemExit(1)
    raw = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    out = convert(raw)
    OUT_PATH.write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"wrote {len(out)} exercises -> {OUT_PATH}")


if __name__ == "__main__":
    main()
