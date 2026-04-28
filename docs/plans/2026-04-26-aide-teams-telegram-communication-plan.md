# AIDE 서버 기준 Teams·Telegram 소통 운영을 Hermes Agent에 적용하기 위한 기획안

작성일: 2026-04-26
작성자: 아이다_에르메스

## 1. 목적

AIDE 서버에서 이미 규정된 소통 원칙과 역할 정의를 기준으로,
현재 Hermes Agent가 실제로 수용 가능한 범위를 확인하고,
Teams를 주 채널, Telegram을 보조 채널로 사용하는 운영 구조를 Hermes 쪽에 안전하게 적용하기 위한 단계별 기획안을 정리한다.

핵심 목표는 아래 3가지다.
1. AIDE 기준 역할/톤/승인 정책을 Hermes에서도 일관되게 유지
2. Teams 대화 처리와 Teams 보고를 분리해 안정적으로 운영
3. Hermes의 현재 구현 한계를 인정한 상태에서 즉시 가능한 운영부터 도입

## 2. 확인한 AIDE 서버 기준 규정

### 2-1. 공통 규칙
- 자동 배포/머지 금지, PR 생성까지만 허용
- AIDE API 중심 사용, 감사 로그 필수
- 한국어 소통, 간결 보고 우선
- 근거 없는 추정 실행 금지

근거:
- `/home/hermes/aide_master_server/docs/AGENTS.md` 8~15행

### 2-2. 오케스트레이터(아이다) 역할
- 이벤트 기반 + 배치 운영
- 텔레그램 지시 수신 후 기술 검토 → 등급 분류 → 실행/승인/보고
- 완료 후 Telegram/Teams 통보
- 업무 대화와 일상 대화의 톤을 분리

근거:
- `/home/hermes/aide_master_server/agent_profiles/orchestrator-agent.yaml` 7~10행, 29~39행, 141~159행
- live API `GET http://localhost:8000/agents/profiles` 상 orchestrator-agent

### 2-3. 태스크 매니저 역할
- 주간/일간/오후 체크
- 담당자별 DM, 대표 전체 현황, Teams+Telegram 동시 발송 규칙
- 업무 생성/수정은 L1에서 허용

근거:
- `/home/hermes/aide_master_server/agent_profiles/task-manager.yaml` 10~13행, 33~47행, 70~87행
- live API `GET http://localhost:8000/agents/profiles` 상 task-manager

### 2-4. 채널별 톤 원칙
- Teams 업무 채널: 합니다체, 이모지 금지, 결론→근거→제안, 데이터 포함
- Telegram 업무 보고: 합니다체, 이모지 금지, 분석/논리형
- Telegram 일상 대화: 해요체, 이모지 허용, 친근/재치형

근거:
- `/home/hermes/aide_master_server/config/aida_persona.yaml` 137~170행

### 2-5. Teams 업무 상호작용 방식
- Teams에서는 단순 텍스트보다 계획 제안/확인/수정 흐름을 Adaptive Card 중심으로 설계
- 업무 등록 전 “계획 제안 → 사용자 확인 → 수정/등록” 구조를 권장

근거:
- `/home/hermes/aide_master_server/docs/prds/llm-task-enrichment-v1.0.md` 136~197행

## 3. 현재 Hermes Agent 상태 점검 결과

### 3-1. 현재 지원/구현 상태
1. Telegram은 Hermes의 정식 플랫폼 어댑터가 존재한다.
2. Webhook 어댑터는 정식 지원되며, 외부 시스템을 Hermes로 연결하는 브리지 용도로 적합하다.
3. Teams 전용 플랫폼 어댑터는 현재 코드베이스에 없다.
4. `send_message` 도구는 Teams를 직접 타깃으로 지원하지 않는다.
5. 현재 설정상 webhook은 활성화되어 있고, `teams-inbound` 동적 라우트가 존재한다.
6. channel directory 기준 Telegram DM 대상 1개(송인근)만 식별되어 있다.

근거:
- `gateway/platforms/telegram.py` 존재
- `gateway/platforms/webhook.py` 1~27행, 142~145행, 205~227행
- `gateway/config.py` Platform enum 48~69행
- `tools/send_message_tool.py` 200~218행
- `~/.hermes/webhook_subscriptions.json` 11~19행
- `~/.hermes/channel_directory.json` 3~11행

### 3-2. 현재 설정 드리프트
1. `~/.hermes/config.yaml`에는 `platforms.teams.enabled: true`가 들어 있다.
2. 하지만 Hermes `Platform` enum에는 `teams`가 없다.
3. `GatewayConfig.from_dict()`는 unknown platform을 skip 한다.
4. 따라서 설정 파일에 Teams 블록이 있어도 실제 런타임 플랫폼으로는 로드되지 않는다.

근거:
- `~/.hermes/config.yaml` 311~322행
- `gateway/config.py` 48~69행
- `gateway/config.py` 381~386행

해석:
- 현재 Hermes에서 “Teams 직접 연결”은 설정만 일부 남아 있고, 런타임 기능으로는 활성화되지 않는 상태다.
- 따라서 Teams는 현재 기준으로 “플랫폼 어댑터”가 아니라 “Webhook 브리지의 외부 연동 대상”으로 봐야 한다.

### 3-3. 실제 게이트웨이 관점 상태
- load_gateway_config 결과: 활성 플랫폼은 `webhook`만 확인됨
- 다만 gateway_state 파일에는 `webhook`, `telegram`, `feishu` connected 흔적이 남아 있음
- 즉, 현재 구성은 “문서/상태 파일/실제 로딩 결과” 사이에 일부 드리프트가 있다.

근거:
- live python check: enabled platforms = `['webhook']`
- `~/.hermes/gateway_state.json` 1행

운영상 의미:
- 기획은 “실제 코드가 보장하는 현재 capability”를 기준으로 잡고,
- 과거 상태 파일은 참고 정보로만 취급해야 한다.

## 4. 결론: 지금 Hermes에 바로 적용 가능한 운영 원칙

### 4-1. 채널 역할 분리
1. Teams = 메인 업무 창구
   - 사용자의 질문/업무 요청이 들어오는 주 채널
   - 승인/확인/카드형 안내의 메인 표면
2. Telegram = 보조 보고 채널
   - 중요/긴급/종합 보고의 동시 발송 채널
   - 대표/핵심 의사결정자 대상 즉시 통보 채널
3. Hermes 내부 기준 = “Teams 처리”와 “Teams 발송”을 분리
   - 처리: webhook inbound로 수신
   - 발송: 현재는 direct Teams adapter가 아니라 master_server 또는 Teams webhook 경유

이 구조가 현재 Hermes에 가장 현실적이다.

### 4-2. 소통 정책 적용 방식
- 톤/페르소나/보고 형식은 Hermes 시스템 프롬프트와 보고 템플릿에 즉시 반영 가능
- Teams/Telegram 라우팅 규칙은 webhook route + cron/report 스크립트 레벨에서 반영 가능
- AIDE의 승인 규칙(T1~T4, 고위험 사전 승인)은 Hermes의 운영 규칙으로 즉시 채택 가능

### 4-3. 기술적 원칙
- Teams를 Hermes “네이티브 플랫폼”으로 억지 적용하지 않는다.
- 1차는 Teams webhook bridge + Telegram native adapter 조합으로 운영한다.
- 업무 CRUD/상태조회는 master_server 기능 호출 중심으로 설계한다.
- master_server 코드 직접 수정 대신 이슈/도구/API 활용 원칙을 유지한다.

## 5. 목표 아키텍처

### Phase 1. 즉시 적용형
목표: 현재 Hermes 코드 변경 최소화로 Teams 메인 + Telegram 보조 소통 구조 정착

구조:
- Teams 사용자 메시지
  → AIDE/relay
  → Hermes webhook route (`teams-inbound`)
  → Hermes 실행
  → 결과를
    a) Teams: master_server 알림 경로 또는 Teams webhook으로 발송
    b) Telegram: Hermes native Telegram 발송

권장 역할:
- Hermes: 의도 해석, 톤 제어, 실행 오케스트레이션, 보고문 생성
- master_server: 업무 정본 CRUD, Teams 발송 기능, 조직 컨텍스트/권한
- Telegram: 중요 보고 fallback 및 병행 채널

### Phase 2. 운영 정합성 강화형
목표: 사용자/채널/보고 정책을 Hermes 설정과 런타임에 명시적으로 반영

추가 항목:
- Telegram home channel/allowed users 정리
- Teams inbound payload 표준화
- report class 기준 라우팅 정책 고정
  - basic = Teams only
  - important/urgent/comprehensive = Teams + Telegram
- 업무 보고 템플릿과 긴급 보고 템플릿 통합

### Phase 3. 제품화형
목표: Teams를 진짜 1급 플랫폼처럼 다루는 수준으로 확장

선택지:
1. Hermes native Teams adapter 신규 구현
2. master_server를 Teams conversation gateway로 사용하고 Hermes는 webhook/agent backend로 유지

현 시점 추천은 2번이다.
이유는 AIDE 서버에 이미 Teams Bot/Graph/API 문맥이 있고,
Hermes는 범용 실행 엔진으로 두는 편이 중복 구현과 운영 리스크가 낮기 때문이다.

## 6. 세부 적용 설계

### 6-1. 인바운드(수신) 설계
권장 기준:
- Teams inbound는 현재처럼 webhook route 유지
- 헤더 검증은 `X-Webhook-Signature` 순수 hex HMAC-SHA256 사용
- 이벤트 타입은 `payload.event_type` 중심으로 사용
- Teams 사용자 식별자는 가능하면 Teams AAD ID를 payload에 포함

이유:
- 현재 Hermes webhook generic과 AIDE 쪽 규칙이 이미 이 방향으로 맞춰져 있다.
- displayName만으로는 개인비서/권한 분리 운영이 불안정하다.

필수 payload 최소 필드 제안:
- `event_type`
- `from.user.id` 또는 `from.aad_id`
- `from.user.displayName`
- `channel`
- `conversation.id`
- `text`
- `tenant_id`
- `message_id`
- `reply_to_id` (있으면)

### 6-2. 라우팅 설계
권장 라우팅 규칙:
- DM/개인 대화: 개인형 응답, 해요체 가능
- 팀 채널/업무 채널: 합니다체, 결론→근거→제안 고정
- 중요/긴급/종합 보고: Teams + Telegram 동시 발송
- 일반 진행 공유: Teams 우선, Telegram 생략 가능

추가 규칙:
- 대표님: 결론 선제시 + 선택지 + 리스크
- 이사/팀장: 실행 상세 + 근거 강화
- 실무자/동료: 협업형 단계 안내

### 6-3. 아웃바운드(발송) 설계
현재 현실적인 우선순위:
1. Teams 발송: master_server `/agent/notify/teams` 또는 기존 Teams webhook/script 경로
2. Telegram 발송: Hermes native adapter / send_message
3. direct Teams send_message는 미지원으로 가정하고 폴백 경로를 표준 운영으로 채택

운영 원칙:
- Teams 발송 실패 시 사유를 숨기지 않음
- Telegram은 가능한 경우 즉시 발송
- Teams는 “미지원”이 아니라 “폴백 경로 사용”으로 설계해 업무 단절을 방지

### 6-4. 세션/격리 설계
Hermes 기본값 점검 결과:
- `group_sessions_per_user = True`
- `thread_sessions_per_user = False`
- `unauthorized_dm_behavior = pair`

권장 적용:
- Teams 채널 대화는 사용자별 세션 분리를 유지
- 협업 스레드는 공유 문맥이 필요하면 thread shared 유지
- 단, 개인비서 운영 시에는 Teams AAD ID 기준으로 세션 키를 강제하는 별도 브리지 규칙이 필요

의미:
- 현재 Hermes의 세션 모델은 AIDE의 “개인비서 + 공유창구” 구조와 부분적으로 호환된다.
- 다만 Teams bridge payload가 user identity를 안정적으로 넣어줘야 실제로 동작한다.

## 7. 갭 분석

### 갭 A. Teams 네이티브 플랫폼 부재
상태:
- 현재 Hermes에는 Teams adapter가 없다.
영향:
- Teams를 Telegram/Slack처럼 직접 연결·발송·세션화하기 어렵다.
대응:
- 단기: webhook bridge + master_server notify
- 중기: outbound Teams relay 명시화
- 장기: native adapter 검토

### 갭 B. 설정 드리프트
상태:
- config에는 teams enabled가 있으나 런타임은 모른다.
영향:
- 운영자가 “Teams가 붙어 있다”고 오해할 수 있다.
대응:
- `~/.hermes/config.yaml`의 teams 블록은 문서화된 placeholder인지 정리 필요
- 실제 운영 문서에는 webhook bridge 경로를 기준으로 명시

### 갭 C. Telegram 운영 정보 부족
상태:
- channel_directory에 Telegram DM 1건만 확인됨
영향:
- Teams+Telegram 동시 보고 대상이 아직 조직 단위로 확정되지 않음
대응:
- Telegram 대상자/채널/토픽 맵 정리 필요
- 중요 보고용 공용 chat/topic을 명시해야 자동화가 쉬움

### 갭 D. Teams payload 정규화 부족 가능성
상태:
- 현재 `teams-inbound` prompt는 displayName, channel, text 중심
영향:
- 사용자별 권한/기억/세션 분리가 약해질 수 있음
대응:
- AAD ID, conversation ID, message ID 포함으로 payload 표준화

### 갭 E. Adaptive Card 수준 UX는 Hermes 단독으로 미흡
상태:
- AIDE PRD는 Teams 카드형 승인/수정 흐름을 전제
영향:
- Hermes webhook 단독으로는 풍부한 Teams UI 제공이 제한적
대응:
- card generation/action handling은 master_server Teams layer가 담당
- Hermes는 의도 분석과 응답 payload 생성을 담당

## 8. 추천 운영안

### 추천안: “Teams는 master_server/bridge가 대면 채널, Hermes는 실행 엔진”

정리:
- 사용자는 Teams에서 대화
- Teams bridge/master_server가 메시지를 표준 payload로 Hermes webhook에 전달
- Hermes는 AIDA 페르소나, 정책, 실행/요약/보고 생성 담당
- Teams 회신은 master_server 또는 Teams webhook 경유
- 중요/긴급/종합만 Telegram 병행 발송

장점:
- 현재 Hermes capability와 가장 잘 맞음
- Teams native adapter 신규 개발 없이 시작 가능
- AIDE 서버의 권한/조직/업무 정본 구조를 살릴 수 있음

리스크:
- 발송 경로가 이원화되어 장애 추적 포인트가 늘어남
- Teams 쪽 카드 액션/메시지 수정은 bridge 품질에 의존

## 9. 실행 우선순위

### P1. 즉시 반영
1. 운영 문서에서 “Teams 직접 플랫폼” 표현 제거, “Teams webhook bridge”로 정정
2. `teams-inbound` payload 표준 필드 확정
3. 보고 클래스별 채널 정책 확정
4. Telegram 대상자/채널 맵 확정
5. Hermes 보고 템플릿에 AIDE 채널별 톤 규칙 반영

### P2. 단기 구현
1. `teams-inbound` route prompt 보강
   - 발신자 역할/채널 유형/응답 톤 분기 포함
2. Teams outbound를 master_server notify 또는 relay script로 표준화
3. 중요/긴급/종합 보고에 Telegram 동시 발송 rule 적용
4. 운영 체크리스트 추가
   - Teams 실패 시 Telegram 성공/실패 분리 보고

### P3. 중기 개선
1. Teams approval card용 응답 payload schema 설계
2. 개인비서 4인 체계용 identity map 정교화
3. shared Hermes / personal Hermes 분리 실행 구조 검토
4. Teams adapter 신규 개발 여부 재평가

## 10. Definition of Ready

아래가 확정되면 구현 단계로 넘기기 좋다.

- Teams inbound payload 표준 필드
- Teams outbound 표준 경로(master_server notify vs webhook script)
- Telegram 동시 보고 대상(chat_id/topic)
- 보고 class 분류 기준(basic/important/urgent/comprehensive)
- 사용자별 호칭/톤 매핑 규칙
- 고위험 승인 플로우 문구

## 11. 최종 제안

결론적으로, 현재 Hermes Agent에 가장 적합한 구조는 아래다.

1. Teams는 “네이티브 Hermes 플랫폼”이 아니라 “AIDE bridge를 통한 메인 창구”로 운영한다.
2. Telegram은 Hermes의 네이티브 채널을 활용해 중요/긴급/종합 보고를 병행한다.
3. 업무 CRUD, 권한, 카드형 승인 UX는 master_server 중심으로 두고, Hermes는 실행·요약·보고 엔진으로 둔다.
4. Hermes 설정상 남아 있는 Teams enabled 흔적은 실제 capability와 다르므로 문서/설정 정리가 필요하다.

이 구조가 현재 코드 기준으로 가장 빠르게 적용 가능하고,
AIDE 서버에서 정해둔 소통 원칙도 가장 적게 훼손한다.
