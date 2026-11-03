"""用法：.venv/bin/python -I scripts/evaluate_research.py <人工标注JSON>。仅本地读取指定文件。"""
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.app.evaluation import EvaluationCase, evaluate_cases

if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("用法：evaluate_research.py <人工标注JSON>")
    with open(sys.argv[1], encoding="utf-8") as source:
        cases = [EvaluationCase.model_validate(value) for value in json.load(source)]
    print(json.dumps(evaluate_cases(cases), ensure_ascii=False, indent=2))
