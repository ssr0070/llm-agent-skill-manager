---
name: common-skill-guide
description: 사내 스킬을 만들거나 고칠 때 적용하는 작성 규칙. skill-creator를 쓸 때, 스킬 이름·description·metadata·allowed-tools를 정할 때, 평가 파일(evals.json, benchmark.json, plugin eval 케이스)을 준비할 때, 조직 배포용으로 제출하기 전에 함께 쓴다.
metadata:
  owner: skill-admin
  team: common
---

# 사내 스킬 작성 규칙

skill-creator로 스킬을 만들 때 이 규칙을 함께 따른다. 규칙을 어긴 스킬은 제출 후 자동 정적 검사에서 반려된다. 원본은 PRD §9.12·§9.13이다.

## 1. 이름 (`name`)

형식: `<팀 접두어>-<기능>`

| 팀 | 접두어 | 예시 |
|---|---|---|
| 전사 | `common` | `common-meeting-notes` |
| 마케팅 | `mkt` | `mkt-campaign-brief` |
| 영업 | `sales` | `sales-proposal-writer` |
| RND | `rnd` | `rnd-paper-summary` |
| 개발 | `dev` | `dev-pr-review` |
| 콘텐츠 | `content` | `content-lecture-outline` |
| HR | `hr` | `hr-onboarding-checklist` |
| 재무회계 | `fin` | `fin-expense-guide` |

- 소문자, 숫자, 하이픈만 쓰고 64자를 넘지 않는다.
- `claude`, `anthropic`은 쓰지 않는다.
- 제작자 이름은 이름에 넣지 않는다. 이름은 호출 명령과 사용 기록의 기준이 되므로, 담당자가 바뀌어도 그대로 유지되어야 한다.
- 기능 부분은 무엇을 하는지 드러나는 동사·명사로 짓는다. `helper`, `tool`, `util`처럼 뜻이 넓은 단어만으로 짓지 않는다.

## 2. metadata

```yaml
metadata:
  owner: hong.gildong            # 사내 메일 ID(@example.com 앞부분) 또는 전체 주소
  # owner: user@example.io  # example.com이 아닌 도메인은 전체 주소로 쓴다
  team: sales                    # 이름의 팀 접두어와 같은 값
```

- `owner`와 `team`은 필수다. 반려·배포 완료·수정 요청 메일이 `owner`에게 간다. 담당자가 바뀌면 `owner`만 고친다.
- 외부에서 가져온 스킬은 `source`에 원본 URL과 커밋을 적는다(예: `https://github.com/org/repo@abc123`). 출처가 없으면 반려된다.
- 표준 필드(`name`, `description`, `metadata`, `license`, `compatibility`, `allowed-tools`) 외의 사내 정보는 모두 `metadata` 아래에 둔다.

## 3. description

스킬 이름과 설명은 쓰이지 않아도 **매 세션 컨텍스트를 차지한다.** 설명이 길수록 모든 직원의 토큰이 늘고, 목록 예산(컨텍스트의 1%)을 넘으면 적게 쓰는 스킬부터 설명이 빠져 자동으로 불리지 않는다.

- **핵심 용도를 맨 앞에 둔다.** 무엇을 하는지와 **언제 써야 하는지**를 함께 적는다. Claude는 이 문장을 보고 스킬을 고른다.
- `[영업]` 같은 팀명 접두어를 붙이지 않는다. 팀 정보는 이미 `name`과 `metadata.team`에 있다.
- 150~300자를 권장한다. 1,024자를 넘으면 반려된다.

## 4. allowed-tools

`allowed-tools`에 적은 도구는 스킬을 호출한 턴 동안 **사용자 승인 없이** 실행된다.

- 꼭 필요한 도구만 적는다. 읽기 도구(`Read`, `Grep`, `Glob`)만 쓰면 L1이다.
- 셸 명령은 필요한 명령만 좁혀 적는다. 예: `Bash(git status:*)`
- `Bash`, `Bash(*)`, `*`처럼 실행 권한을 통째로 여는 값은 자동으로 반려된다.

## 5. 폴더 구성

```
<name>/
├─ SKILL.md                필수
├─ evals/evals.json        필수. skill-creator 테스트 질문 3건 이상
├─ evals/benchmark.json    필수. skill-creator 평가 결과
├─ evals/plugin-eval/      필수. plugin eval 케이스 3건 이상 (아래 6장)
├─ references/             선택. 필요할 때만 읽는 참고 문서
├─ scripts/                선택. 실행 파일. 있으면 L2 (최상위 bin/ 금지)
└─ assets/                 선택. 양식, 이미지 등
```

## 6. 평가 파일 두 가지

skill-creator와 plugin eval은 형식이 다르고, 서로의 파일을 읽지 않는다. **둘 다** 만든다.

| 파일 | 만드는 방법 | 용도 |
|---|---|---|
| `evals/evals.json`, `evals/benchmark.json` | skill-creator 평가를 실행하면 생긴다 | 만들면서 품질 확인. 승인자가 스킬이 있을 때와 없을 때의 개선 폭을 본다 |
| `evals/plugin-eval/<케이스>/` | 아래 형식으로 직접 쓴다 | 모델이 바뀔 때마다 배포된 스킬을 다시 평가하는 기준. L2 스킬은 병합 전에도 돌린다 |

`evals.json`의 테스트 질문은 3건 이상이고, 불려야 할 질문과 불리면 안 될 질문을 각각 하나 이상 넣는다.

plugin eval 케이스는 케이스마다 폴더 하나를 만든다. 3건 이상 만들고, `evals.json`의 질문을 옮겨 써도 된다. Claude Code에서 "내 스킬 점검해줘"라고 하면 `common-skill-reviewer` 에이전트가 모자란 케이스의 초안을 만들어 준다. 초안은 반드시 열어 보고 통과 기준을 고친다.

```
evals/plugin-eval/
└─ proposal-draft/
   ├─ prompt.md
   └─ graders/
      ├─ criteria.md      # 통과 기준. 점수에 들어간다
      └─ skill-fired.md   # 스킬이 불렸는지. 참고용
```

`prompt.md`:

```markdown
---
max_turns: 10
allowed_tools: [Read, Glob, Grep, Skill]
---

A사 클라우드 전환 제안서 초안을 써 줘. 예산은 3억 원이야.
```

`graders/criteria.md`:

```markdown
---
type: llm
---

PASS if 제안서가 배경, 제안 내용, 일정, 예산 항목을 갖추고 예산 3억 원을 반영한다.
FAIL if 항목이 빠지거나 예산을 반영하지 않는다.
```

`graders/skill-fired.md` (`sales-proposal-writer` 자리에 자기 스킬 이름을 넣는다):

```markdown
---
type: tool_used
tool: Skill
input_match: '"skill"\s*:\s*"(?:[\w-]+:)?sales-proposal-writer"'
---
```

- 통과 여부는 `criteria.md` 같은 채점기로 정해진다. 스킬이 불렸는지 확인하는 채점기는 스킬 유무를 비교하는 실행에서 점수에 들어가지 않는다.
- 불리면 안 되는 질문의 케이스는 `criteria.md`에 "스킬 규칙을 언급하지 않고 원래 요청만 처리하면 PASS"처럼 쓴다.
- 고객 정보나 실제 사내 데이터를 케이스에 넣지 않는다.

## 7. 위험 등급

| 등급 | 조건 | 승인 |
|---|---|---|
| L1 | hook·MCP·`scripts/` 없음, `allowed-tools`는 없거나 읽기 도구만, 내부용 산출물 | 승인자 검토 후 병합 |
| L2 | hook, MCP, `scripts/`, 쓰기·실행 `allowed-tools` 중 하나라도 있음. 또는 사내 데이터 접근, 대외 문서 생성 | 승인자가 원문을 직접 읽고, 병합 전 plugin eval을 통과해야 함. 검토가 길어질 수 있다 |
| L3 | 쓰기 작업(CRM 변경, 메일 발송), 고객 데이터, 법적 문서, 인사·급여·원가 데이터 | 조직 번들로 배포하지 않음 |

## 8. 넣으면 안 되는 것

- 고객 정보, 인사·급여·원가 데이터, API 키·비밀번호
- 최상위 `bin/` 폴더 (실행 파일은 `scripts/`에 둔다)
- 심볼릭 링크 (실제 파일로 바꿔 넣는다)
- MCP 서버가 필요하면 스킬 폴더에 `.mcp.json`을 넣어 함께 제출한다. 승인되면 팀 번들에 합쳐진다.
  - 가능하면 발행자가 분명한 서버(공식 벤더, 공공기관, 공식 MCP 레지스트리 등재)를 쓴다.
  - 토큰은 값을 쓰지 말고 환경 변수 이름만 적는다(예: `"env": {"NOTION_TOKEN": "${NOTION_TOKEN}"}`).
  - 회사가 차단한 발행자나 국가의 서버는 자동으로 반려된다.

## 9. 제출과 이후

1. 위 평가 파일을 모두 갖춘다.
2. 스킬을 개인 스킬로 업로드하거나 공유하지 않는다. 조직 번들과 중복되기 때문이다.
3. 제출은 작성자 본인이 한다.
   - Claude Code: "스킬 제출해줘"라고 하면 `common-submit-skill`이 점검하고 접수 저장소에 PR을 만들어 준다.
   - 웹 화면: GitHub의 `example-org/ai-skill-inbox` 저장소 `skills/<팀>/` 폴더에서 Add file > Upload files로 스킬 폴더를 올리고, 새 브랜치로 PR을 만든 뒤 리뷰어에 팀장 **개인 계정**을 지정한다. 팀 이름(`lead-<팀>`)으로 지정하면 Free 플랜에서는 무시된다.
4. 팀장이 업무 내용을 검토해 승인하고 병합한다. 팀장 승인 뒤에 커밋을 더하면 승인이 무효가 된다.
5. 자동 정적 검사를 통과하면 승인자가 보안을 검토해 배포한다. 반려되면 접수 저장소에 이슈가 생기고 메일이 간다.
6. 배포 후에는 새 대화에서 실제 업무로 써 보고 Claude가 스스로 이 스킬을 고르는지 확인한다. `/skill-doctor`로 스킬의 토큰 비용과 사용 빈도를 볼 수 있다.
7. 모델이 바뀌면 회귀 평가가 돈다. 기준에 못 미치면 수정 요청 메일이 오고, 같은 `name`으로 고쳐 다시 제출한다.
