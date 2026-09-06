# acme-skills

사내 스킬·에이전트 카탈로그. **모든 등재는 PR 리뷰를 거친다.**

> ⚠️ 이 저장소는 현재 **스켈레톤**이다. 저장소 이름(`acme-skills`), 오너 핸들(`@eng-owner-a` 등),
> 팀 구성은 전부 임시값이며 Phase 1에서 확정한다.

## 구조

```
.claude-plugin/marketplace.json   카탈로그 정의
plugins/
  common/     Required 등급. 전 직원 자동 설치, 제거 불가. 오너: 시큐리티 리드
  platform/   개발 워크플로·인프라
  sales/      영업 업무 (견적서 등)
  finance/    재무 업무
.github/
  CODEOWNERS               플러그인 단위 오너 강제
  PULL_REQUEST_TEMPLATE.md
  workflows/skill-ci.yml   구조 린트 + 보안 스캔(하드) / eval(경고)
scripts/
  lint_structure.py        구조 린트 + 위험도 판정
  inventory.sh             Phase 0 자가진단 (읽기 전용)
docs/CONTRIBUTING.md       기여 가이드
```

## 시작하기

기여 방법은 [docs/CONTRIBUTING.md](docs/CONTRIBUTING.md)를 보라.

제출 전 로컬 검사:

```bash
python3 scripts/lint_structure.py
python3 scripts/lint_structure.py --risk
```

## 설계 문서

- PRD: `../docs/PRD.md`
- 구현 계획: `../docs/IMPLEMENTATION-PLAN.md`
