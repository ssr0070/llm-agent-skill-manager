# /// script
# requires-python = ">=3.10"
# dependencies = ["pyyaml"]
# ///
"""제출 전 점검: 작성자가 스킬·플러그인 폴더를 배포 저장소의 자동 정적 검사와 같은 기준으로 직접 검사한다.

3단계 접수(제출 전 점검 → 제출 후 재검사 → 사람 검토)의 첫 단계다. 통과 보고서가 있어야 제출할 수 있고,
보고서는 PR 본문에 붙는다. 배포 저장소의 intake는 보고서의 내용 해시(git tree)가 제출된 폴더와 같은지
확인한 뒤 같은 검사를 다시 한다. 보고서는 제출 절차의 조건이지 보안 경계가 아니다. 최종 판정은 재검사가 한다.

기준은 intake.sh·check-plugin.sh와 같게 맞춘다. 한쪽을 고치면 다른 쪽도 고친다.
MCP 차단 목록(inspect_l2.py)과 배포본 버전·의존 플러그인 비교는 배포 저장소에서만 확인한다.

사용법: uv run --script precheck.py <스킬 또는 플러그인 폴더> [--team <팀>] [--out <보고서.md>] [--request-exception]
  --team  플러그인은 폴더에 팀 정보가 없으므로 리뷰할 팀장의 팀을 넘긴다. 스킬은 metadata.team을 쓴다
  --out   보고서를 쓸 파일. 없으면 표준 출력
  --request-exception
          SkillSpector HIGH가 오탐이라고 보고 승인자 판정을 요청한다. 반려 사유가 예외로 받을 수 있는 HIGH뿐일 때만
          보고서가 result=exception-requested가 되고, 그 보고서로 제출하면 재검사가 승인자 판정을 기다린다(보류).
          CRITICAL, 검사 시간 한도로 생긴 미완료, 다른 ❌가 있으면 요청할 수 없다(docs/08_scan-exception-design.md)
종료 코드: 0 통과, 1 미통과, 2 실행 오류(폴더 없음 등), 3 예외 요청(승인자 판정 필요)
필요한 도구: git, claude(Claude Code), skillspector, skill-scanner
  uv tool install git+https://github.com/NVIDIA/skillspector.git@11c8b48e35056602fad263438448e0ffb5be2776
  uv tool install cisco-ai-skill-scanner==2.2.1
버전은 배포 저장소의 .github/tool-versions와 같아야 판정이 같다. 바꿀 때는 그 파일과 아래 EXPECTED_VERSIONS를 함께 바꾼다.
같은 폴더의 file_rules.py는 배포 저장소 .github/scripts/file_rules.py의 사본이다(파일 형태 규칙, v0.7).
"""
import argparse
import datetime
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile

try:
    import yaml
except ImportError:
    sys.exit("PyYAML이 없습니다. 'uv run --script precheck.py ...'로 실행하면 자동으로 설치됩니다.")

import file_rules  # 같은 폴더. 배포 저장소의 intake.sh 3-4와 같은 기준

# 배포 저장소 .github/tool-versions와 같은 값. 설치된 버전이 다르면 판정이 달라질 수 있어 경고한다
# (SkillSpector는 커밋 SHA로 고정해서 --version으로 확인할 수 없다)
EXPECTED_VERSIONS = {"claude": "2.1.304", "skill-scanner": "2.2.1"}
# SkillSpector 검사 시간 한도(초). 배포 저장소 .github/tool-versions의 SKILLSPECTOR_MAX_WORKFLOW_SECONDS와 같은 값.
# 한도에 가까운 스킬은 실행마다 판정이 달라지고, 넘긴 파일은 분석 미완료(HIGH)가 된다
SCAN_SECONDS = "1200"

TEAMS = ("common", "mkt", "sales", "rnd", "dev", "content", "hr", "fin")
DOMAINS = ("example.com", "example.io")
NAME_RE = re.compile(r"^[a-z0-9-]{1,64}$")
TOOL_RE = re.compile(r"[A-Za-z_*][\w*-]*(?:\([^)]*\))?")  # inspect_l2.py·check-plugin.sh와 같은 규칙
GITATTRIBUTES = "* text=auto eol=lf\n"
# inspect_l2.py의 CODE_EXTS, check-plugin.sh의 셸 블록 정규식과 같게 맞춘다
CODE_EXTS = {".py", ".sh", ".bash", ".zsh", ".ps1", ".psm1", ".psd1", ".bat", ".cmd", ".vbs", ".wsf",
             ".js", ".mjs", ".cjs", ".ts", ".rb", ".pl", ".php", ".lua", ".r", ".go", ".applescript", ".scpt",
             ".exe", ".dll", ".so", ".dylib", ".jar", ".msi", ".com"}
SHELL_BLOCK_RE = re.compile(r"^[ \t]*```[ \t]*(?:bash|sh|shell|zsh|console|powershell|pwsh|ps1|cmd|bat)[ \t]*$", re.M)  # 접수 저장소의 .gitattributes. 내용 해시를 저장소와 같게 계산하기 위해 쓴다


class Report:
    def __init__(self):
        self.errors, self.warnings, self.notes = [], [], []
        # SkillSpector 점수·HIGH 반려의 수와 HIGH 검출 목록. 예외 요청을 받을 수 있는지 판단한다
        self.ss_errors, self.highs = 0, []

    def bad(self, msg):
        self.errors.append(msg)

    def bad_ss(self, msg):
        self.errors.append(msg)
        self.ss_errors += 1

    def warn(self, msg):
        self.warnings.append(msg)

    def note(self, msg):
        self.notes.append(msg)


def frontmatter(md):
    text = md.read_text(encoding="utf-8")
    parts = re.split(r"^---[ \t]*$", text, maxsplit=2, flags=re.M)
    if len(parts) < 3 or parts[0].strip():
        return {}
    try:
        data = yaml.safe_load(parts[1])
    except yaml.YAMLError:
        return None
    return data if isinstance(data, dict) else {}


def owner_ok(owner):
    """metadata.owner는 사내 메일 ID(hong.gildong) 또는 허용 도메인의 전체 주소"""
    if "@" in owner:
        local, _, domain = owner.partition("@")
        return domain in DOMAINS and re.fullmatch(r"[a-z0-9._-]+", local) is not None
    return re.fullmatch(r"[a-z0-9._-]+", owner) is not None


def name_violation(name, owner):
    """이름 금지어 규칙. 배포 저장소 .github/scripts/name_rules.sh와 같은 기준이다. 위반이 없으면 빈 문자열
    - 하이픈으로 나눈 이름 조각에 claude·anthropic이 있으면 안 된다(공급사 이름을 쓰면 공식 스킬처럼 보인다)
    - 담당자 메일 ID를 . _ - 로 나눈 3자 이상 조각이 이름 조각과 같으면 안 된다(사람 이름)"""
    segs = name.lower().split("-")
    for seg in segs:
        if seg in ("claude", "anthropic"):
            return f"이름에 '{seg}'를 쓸 수 없습니다. 공급사 이름은 공식 스킬로 오해받습니다."
    for part in re.split(r"[._-]", owner.lower().partition("@")[0]):
        if len(part) >= 3 and part in segs:
            return f"이름에 담당자 이름('{part}')을 쓸 수 없습니다. 기능을 나타내는 말로 바꿔 주세요."
    return ""


def eval_cases(d):
    """plugin eval 케이스 폴더 수: d/<케이스>/prompt.md 또는 case.yaml"""
    if not d.is_dir():
        return 0
    return sum(1 for c in d.iterdir() if c.is_dir() and ((c / "prompt.md").is_file() or (c / "case.yaml").is_file()))


def json_ok(path, need_evals=0):
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return not need_evals or len(data.get("evals") or []) >= need_evals


def check_skill_md(md, r, team, bundle, plugin_owner=""):
    """SKILL.md 하나의 이름·담당자·설명·권한 규칙 (check-plugin.sh 4번). plugin_owner는 플러그인의 author.email"""
    fm = frontmatter(md)
    label = md.parent.name
    if fm is None:
        r.bad(f"{label}: SKILL.md frontmatter를 YAML로 읽을 수 없습니다.")
        return {}
    name = str(fm.get("name") or "")
    meta = fm.get("metadata") or {}
    desc = str(fm.get("description") or "")
    label = name or label
    why = name_violation(name, str(meta.get("owner") or "") or plugin_owner)
    if why:
        r.bad(f"{label}: {why}")

    if bundle:
        if not re.fullmatch(rf"{team}-[a-z0-9][a-z0-9-]*", name) or len(name) > 64:
            r.bad(f"{label}: 이름은 '{team}-'으로 시작하는 소문자·숫자·하이픈 64자 이내여야 합니다.")
        owner = str(meta.get("owner") or "")
        if not owner:
            r.bad(f"{label}: metadata.owner(제작자 사내 메일 ID 또는 주소)가 없습니다.")
        elif not owner_ok(owner):
            r.bad(f"{label}: metadata.owner '{owner}'는 사내 메일 ID이거나 ({' '.join(DOMAINS)}) 도메인 주소여야 합니다.")
        if str(meta.get("team") or "") != team:
            r.bad(f"{label}: metadata.team은 '{team}'이어야 합니다(현재 '{meta.get('team') or ''}').")
    else:
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", name) or len(name) > 64:
            r.bad(f"{label}: 이름은 소문자·숫자·하이픈 64자 이내여야 합니다.")
    if name != md.parent.name:
        r.bad(f"{label}: SKILL.md의 name '{name}'이 폴더 이름 '{md.parent.name}'과 다릅니다.")

    if not desc:
        r.bad(f"{label}: description이 비어 있습니다.")
    elif len(desc) > 1024:
        r.bad(f"{label}: description이 1,024자를 넘습니다(현재 {len(desc)}자).")
    elif not 150 <= len(desc) <= 300:
        r.warn(f"{label}: description은 150~300자를 권장합니다(현재 {len(desc)}자). 설명은 매 세션 토큰을 차지합니다.")
    if desc.lstrip().startswith("["):
        r.warn(f"{label}: description을 [팀명] 같은 대괄호 접두어로 시작하지 마세요. 핵심 용도를 맨 앞에 둡니다.")

    tools = fm.get("allowed-tools") or []
    if isinstance(tools, str):
        tools = TOOL_RE.findall(tools)
    for t in tools:
        t = str(t)
        if t in ("*", "Bash") or re.fullmatch(r"[A-Za-z_]+\(\*\)", t):
            r.bad(f"{label}: allowed-tools의 '{t}'는 실행 권한을 와일드카드로 엽니다. 필요한 명령만 적으세요(예: Bash(git status:*)).")

    # 본문의 셸 명령 블록은 반려하지 않고 경고한다(check-plugin.sh와 같은 기준)
    shell_blocks = len(SHELL_BLOCK_RE.findall(md.read_text(encoding="utf-8")))
    if shell_blocks:
        r.warn(f"{label}: 본문에 셸 명령 블록이 {shell_blocks}개 있습니다. 직원에게 명령 실행을 시키는 스킬이면 팀장이 접수 PR에 L2 라벨을 달아 승인자 검토를 받게 됩니다.")
    return fm


def which(cmd):
    return shutil.which(cmd)


def run(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", **kw)


def tool_version(cmd):
    path = which(cmd)
    if not path:
        return None
    out = run([path, "--version"])
    return (out.stdout or out.stderr).strip().splitlines()[0] if (out.stdout or out.stderr).strip() else "?"


def ineligible(issue):
    """승인자 예외로 받을 수 없는 검출인가 (배포 저장소 scan_exceptions.py와 같은 기준)"""
    if issue.get("severity") == "CRITICAL":
        return "CRITICAL"
    ev = issue.get("evidence")
    if isinstance(ev, dict) and any(isinstance(x, dict) and x.get("reason_code") == "runtime_limit"
                                    for x in ev.get("reasons") or []):
        return "검사 시간 한도"
    return ""


def skillspector(d, label, r):
    """SkillSpector 판정 (check-plugin.sh와 같은 기준)
    점수 50 초과·HIGH 이상·치명적 예외 → 반려, 분석 일부 미완료·MEDIUM → 경고"""
    os.environ["SKILLSPECTOR_MAX_WORKFLOW_SECONDS"] = SCAN_SECONDS
    out = run([which("skillspector"), "scan", str(d), "--no-llm", "-f", "json"])
    try:
        res = json.loads(out.stdout)
    except ValueError:
        r.bad(f"{label}: SkillSpector 실행에 실패했습니다(종료 코드 {out.returncode}). {out.stderr.strip()[:300]}")
        return
    issues = res.get("issues") or []
    score = int((res.get("risk_assessment") or {}).get("score") or 0)
    highs = [i for i in issues if i.get("severity") in ("HIGH", "CRITICAL")]
    meds = [i for i in issues if i.get("severity") == "MEDIUM"]
    judged = False
    r.highs += [(label, i) for i in highs]
    if score > 50:
        r.bad_ss(f"{label}: SkillSpector 위험 점수가 {score}점으로 50을 넘습니다(HIGH 이상 {len(highs)}건, MEDIUM {len(meds)}건).")
        judged = True
    if highs:
        where = sorted({f"{i.get('category')} ({(i.get('location') or {}).get('file', '?')}:{(i.get('location') or {}).get('start_line', 0)})" for i in highs})
        r.bad_ss(f"{label}: SkillSpector가 HIGH 이상을 {len(highs)}건 검출했습니다: {', '.join(where)}")
        judged = True
    comp = res.get("analysis_completeness") or {}
    exc = comp.get("ledger_exceptions") or []
    fatal = [e for e in exc if e.get("fatal") is True]
    if fatal:
        where = sorted({f"{e.get('reason_code')} ({e.get('path', '?')}:{e.get('start_line', 0)})" for e in fatal})
        r.bad(f"{label}: SkillSpector가 분석을 끝내지 못했습니다(치명적 예외 {len(fatal)}건): {', '.join(where)}")
        judged = True
    elif comp.get("is_complete") is False:
        where = sorted({f"{e.get('reason_code')} ({e.get('path', '?')}:{e.get('start_line', 0)})" for e in exc})
        r.warn(f"{label}: SkillSpector 분석이 부분적으로 끝났습니다(반려 아님). 비치명 예외: {', '.join(where)}. "
               "reference_missing은 본문 문자열을 파일 경로로 오인한 경우가 대부분입니다.")
    if out.returncode != 0 and not judged:
        r.bad(f"{label}: SkillSpector 종료 코드가 {out.returncode}이지만 점수({score}점)와 검출에서 원인을 찾지 못했습니다.")
    if meds:
        cats = {}
        for i in meds:
            cats[i.get("category")] = cats.get(i.get("category"), 0) + 1
        r.warn(f"{label}: SkillSpector MEDIUM {len(meds)}건(위험 점수 {score}점, 반려 아님): "
               + ", ".join(f"{c} {n}건" for c, n in sorted(cats.items())))
    if not judged:
        r.note(f"{label}: SkillSpector 위험 점수 {score}점")


def cisco(d, label, r, work):
    out = run([which("skill-scanner"), "scan", str(d), "--fail-on-severity", "high",
               "--format", "sarif", "--output", str(work / f"cisco-{label}.sarif")])
    if out.returncode != 0:
        r.bad(f"{label}: Cisco skill-scanner가 HIGH 이상을 검출했거나 실행에 실패했습니다(종료 코드 {out.returncode}). "
              f"{(out.stderr or out.stdout).strip()[:300]}")


def validate(plugin_dir, r):
    out = run([which("claude"), "plugin", "validate", str(plugin_dir)])
    if out.returncode != 0:
        r.bad("claude plugin validate 를 통과하지 못했습니다: " + (out.stdout + out.stderr).strip()[-500:])


def content_tree(src):
    """접수 저장소에 커밋될 때와 같은 git tree 해시. intake가 제출된 폴더와 비교한다"""
    with tempfile.TemporaryDirectory() as tmp:
        repo = pathlib.Path(tmp)
        run(["git", "init", "-q", str(repo)])
        (repo / ".gitattributes").write_text(GITATTRIBUTES, encoding="utf-8")
        shutil.copytree(src, repo / "x", symlinks=True)
        add = run(["git", "-C", str(repo), "add", "-A", "x"])
        tree = run(["git", "-C", str(repo), "write-tree", "--prefix=x/"])
        if add.returncode or tree.returncode:
            return None
        return tree.stdout.strip()


def main():
    ap = argparse.ArgumentParser(description="스킬·플러그인 제출 전 점검")
    ap.add_argument("folder")
    ap.add_argument("--team")
    ap.add_argument("--out")
    ap.add_argument("--request-exception", action="store_true")
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")

    src = pathlib.Path(args.folder).resolve()
    if not src.is_dir():
        print(f"폴더가 없습니다: {src}", file=sys.stderr)
        return 2
    r = Report()
    plugin = (src / ".claude-plugin" / "plugin.json").is_file()
    kind, unit = ("plugins", "플러그인") if plugin else ("skills", "스킬")
    name, team = src.name, args.team or ""

    # 도구가 없으면 기준과 같은 검사를 할 수 없으므로 통과로 보지 않는다
    versions = {}
    for cmd in ("git", "claude", "skillspector", "skill-scanner"):
        versions[cmd] = tool_version(cmd)
        if not versions[cmd]:
            r.bad(f"'{cmd}' 명령을 찾을 수 없습니다. 설치 방법은 이 스크립트 첫머리의 '필요한 도구'를 보세요.")
        elif cmd in EXPECTED_VERSIONS and EXPECTED_VERSIONS[cmd] not in versions[cmd]:
            r.warn(f"'{cmd}' 버전({versions[cmd]})이 배포 저장소의 고정 버전 {EXPECTED_VERSIONS[cmd]}과 다르거나 확인되지 않습니다. "
                   "판정이 재검사와 달라질 수 있습니다. 설치 방법은 이 스크립트 첫머리의 '필요한 도구'를 보세요.")

    links = [p for p in src.rglob("*") if p.is_symlink()]
    if links:
        r.bad("심볼릭 링크는 받지 않습니다. 실제 파일로 바꿔 주세요: " + ", ".join(str(p.relative_to(src)) for p in links[:5]))
    junk = [p for p in src.rglob("__pycache__") if p.is_dir()] + ([src / "evals" / "results"] if (src / "evals" / "results").is_dir() else [])
    if junk:
        r.bad("제출하지 않는 폴더가 있습니다. 지운 뒤 다시 점검하세요: " + ", ".join(str(p.relative_to(src)) for p in junk))
    # 파일 형태 규칙: 바이트코드·실행 파일·압축, 매크로가 든 문서, 공백 부풀리기, 보이지 않는 문자
    for level, msg in file_rules.check(src):
        (r.bad if level == "ERROR" else r.warn)(msg)

    work = pathlib.Path(tempfile.mkdtemp(prefix="precheck-"))
    scan_dirs = []
    try:
        if not plugin:
            # 스킬: SKILL.md 하나, 팀 번들 규칙 (intake.sh 3-1, check-plugin.sh 번들 규칙)
            mds = list(src.rglob("SKILL.md"))
            if len(mds) != 1:
                r.bad(f"스킬 폴더에는 SKILL.md가 정확히 하나 있어야 합니다(현재 {len(mds)}개). "
                      "스킬 여럿이나 에이전트·hook을 함께 내려면 플러그인으로 제출하세요.")
            elif mds[0].parent != src:
                r.bad("SKILL.md는 스킬 폴더 바로 아래에 있어야 합니다.")
            else:
                fm = frontmatter(mds[0]) or {}
                team = str((fm.get("metadata") or {}).get("team") or "")
                if team not in TEAMS:
                    r.bad(f"metadata.team '{team}'은(는) {' '.join(TEAMS)} 중 하나여야 합니다.")
                if not NAME_RE.fullmatch(str(fm.get("name") or "")):
                    r.bad(f"이름 '{fm.get('name') or ''}'은 소문자·숫자·하이픈 64자 이내여야 합니다.")
                check_skill_md(mds[0], r, team, bundle=True)
                if not json_ok(src / "evals" / "evals.json", need_evals=3):
                    r.bad(f"{name}: evals/evals.json에 skill-creator 테스트 질문이 3건 이상 있어야 합니다.")
                if not json_ok(src / "evals" / "benchmark.json"):
                    r.bad(f"{name}: evals/benchmark.json(skill-creator 평가 결과)이 없거나 JSON이 아닙니다.")
                cases = eval_cases(src / "evals" / "plugin-eval")
                if cases < 3:
                    r.bad(f"{name}: evals/plugin-eval/에 plugin eval 케이스가 3건 이상 있어야 합니다(현재 {cases}건).")
                # 배포될 때와 같이 임시 번들에 넣어 claude plugin validate를 돌린다
                bundle = work / "bundle"
                (bundle / ".claude-plugin").mkdir(parents=True)
                (bundle / ".claude-plugin" / "plugin.json").write_text(json.dumps(
                    {"name": f"{team or 'common'}-toolkit", "version": "0.0.0", "description": "제출 전 점검용 임시 번들"}),
                    encoding="utf-8")
                shutil.copytree(src, bundle / "skills" / name, symlinks=True)
                pe = bundle / "skills" / name / "evals" / "plugin-eval"
                if pe.is_dir():
                    (bundle / "evals").mkdir()
                    shutil.move(str(pe), str(bundle / "evals" / name))
                if versions["claude"]:
                    validate(bundle, r)
                scan_dirs.append(src)
        else:
            # 플러그인: plugin.json, 이름, 담당자, 스킬·에이전트, 평가 케이스 (intake.sh 3-2, check-plugin.sh 플러그인 규칙)
            try:
                manifest = json.loads((src / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
            except ValueError:
                manifest = None
                r.bad(".claude-plugin/plugin.json이 JSON이 아닙니다.")
            if manifest is not None:
                pname = str(manifest.get("name") or "")
                email = str((manifest.get("author") or {}).get("email") or "")
                if pname != name:
                    r.bad(f"plugin.json의 name '{pname}'이 폴더 이름 '{name}'과 다릅니다.")
                if not NAME_RE.fullmatch(pname):
                    r.bad(f"이름 '{pname}'은 소문자·숫자·하이픈 64자 이내여야 합니다.")
                if pname.endswith("-toolkit"):
                    r.bad("'-toolkit'으로 끝나는 이름은 팀 번들용입니다.")
                why = name_violation(pname, email)
                if why:
                    r.bad(why)
                if "@" not in email or not owner_ok(email):
                    r.bad(f"plugin.json의 author.email('{email}')은 ({' '.join(DOMAINS)}) 도메인의 사내 주소여야 합니다.")
                if not manifest.get("version"):
                    r.warn("plugin.json에 version이 없습니다. 다시 제출할 때마다 배포본보다 올려야 합니다.")
            if not team:
                r.bad("플러그인은 --team으로 리뷰할 팀장의 팀을 넘겨야 합니다.")
            elif team not in TEAMS:
                r.bad(f"팀 '{team}'은(는) {' '.join(TEAMS)} 중 하나여야 합니다.")
            if (src / "bin").is_dir():
                r.bad("최상위 bin/ 폴더는 허용되지 않습니다. scripts/로 옮기세요.")
            for md in sorted(src.glob("skills/*/SKILL.md")):
                check_skill_md(md, r, team, bundle=False, plugin_owner=email if manifest else "")
                d = md.parent
                if not (json_ok(d / "evals" / "evals.json", need_evals=3) and json_ok(d / "evals" / "benchmark.json")):
                    r.warn(f"{d.name}: skill-creator 평가 결과(evals/evals.json 3건, evals/benchmark.json)가 없습니다. 승인자가 개선 폭을 볼 수 없습니다.")
                scan_dirs.append(d)
            cases = eval_cases(src / "evals")
            if cases < 3:
                r.bad(f"evals/에 plugin eval 케이스가 3건 이상 있어야 합니다(현재 {cases}건). 케이스마다 evals/<케이스>/prompt.md와 graders/를 둡니다.")
            for ag in sorted(src.glob("agents/*.md")):
                afm = frontmatter(ag) or {}
                if not afm.get("name"):
                    r.bad(f"agents/{ag.name}: frontmatter에 name이 없습니다.")
                if not afm.get("tools"):
                    r.warn(f"agents/{ag.name}: tools가 없어 모든 도구를 쓸 수 있습니다. 필요한 도구만 적는 것을 권장합니다.")
            if versions["claude"]:
                validate(src, r)

        # 보안 스캔: 스킬 폴더마다 (플러그인의 agents·hooks·commands는 스캐너가 보지 않으므로 승인자가 읽는다)
        for d in scan_dirs:
            if versions["skillspector"]:
                skillspector(d, d.name, r)
            if versions["skill-scanner"]:
                cisco(d, d.name, r, work)
    finally:
        shutil.rmtree(work, ignore_errors=True)

    l2 = [p for p in ("hooks", "scripts", "agents", "commands", ".mcp.json") if (src / p).exists()]
    l2 += [str(p.relative_to(src)) for p in src.glob("skills/*/scripts")]
    # scripts/ 밖의 실행 파일도 L2다(inspect_l2.py의 stray_code와 같은 기준)
    skip = {"scripts", "hooks", "skills"} if plugin else {"scripts"}
    stray = [p for p in src.rglob("*") if p.is_file() and "__pycache__" not in p.parts
             and p.suffix.lower() in CODE_EXTS and p.relative_to(src).parts[0] not in skip]
    if plugin:
        stray += [p for d in src.glob("skills/*") if d.is_dir() for p in d.rglob("*")
                  if p.is_file() and "__pycache__" not in p.parts and p.suffix.lower() in CODE_EXTS
                  and p.relative_to(d).parts[0] != "scripts"]
    l2 += sorted(p.relative_to(src).as_posix() for p in stray)
    if l2:
        r.note("L2 요소가 있습니다(" + ", ".join(l2) + "). 팀장 승인 뒤 승인자가 원문을 읽고 병합 전 eval을 돌리므로 배포가 L1보다 늦습니다.")
    else:
        r.note("L1로 예상됩니다. 팀장이 승인하면 승인자 검토 없이 자동 배포됩니다. 사내 데이터를 다루거나 고객에게 나가는 문서를 만들면 팀장이 L2 라벨을 답니다.")

    tree = content_tree(src) if versions["git"] else None
    if not tree:
        r.bad("내용 해시(git tree)를 계산하지 못했습니다.")
    passed = not r.errors
    # 예외 요청: 반려 사유가 예외로 받을 수 있는 SkillSpector HIGH뿐일 때만 승인자 판정을 요청할 수 있다
    refused = [(lb, i) for lb, i in r.highs if ineligible(i)]
    requestable = (not passed and r.highs and not refused and len(r.errors) == r.ss_errors)
    requested = bool(args.request_exception and requestable)
    if args.request_exception and not passed and not requested:
        why = ("CRITICAL이나 검사 시간 한도로 생긴 미완료가 있습니다" if refused
               else "SkillSpector HIGH 말고도 ❌가 있습니다" if r.highs else "SkillSpector HIGH가 없습니다")
        r.note(f"예외를 요청할 수 없습니다: {why}. ❌ 항목을 고친 뒤 다시 점검하세요.")
    elif requestable and not args.request_exception:
        r.note("남은 ❌는 SkillSpector HIGH뿐입니다. 원문을 읽어 오탐이라고 판단되면 --request-exception으로 다시 점검해 승인자 판정을 요청할 수 있습니다.")
    result = "pass" if passed else "exception-requested" if requested else "fail"
    now = datetime.datetime.now(datetime.timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M %Z")
    status = {"pass": "✅ 통과", "exception-requested": f"⏸ 승인자 예외 요청 (SkillSpector HIGH {len(r.highs)}건)",
              "fail": f"❌ 미통과 ({len(r.errors)}건)"}[result]
    lines = [
        "## 제출 전 점검 보고서",
        "",
        "| 항목 | 값 |",
        "|---|---|",
        f"| 대상 | `{kind}/{team or '?'}/{name}/` ({unit}) |",
        f"| 점검 시각 | {now} |",
        f"| 내용 해시 (git tree) | `{tree or '계산 실패'}` |",
        "| 도구 | " + ", ".join(f"{k} {v or '없음'}" for k, v in versions.items()) + " |",
        f"| 결과 | {status} |",
        "",
    ]
    lines += [f"- ❌ {m}" for m in r.errors]
    lines += [f"- ⚠️ {m}" for m in r.warnings]
    lines += [f"- ℹ️ {m}" for m in r.notes]
    if not (r.errors or r.warnings or r.notes):
        lines.append("- 지적 사항이 없습니다.")
    if r.highs:
        # 승인자가 오탐 여부를 판정할 때 보는 표. 규칙 ID와 위치로 원문을 찾는다
        lines += ["", "### SkillSpector HIGH 이상 검출", "", "| 스킬 | 규칙 | 심각도 | 분류 | 위치 | 검출 | 예외 |", "|---|---|---|---|---|---|---|"]
        for lb, i in r.highs:
            loc = i.get("location") or {}
            found = re.sub(r"\s+", " ", str(i.get("finding") or "")).strip().replace("|", "\\|")[:100]
            lines.append(f"| {lb} | {i.get('id', '?')} | {i.get('severity')} | {i.get('category')} | "
                         f"{loc.get('file', '?')}:{loc.get('start_line') or 0} | `{found}` | {ineligible(i) and '불가(' + ineligible(i) + ')' or '요청 가능'} |")
    lines += ["", "MCP 차단 목록, 배포본 버전, 의존 플러그인은 제출 후 재검사에서 확인합니다.", "",
              f"<!-- precheck: result={result} tree={tree or 'none'} kind={kind} team={team or 'none'} name={name} -->"]
    text = "\n".join(lines) + "\n"
    if args.out:
        pathlib.Path(args.out).write_text(text, encoding="utf-8")
        print(f"보고서: {args.out} ({ {'pass': '통과', 'exception-requested': '예외 요청', 'fail': '미통과'}[result] })")
    else:
        print(text)
    return {"pass": 0, "exception-requested": 3, "fail": 1}[result]


if __name__ == "__main__":
    sys.exit(main())
