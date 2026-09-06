#!/usr/bin/env bash
# Phase 0 — 스킬 자가진단 (읽기 전용)
#
# 내 PC에 어떤 스킬이 있는지 목록을 만든다.
# 파일을 고치거나 지우지 않고, 아무것도 전송하지 않는다.
# 출력 결과를 직접 읽어보고, 공유해도 괜찮은 내용이면 수집 이슈에 붙여넣으면 된다.
#
# 사용법:  bash inventory.sh
set -uo pipefail

SEARCH_DIRS=(
  "$HOME/.claude/skills"
  "$HOME/.claude/agents"
)
# 프로젝트 로컬 스킬도 있으면 함께 본다 (현재 디렉터리 기준 2단계까지)
while IFS= read -r d; do SEARCH_DIRS+=("$d"); done < <(
  find -L . -maxdepth 3 -type d -path "*/.claude/skills" 2>/dev/null
)

echo "# 스킬 인벤토리"
echo
echo "- 수집 시각: $(date '+%Y-%m-%d %H:%M')"
echo "- 호스트: $(hostname -s 2>/dev/null || echo unknown)"
echo
echo "| 위치 | 이름 | 설명 | SHA-256(앞 12자리) |"
echo "|---|---|---|---|"

count=0
for dir in "${SEARCH_DIRS[@]}"; do
  [ -d "$dir" ] || continue
  while IFS= read -r f; do
    [ -f "$f" ] || continue
    name=$(sed -n 's/^name:[[:space:]]*//p' "$f" | head -1)
    desc=$(sed -n 's/^description:[[:space:]]*//p' "$f" | head -1)
    [ -n "$name" ] || name=$(basename "$(dirname "$f")")
    # 표가 깨지지 않도록 파이프를 치환하고 설명은 120자로 자른다
    desc=${desc//|/／}
    [ ${#desc} -gt 120 ] && desc="${desc:0:120}…"
    if command -v shasum >/dev/null 2>&1; then
      hash=$(shasum -a 256 "$f" | cut -c1-12)
    else
      hash=$(sha256sum "$f" | cut -c1-12)
    fi
    echo "| ${dir/#$HOME/~} | ${name} | ${desc} | ${hash} |"
    count=$((count + 1))
  done < <(
    if [ "$(basename "$dir")" = "agents" ]; then
      # 에이전트는 디렉터리 바로 아래 .md 파일 하나가 곧 에이전트다
      find -L "$dir" -maxdepth 1 -name "*.md" 2>/dev/null | sort
    else
      # 스킬은 SKILL.md 만 센다. 같은 폴더의 README/참고문서는 제외한다
      find -L "$dir" -maxdepth 2 -name "SKILL.md" 2>/dev/null | sort
    fi
  )
done

echo
echo "**총 ${count}건**"
echo
if [ "$count" -eq 0 ]; then
  echo "> 발견된 스킬이 없습니다. 그대로 \"0건\"으로 회신해 주세요 — 그것도 중요한 데이터입니다."
else
  echo "> 위 표를 확인하고, **공유해도 괜찮은 내용만** 수집 이슈에 붙여넣어 주세요."
  echo "> 설명에 사내 민감 정보가 들어 있다면 해당 행은 지우거나 이름만 남기고 회신하시면 됩니다."
fi
