"""Grades saved mail-matrix answers again with today's case expectations, at no cost.

cd backend && uv run python evals/regrade.py evals/results/<file>.json [more files]
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import mail_eval  # noqa: E402


def main() -> None:
    print("| Model | Effort | Passed | Tokens | Seconds |\n|---|---|---|---|---|")
    for name in sys.argv[1:]:
        saved = json.loads(Path(name).read_text())
        cases = {
            c["id"]: c
            for c in json.loads((Path(__file__).parent / saved["cases_file"]).read_text())["cases"]
        }
        for run in saved["runs"]:
            passed = 0
            for result in run["results"]:
                missed = mail_eval._missed(cases[result["case"]]["want"], result["got"])
                passed += not missed
                if missed:
                    why = "; ".join(missed)
                    print(f"<!-- {run['model']} {run['effort']} {result['case']}: {why} -->")
            total = run["tokens"]["input"] + run["tokens"]["output"]
            cells = [run["model"], run["effort"], f"{passed}/{len(run['results'])}"]
            print("| " + " | ".join([*cells, f"{total:,}", str(run["seconds"])]) + " |")


if __name__ == "__main__":
    main()
