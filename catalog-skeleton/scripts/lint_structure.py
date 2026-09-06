#!/usr/bin/env python3
"""구조 린트 + 위험도 판정.

기본 실행: 구조 위반이 있으면 종료 코드 1 (CI 하드 게이트).
--risk   : 위험도를 판정해 마크다운으로 출력한다 (승인 경로 결정용).

의존성 없음 — 표준 라이브러리만 쓴다.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PLUGINS = ROOT / "plugins"

MAX_DESC = 1536          # 항목당 description 상한 (NFR-4)
MIN_EVAL_CASES = 3       # FR-103
RISKY_PATHS = ("scripts", "hooks", ".mcp.json", "bin")   # FR-304 블랙리스트
RISKY_TOOLS = ("Bash", "Write")

errors: list[str] = []
risky: list[str] = []


def frontmatter(path: Path) -> dict[str, str]:
    """--- 로 감싼 머리말에서 최상위 key: value 만 뽑는다."""
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    if end == -1:
        return {}
    out = {}
    for line in text[3:end].splitlines():
        if ":" in line and not line.startswith((" ", "\t", "#")):
            k, _, v = line.partition(":")
            out[k.strip()] = v.strip()
    return out


def check_plugin(plugin: Path) -> None:
    name = plugin.name

    manifest = plugin / ".claude-plugin" / "plugin.json"
    if not manifest.exists():
        errors.append(f"{name}: .claude-plugin/plugin.json 없음")
    else:
        try:
            data = json.loads(manifest.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            errors.append(f"{name}: plugin.json 파싱 실패 — {e}")
            data = {}
        for field in ("name", "version", "description"):
            if not data.get(field):
                errors.append(f"{name}: plugin.json 에 '{field}' 없음")
        if data.get("name") and data["name"] != name:
            errors.append(f"{name}: plugin.json 의 name '{data['name']}' 이 디렉터리명과 다름")

    for skill_dir in sorted((plugin / "skills").glob("*/")):
        check_skill(name, skill_dir)

    for agent in sorted((plugin / "agents").glob("*.md")):
        check_agent(name, agent)

    for risky_path in RISKY_PATHS:
        if (plugin / risky_path).exists():
            risky.append(f"{name}: `{risky_path}` 존재")


def check_skill(plugin_name: str, skill_dir: Path) -> None:
    label = f"{plugin_name}/{skill_dir.name}"
    skill_md = skill_dir / "SKILL.md"
    if not skill_md.exists():
        errors.append(f"{label}: SKILL.md 없음")
        return

    fm = frontmatter(skill_md)
    if not fm.get("name"):
        errors.append(f"{label}: frontmatter 에 name 없음")
    elif fm["name"] != skill_dir.name:
        errors.append(f"{label}: name '{fm['name']}' 이 디렉터리명과 다름")

    desc = fm.get("description", "")
    if not desc:
        errors.append(f"{label}: frontmatter 에 description 없음 — 자동 발동의 유일한 근거다")
    elif len(desc) > MAX_DESC:
        errors.append(f"{label}: description 이 {len(desc)}자로 상한 {MAX_DESC}자를 초과")

    cases = skill_dir / "evals" / "cases.jsonl"
    if not cases.exists():
        errors.append(f"{label}: evals/cases.jsonl 없음 (FR-102)")
        return
    lines = [ln for ln in cases.read_text(encoding="utf-8").splitlines() if ln.strip()]
    if len(lines) < MIN_EVAL_CASES:
        errors.append(f"{label}: eval 케이스가 {len(lines)}개 — 최소 {MIN_EVAL_CASES}개 필요")
    for i, line in enumerate(lines, 1):
        try:
            json.loads(line)
        except json.JSONDecodeError:
            errors.append(f"{label}: cases.jsonl {i}행이 유효한 JSON 이 아님")


def check_agent(plugin_name: str, agent: Path) -> None:
    label = f"{plugin_name}/agents/{agent.name}"
    fm = frontmatter(agent)
    if not fm.get("description"):
        errors.append(f"{label}: description 없음")

    tools = fm.get("tools")
    if not tools:
        errors.append(f"{label}: tools 미명시 — 에이전트는 허용 도구를 반드시 선언해야 한다 (FR-304)")
        risky.append(f"{label}: tools 미명시")
        return
    for tool in RISKY_TOOLS:
        if tool in tools:
            risky.append(f"{label}: tools 에 `{tool}` 포함")


def main() -> int:
    if not PLUGINS.is_dir():
        print("plugins/ 디렉터리가 없다", file=sys.stderr)
        return 1
    for plugin in sorted(p for p in PLUGINS.iterdir() if p.is_dir()):
        check_plugin(plugin)

    if "--risk" in sys.argv:
        if risky:
            print("## 위험도 판정: **사람 승인 필요**\n")
            for r in risky:
                print(f"- {r}")
            print("\n오너 1인 이상의 승인 없이는 머지할 수 없다.")
        else:
            print("## 위험도 판정: **자동 승인 가능**\n")
            print("스크립트·훅·MCP·실행 파일이 없고, 에이전트가 위험 도구를 요구하지 않는다.")
        return 0

    if errors:
        print(f"구조 린트 실패 — {len(errors)}건\n", file=sys.stderr)
        for e in errors:
            print(f"  ✗ {e}", file=sys.stderr)
        return 1
    print("구조 린트 통과")
    return 0


if __name__ == "__main__":
    sys.exit(main())
