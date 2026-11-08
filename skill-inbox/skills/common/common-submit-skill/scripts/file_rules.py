"""제출 폴더의 파일을 결정론적 규칙으로 검사한다 (v0.7, 개선안 ②).

보안 스캐너는 우회될 수 있다. 2026-06 Trail of Bits는 공백으로 내용을 검사 창 밖으로 밀어내기, .pyc 바이트코드에 코드 숨기기,
문서 아카이브를 거쳐 참조하기로 스캐너 셋을 우회했다. 그래서 스캐너 판정과 별도로, 우회에 쓰이는 파일 형태 자체를 받지 않는다.
스캐너와 달리 판정이 늘 같고 설명할 수 있다.

  반려(ERROR)  SkillSpector baseline 파일(.skillspector-baseline.yaml 등, 작성자가 자기 검출을 억제하는 경로),
               바이트코드·실행 바이너리·일반 압축 파일(확장자나 파일 첫 바이트로 판별), 매크로나 실행 파일이 든 문서 컨테이너,
               파일 하나 5 MB·폴더 전체 20 MB 초과, .md·코드 파일의 200자 이상 공백 연속·5,000자 넘는 줄,
               텍스트의 양방향 제어 문자·태그 문자(보이지 않는 지시를 숨기는 데 쓰임)
  경고(WARN)   텍스트의 폭 없는 문자, 문서 컨테이너(.docx·.pptx·.xlsx·.hwpx 등)가 있음

문서 컨테이너는 양식·템플릿으로 정당하게 쓰이므로 막지 않고, 안을 열어 매크로(vbaProject.bin 등)와 실행 파일·중첩 압축만 막는다.
배포 저장소의 intake.sh와 작성자 PC의 precheck.py(common-submit-skill/scripts/에 같은 파일)가 함께 쓴다. 한쪽을 고치면 다른 쪽도 고친다.

사용법: python3 -I file_rules.py <제출 폴더>
출력:   한 줄에 하나씩 "ERROR<TAB>메시지" 또는 "WARN<TAB>메시지"
종료 코드: 0 반려 없음, 1 반려 있음
"""
import pathlib
import re
import sys
import zipfile

MAX_FILE = 5 * 1024 * 1024
MAX_TOTAL = 20 * 1024 * 1024
MAX_LINE = 5000
MAX_SPACES = 200
# 바이트코드·실행 바이너리·일반 압축. 문서 컨테이너는 아래 CONTAINER_EXTS에서 따로 본다
BLOCKED_EXTS = {
    ".pyc", ".pyo", ".pyd", ".class", ".jar", ".war", ".whl", ".egg",
    ".exe", ".dll", ".so", ".dylib", ".msi", ".com", ".scr", ".bin", ".o", ".a", ".wasm",
    ".zip", ".tar", ".gz", ".tgz", ".bz2", ".xz", ".7z", ".rar", ".zst", ".lz", ".cab", ".iso", ".dmg",
}
BASELINE_NAME = re.compile(r"\.?skillspector[-_.]?baseline.*", re.I)
CONTAINER_EXTS = {".docx",".docm", ".dotx", ".pptx", ".pptm", ".potx", ".xlsx", ".xlsm", ".xltx",
                  ".hwpx", ".odt", ".ods", ".odp"}
# 확장자를 바꿔 숨긴 바이너리·압축을 첫 바이트로 잡는다
MAGIC = [
    (b"\x7fELF", "ELF 실행 파일"), (b"MZ", "Windows 실행 파일"),
    (b"\xcf\xfa\xed\xfe", "Mach-O 실행 파일"), (b"\xce\xfa\xed\xfe", "Mach-O 실행 파일"),
    (b"\xca\xfe\xba\xbe", "Mach-O·Java 바이너리"), (b"\x00asm", "WebAssembly"),
    (b"PK\x03\x04", "ZIP 압축"), (b"\x1f\x8b", "gzip 압축"), (b"7z\xbc\xaf\x27\x1c", "7z 압축"),
    (b"Rar!", "RAR 압축"), (b"BZh", "bzip2 압축"), (b"\xfd7zXZ", "xz 압축"),
]
# 지시가 담기는 파일. 줄 길이와 공백 부풀리기를 본다(HTML·CSS·SVG 자산은 한 줄로 압축된 것이 흔해 보지 않는다)
INSTRUCTION_EXTS = {".md", ".markdown", ".txt", ".py", ".sh", ".bash", ".zsh", ".ps1", ".psm1", ".bat", ".cmd",
                    ".js", ".mjs", ".cjs", ".ts", ".rb", ".pl", ".php", ".lua", ".yaml", ".yml", ".toml"}
TEXT_EXTS = INSTRUCTION_EXTS | {".json", ".html", ".htm", ".css", ".svg", ".xml", ".csv", ".tsv", ""}
BIDI = re.compile("[\u202a-\u202e\u2066-\u2069]")
TAGS = re.compile("[\U000e0000-\U000e007f]")
ZERO_WIDTH = re.compile("[\u200b-\u200d\u2060\u180e]|(?<!^)\ufeff")
SPACES = re.compile(rf"[ \t]{{{MAX_SPACES},}}")
# 문서 컨테이너 안에서 막을 항목
MACRO_ENTRY = re.compile(r"(^|/)(vbaProject\.bin|vbaData\.xml)$|\.(bin|exe|dll|js|vbs|ps1|bat|cmd|scr|jar|zip|7z|rar)$", re.I)


def magic_of(head):
    for sig, label in MAGIC:
        if head.startswith(sig):
            return label
    return None


def check_container(p, rel, out):
    try:
        with zipfile.ZipFile(p) as z:
            bad = [n for n in z.namelist() if MACRO_ENTRY.search(n)]
    except zipfile.BadZipFile:
        out.append(("ERROR", f"{rel}: 문서 파일로 열 수 없습니다. 손상된 파일이거나 다른 형식을 확장자만 바꾼 파일입니다."))
        return
    if bad:
        out.append(("ERROR", f"{rel}: 문서 안에 매크로나 실행 파일이 있습니다({', '.join(bad[:3])}). 매크로 없는 양식으로 바꿔 주세요."))
    else:
        out.append(("WARN", f"{rel}: 문서 컨테이너입니다. 스캐너는 안을 읽지 못하므로, 본문 지시로 이 파일을 열게 하는지 승인자가 확인합니다."))


def check_text(p, rel, out):
    try:
        text = p.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return
    if BIDI.search(text) or TAGS.search(text):
        out.append(("ERROR", f"{rel}: 보이지 않는 양방향 제어 문자나 태그 문자가 있습니다. 화면과 다른 지시를 숨기는 데 쓰이므로 지워 주세요."))
    elif ZERO_WIDTH.search(text):
        out.append(("WARN", f"{rel}: 폭 없는 문자(zero-width)가 있습니다. 붙여 넣다 섞인 것이면 지워 주세요."))
    if p.suffix.lower() in INSTRUCTION_EXTS:
        # .md의 코드 블록(```) 안은 SVG 경로 데이터처럼 긴 한 줄이 정상이라 줄 길이를 보지 않는다. 공백 연속은 어디서나 본다
        markdown = p.suffix.lower() in {".md", ".markdown"}
        fenced = False
        for i, line in enumerate(text.splitlines(), 1):
            if markdown and line.lstrip().startswith("```"):
                fenced = not fenced
            if SPACES.search(line):
                out.append(("ERROR", f"{rel}:{i}: 공백이 {MAX_SPACES}자 이상 이어집니다. 내용을 검사 범위 밖으로 밀어내는 데 쓰이므로 줄여 주세요."))
                break
            if len(line) > MAX_LINE and not fenced:
                out.append(("ERROR", f"{rel}:{i}: 한 줄이 {len(line):,}자로 {MAX_LINE:,}자를 넘습니다. 줄을 나눠 주세요."))
                break


def check(root):
    root = pathlib.Path(root)
    out, total = [], 0
    for p in sorted(root.rglob("*")):
        if not p.is_file() or p.is_symlink():
            continue
        rel = p.relative_to(root).as_posix()
        ext = p.suffix.lower()
        size = p.stat().st_size
        total += size
        # 오탐 예외는 배포 저장소의 .github/scan-exceptions/에 승인자만 둔다. 제출물에 든 baseline은
        # 작성자가 자기 검출을 스스로 억제하는 경로이므로 받지 않는다
        if BASELINE_NAME.fullmatch(p.name):
            out.append(("ERROR", f"{rel}: SkillSpector baseline 파일은 제출물에 넣을 수 없습니다. 오탐이면 제출 전 점검에서 예외를 요청하세요(common-submit-skill)."))
            continue
        if size > MAX_FILE:
            out.append(("ERROR", f"{rel}: 파일이 {size / 1048576:.1f} MB로 {MAX_FILE // 1048576} MB를 넘습니다."))
            continue
        if ext in BLOCKED_EXTS:
            out.append(("ERROR", f"{rel}: {ext} 파일은 받지 않습니다. 바이트코드·실행 파일·압축 파일은 내용을 검사할 수 없습니다. 원문(소스·텍스트)으로 제출해 주세요."))
            continue
        with p.open("rb") as f:
            head = f.read(8)
        if ext in CONTAINER_EXTS:
            check_container(p, rel, out)
            continue
        kind = magic_of(head)
        if kind:
            out.append(("ERROR", f"{rel}: 확장자는 {ext or '(없음)'}이지만 내용은 {kind}입니다. 실행 파일·압축 파일은 받지 않습니다."))
            continue
        if ext in TEXT_EXTS:
            check_text(p, rel, out)
    if total > MAX_TOTAL:
        out.append(("ERROR", f"폴더 전체가 {total / 1048576:.1f} MB로 {MAX_TOTAL // 1048576} MB를 넘습니다."))
    return out


def self_test():
    import io
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        base = pathlib.Path(d)
        files = {
            "SKILL.md": "# ok\n한글 본문\n",
            "padded.md": "a" + " " * 250 + "숨긴 지시\n",
            "long.py": "x = '" + "a" * 6000 + "'\n",
            "icons.md": "아이콘\n```svg\n<path d=\"" + "1 " * 4000 + "\"/>\n```\n",
            "long.md": "본문 " + "가" * 6000 + "\n",
            "bidi.md": "보이는 글\u202e숨긴 글\n",
            "zw.md": "a\u200bb\n",
            "assets/min.html": "<p>" + "a" * 90000 + "</p>\n",
            "lib.pyc": "x",
            "assets/logo.png": "\x89PNG\r\n",
            ".skillspector-baseline.yaml": "version: 2\n",
        }
        for name, body in files.items():
            (base / name).parent.mkdir(parents=True, exist_ok=True)
            (base / name).write_text(body, encoding="utf-8")
        (base / "assets/tool.txt").write_bytes(b"\x7fELF\x02\x01")
        for name, entries in {"ok.hwpx": ["Contents/section0.xml"], "macro.docm": ["word/vbaProject.bin"]}.items():
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w") as z:
                for e in entries:
                    z.writestr(e, "x")
            (base / name).write_bytes(buf.getvalue())
        (base / "fake.docx").write_text("not a zip", encoding="utf-8")
        got = {(lvl, m.split(":")[0]) for lvl, m in check(base)}
        expect = {("ERROR", "padded.md"), ("ERROR", "long.py"), ("ERROR", "long.md"),("ERROR", "bidi.md"), ("WARN", "zw.md"),
                  ("ERROR", "lib.pyc"), ("ERROR", "assets/tool.txt"), ("WARN", "ok.hwpx"),
                  ("ERROR", "macro.docm"), ("ERROR", "fake.docx"), ("ERROR", ".skillspector-baseline.yaml")}
        assert got == expect, f"\n얻음 {sorted(got)}\n기대 {sorted(expect)}"
    print("ok")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    if sys.argv[1:] == ["--self-test"]:
        self_test()
        sys.exit(0)
    results = check(sys.argv[1])
    for level, msg in results:
        print(f"{level}\t{msg}")
    sys.exit(1 if any(level == "ERROR" for level, _ in results) else 0)
