# 실행과 운영 준비

## 합의한 선택

2026-10-16 사용자가 영국 오전 8시 발송을 목표로 사전 생성하고 OpenAI·Resend·Render 기준으로 준비하기로 선택했다. 현재 기본 모델은 참고 초안의 `gpt-4.1-mini`이며 환경변수로 바꿀 수 있다. 최신 모델 또는 최적 품질·비용이 검증됐다는 의미는 아니다.

생성 시작은 임시 기본값 07:30 Europe/London이다. `PREPARATION_MINUTES=30`으로 조절한다. 08:00 이전에는 스케줄러가 발송하지 않는다. 개인 worker는 30초 간격으로 검사하므로 정확히 08:00:00 접수와 받은편지함 도착을 보장하지 않는다. 생성이 늦어지면 08:00 이후 준비되는 대로 발송하며 현지 09:00 이후에는 자동 복구를 멈춘다. 이 1시간 복구 창, 국가별 최대 3개, 호출 제한은 임시 운영 기본값이다.

## 로컬 준비

[uv](https://docs.astral.sh/uv/getting-started/installation/)를 설치한 뒤 프로젝트 루트에서:

```sh
uv sync --locked
uv run --locked pytest -q
uv run --locked python -m briefing doctor
```

`uv sync --locked`가 `.venv`와 개발용 패키지까지 설치하므로 별도 가상환경 활성화는 필요 없다. 패키지 추가는 `uv add`, 개발용 패키지 추가는 `uv add --dev`로 처리한다. 의존성을 변경하면 `pyproject.toml`과 `uv.lock`을 함께 커밋한다. Docker는 `uv sync --locked --no-dev`로 운영용 패키지만 설치한다.

`.env.example`을 `.env`로 복사한 뒤 자신의 편집기에서 OpenAI·LangSmith·Resend 키와 `MAIL_FROM`을 입력한다. 키를 채팅이나 저장소에 올리지 않는다. `.env`는 Git과 Docker 빌드 컨텍스트에서 제외된다. 기존 설정이 있다면 덮어쓰지 않는다.

월 예산은 아직 결정되지 않았다. 최대 70개 후보, 3개 본문 조회, 1회 수정, 하루 3회 생성 시도 및 3회 발송 시도로 사용량을 제한하지만 월 지출 상한을 보장하지 않는다. 실제 모델 호출·토큰·비용과 서버·메일·추적 비용을 확인한 뒤 예산을 정한다.

## 명령별 외부 효과

| 명령 | 효과 |
|---|---|
| `collect` | 공개 피드 접속, 후보 및 수집 보고서 저장. AI·메일 없음 |
| `doctor` | 설정 누락 여부 표시. 키 값은 출력하지 않음 |
| `demo` | 가상 기사 HTML·텍스트 작성. 실제 뉴스가 아니며 네트워크·AI·발송 없음 |
| `preview` | 실제 RSS·OpenAI 호출, LangSmith 활성화 시 추적. 미리보기만 작성 |
| `prepare` | 당일 실제 본문 생성 및 저장. 메일 발송 없음 |
| `send` | **이미 저장된 당일 본문을 즉시 실제 발송**. 수동 명령은 08:00까지 기다리지 않음 |
| `serve` | 사전 생성 및 08:00 이후 발송을 매일 자동 실행 |
| `status` | 당일 상태, 시도 횟수, 서비스 메시지 ID 표시 |
| `recover` | 발송 결과를 수동 정정. 이 명령 자체는 메일을 보내지 않음 |

```sh
uv run --locked python -m briefing demo
uv run --locked python -m briefing preview
uv run --locked python -m briefing prepare
uv run --locked python -m briefing status
# 본문 검토 및 발신자 설정 후 실제 발송:
uv run --locked python -m briefing send
```

가상 미리보기는 `var/demo/briefing.html`, 실제 미리보기는 `var/preview/briefing.html`, 저장한 당일 본문은 `var/latest/briefing.html`이다. 각각 일반 텍스트도 생성한다. 실제 편집 실행의 `briefing.json`에는 모델별 입력·출력 토큰 및 실행 시간, 후보·승인 기사 수, 빈 결과 사유를 기록한다. 가격표를 임의로 고정해 비용을 계산하지 않는다. LangSmith에 그래프와 모델 호출을 추적하도록 SDK 연동을 준비했으며 실제 연결은 키 설정 후 확인해야 한다.

그래프에 전달하는 입력은 기사·과거 사건·편집 상태뿐이다. 수신자·발신자·API 키·메일 설정 객체는 전달하지 않는다. 모의 테스트로 이 경계를 확인했으나 실제 LangSmith 추적 입력·출력과 조직별 보존 설정은 실연동 때 확인한다.

## 발송 실패 및 중단 복구

상태는 `generating → prepared → sending → accepted`다. `accepted`는 Resend 접수이며 받은편지함 도착을 뜻하지 않는다. 본문 생성 실패는 `failed`, 접수 결과 불명은 `uncertain`이다.

- 명확한 거절: 본문을 유지한 채 `prepared`로 돌아가며 재생성하지 않는다. 발송 시도는 하루 3회다.
- 요청 timeout·HTTP 5xx·409·접수 ID 불명: `uncertain`으로 멈춘다.
- 발송 요청 중 프로세스 종료: `sending` 상태가 남아 자동 재발송을 차단한다.
- 생성 중 종료: 파일 잠금이 해제되면 최대 3회 안에서 새 프로세스가 다시 생성할 수 있다.
- 동일 디스크의 worker 파일 잠금과 SQLite 원자적 발송 상태 전환을 함께 사용한다.

Resend 로그를 확인하고 실제 접수 ID가 있다면:

```sh
uv run --locked python -m briefing recover --day 2026-10-16 --action accepted --provider-id PROVIDER_MESSAGE_ID --note "Provider log confirms acceptance"
```

서비스가 접수하지 않았음을 확인했다면:

```sh
uv run --locked python -m briefing recover --day 2026-10-16 --action not-accepted --note "Provider logs confirm no acceptance"
```

후자는 `prepared`로 되돌린다. 시도 상한은 초기화하지 않는다. `sending/uncertain`만 정정할 수 있고 근거 메모와 변경 내역을 저장한다. 일일 idempotency key는 보조 장치이며 Resend의 키 보관 시간에 영구 중복 방지를 의존하지 않는다. 저장소를 삭제하면 중복 방지 이력이 사라지므로 `/data`와 SQLite를 유지해야 한다.

## Render 준비

`Dockerfile`, `uv.lock`, `render.yaml`을 준비했다. 단일 worker와 `/data` 영구 디스크를 사용한다. 배포 시 OpenAI·LangSmith·Resend 키와 검증된 `MAIL_FROM`을 Render secret으로 설정한다. `render.yaml`은 유료 worker·디스크 구성이며 실제 리소스는 아직 생성하지 않았다.

로컬 검증:

```sh
docker build -t technews-briefing:local .
docker run --rm --network none technews-briefing:local python -m briefing doctor
docker run --rm --network none technews-briefing:local python -m briefing demo
```

2026-10-16 최종 코드 기준 Docker 빌드 및 위 두 컨테이너 명령 성공. 모의 테스트 37개 통과, `pip check` 통과. 실제 API 호출·LangSmith 연결·메일 도착·Render 배포·재배포 후 기록 유지·개인 컴퓨터를 끈 상태의 이틀 연속 예약 발송은 미검증이다.

## 공식 문서 확인 근거

- [OpenAI Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs): Pydantic 기반 구조화 출력의 구현 근거. 형식 준수와 사실 정확성은 별도 검증한다.
- [LangGraph Graph API](https://docs.langchain.com/oss/python/langgraph/graph-api): 조건 분기와 상태 흐름.
- [Resend Send Email](https://resend.com/docs/api-reference/emails/send-email), [Idempotency keys](https://resend.com/changelog/idempotency-keys): 발송 API와 24시간 키 보관.
- [Render Persistent Disks](https://render.com/docs/disks): worker의 영구 저장 구성.

## uv 전환 검증: 2026-10-20

의존성 관리를 `pyproject.toml`과 `uv.lock`으로 통일하고 기존 `requirements.lock`을 제거했다. 개발용 pytest는 `dev` dependency group으로 옮겼으며 `.python-version`의 로컬 기본 Python은 Docker와 같은 3.13이다. 기존 Python 3.13 환경의 패키지 버전은 유지했다.

- `uv sync --locked`, `uv lock --check --offline` 성공
- `uv run --locked pytest -q`: 37개 통과
- `uv run --locked python -m briefing demo`: 가상 메일 생성 성공
- `uv pip check`: 설치된 패키지 간 호환성 검사 통과
- 별도 임시 환경에서 `uv sync --locked --no-dev --no-editable` 설치 성공
- uv 기반 Docker 이미지 빌드 성공. 네트워크 차단 상태에서 `doctor`·`demo` 실행과 편집 모듈 로딩 성공, pytest 제외 확인

이 검증은 실제 OpenAI·LangSmith·Resend 연결이나 서버 배포를 수행한 것이 아니다.
