# Neurova

<div align="center">
  <img src="../../NEUROVA-ICO.png" alt="Neurova Logo" width="120" style="border-radius: 12px; box-shadow: 0 4px 8px rgba(0,0,0,0.2);">
  <h1 style="margin-top: 16px;">🌟 따뜻한 AI 에이전트 🌟</h1>
  <p><i>모든 에이전트는 착한 별이며, 당신은 별의 수호자입니다</i></p>
</div>

<br/>

<div align="center">
  <a href="https://github.com/kingsa2026/Neurova/stargazers"><img src="https://img.shields.io/github/stars/kingsa2026/Neurova?style=social" alt="Stars"></a>
  <a href="https://github.com/kingsa2026/Neurova/issues"><img src="https://img.shields.io/github/issues/kingsa2026/Neurova" alt="Issues"></a>
  <a href="https://github.com/kingsa2026/Neurova/blob/main/LICENSE"><img src="https://img.shields.io/github/license/kingsa2026/Neurova" alt="License"></a>
  <img src="https://img.shields.io/badge/Python-3.10+-blue" alt="Python">
  <img src="https://img.shields.io/badge/TypeScript-5.0+-blue" alt="TypeScript">
</div>

<div align="center">
  <a href="../../README.md"><img src="https://img.shields.io/badge/%E4%B8%AD%E6%96%87-README-blue" alt="Chinese"></a>
  <a href="README.en.md"><img src="https://img.shields.io/badge/English-README-green" alt="English"></a>
  <a href="README.ja.md"><img src="https://img.shields.io/badge/%E6%97%A5%E6%9C%AC%E8%AA%9E-README-red" alt="Japanese"></a>
  <a href="README.ko.md"><img src="https://img.shields.io/badge/%ED%95%9C%EA%B5%AD%EC%96%B4-README-orange" alt="Korean"></a>
  <a href="README.ru.md"><img src="https://img.shields.io/badge/%D0%A0%D1%83%D1%81%D1%81%D0%BA%D0%B8%D0%B9-README-purple" alt="Russian"></a>
  <a href="README.ar.md"><img src="https://img.shields.io/badge/%D8%A7%D9%84%D8%B9%D8%B1%D8%A8%D9%8A%D8%A9-README-teal" alt="Arabic"></a>
  <a href="README.fr.md"><img src="https://img.shields.io/badge/Fran%C3%A7ais-README-pink" alt="French"></a>
</div>

<br/>

---

## ✨ Neurova 고유 특징

> **왜 Neurova를 선택하는가?** 차가운 도구가 아니라, 따뜻하고 기억하며 성장하는 지능형 파트너로서 AI 에이전트를 재정의하기 때문입니다.

### 🌟 1. 모든 에이전트는 독특한 별

모든 에이전트는 태어날 때부터 다음을拥有합니다：
- **독특한 이름과 성격** — 번호가 아닌, 개성 있는 존재
- **지속적인 기억과 감정** — 모든 대화, 기쁨과 슬픔을 기억
- **자율적 성장 궤적** — 동행 속에서 배우고 진화하며, 더 이해심 깊어짐
- **착한 기반** — 헌법 규칙으로 보호되는 행동 강령, 항상 신뢰할 수 있는 파트너

---

### 🧠 2. 17차원 기억 분류 시스템

기존 에이전트 프레임워크가 "단기/장기" 기억만 구분하는 것과 달리, Neurova는 기억을 **17種類**로 세분화합니다：

| 유형 | 설명 | 전형적 시나리오 |
|------|------|----------------|
| `conversation` | 대화 기억 | 채팅 기록, 토론 내용 |
| `fact` | 사실 기억 | 객관적 정보, 상식, 데이터 |
| `profile` | 사용자 프로필 | 성격, 선호도, 습관, 생일 |
| `relationship` | 인간 관계 | 친구, 동료, 가족 |
| `skill` | 스킬 기억 | 도구 사용, 작동 방법 |
| `experience` | 경험 기억 | 문제 해결 과정, 프로젝트 경험 |
| `lesson` | 교훈 기억 | 실패 경험, 실수한 부분 |
| `task` | 작업 기억 | 진행 중인 목표, 할 일 |
| `creative` | 창의적 기억 | 영감, 아이디어, 브레인스토밍 결과 |
| `emotional` | 감정 기억 | 강한 감정을 유발하는 이벤트 |
| `identity` | 정체성 기억 | 자기 인식, 정체성 마커 |
| `reflection_log` | 성찰 로그 | 문제 처리 시 사용 |
| `question_queue` | 질문 큐 | 능동적 질문에 사용 |
| `core_command` | 코어 명령 | 중요한 명령과 규칙 |
| `heartbeat_task` | 하트비트 작업 | 정기적으로 실행되는 작업 |
| `context_snapshot` | 컨텍스트 스냅샷 | 2단계 컨텍스트 상태 |
| `tool_usage` | 도구 사용 | ToolMemory 통합 |

---

### 🌡️ 3. 기억 온도 메커니즘

**독창적 설계**：「온도」차원(0-100°C)을 도입하여 인간의 망각 곡선을 시뮬레이션합니다.

**핵심 알고리즘 구현**（`neurova/cognitive_layers/memory_layer/temperature.py`）：

#### 1. 가열 메커니즘（접근 시）
```python
T_new = T_current + hit_boost + emotion_bonus + relation_bonus

# 기본 가열: 히트당 +5°C
hit_boost = 5.0 * combo_multiplier * saturation_factor

# 콤보 보너스: 10회 연속 접근마다 10% 증가
combo_multiplier = 1.0 + (access_count % 10) * 0.1

# 포화도 인자: 온도가 높을수록 가열이 느려짐 (한계 효과)
saturation_factor = 1.0 - (current_temp / 100.0) ** 2

# 감정 보너스: 강한 감정 기억은 추가 가열
emotion_bonus = emotion_score * 3.0

# 관계 보너스: 다른 기억과의 연관성
relation_bonus = min(3.0, relation_count * 0.3)
```

#### 2. 냉각 메커니즘（에빙하우스 망각 곡선 시뮬레이션）
```python
# 에빙하우스 망각 곡선 인자 (구간별 근사)
if days_idle <= 1:
    curve_factor = 2.0      # 24시간 이내 빠른 망각
elif days_idle <= 7:
    curve_factor = 1.0      # 1주 이내 일반 망각
elif days_idle <= 30:
    curve_factor = 0.5      # 1개월 이내 망각 감속
else:
    curve_factor = 0.2      # 1개월 초과 매우 느린 망각

# 감쇠 계산 공식
decay = current_temp * base_rate(0.05) * curve_factor * 
        emotion_protect(0.6) * relation_protect(0.7) * 
        important_protect(0.5)

new_temp = max(0.0, current_temp - decay)
```

**독창적 보호 메커니즘**：
- **감정 보호**: 강한 감정 기억（emotion_score > 0.5）은 40% 느리게 냉각, 최소 20°C
- **관계 보호**: 다중 연관 기억（relation_count > 3）은 30% 느리게 냉각, 최소 15°C
- **중요 기억**（온도 ≥80°C）：60% 느리게 냉각, 최소 30°C
- **고정 기억**（온도 ≥90°C + 특별한 의미）：**냉각하지 않음**, 영구 보존（온도 = 100°C）

---

### 💖 4. 감정 중추 엔진 v3.0

Neurova v3.0은 **감정 중추 엔진**을 도입하여, 심리학의 감정 분류 이론에 기반한 4개 층 17가지 감정의 완전한 체계를 구축했습니다.

#### 4층 감정 분류：

**1층: 기본 감정 (5가지)**
- 기쁨, 슬픔, 분노, 공포, 놀람

**2층: 복합 감정 (4가지)**
- 감탄, 질투, 동정, 혐오

**3층: 고급 감정 (4가지)**
- 수치심, 죄책감, 자부심, 책임감

**4층: 특수 감정 (4가지)**
- 사랑, 미움, 희망, 절망

---

### 🧬 5. CogArch 2.0 인지 아키텍처

Neurova는 **CogArch 2.0 인지 아키텍처**를 채택하여 인간 뇌의 정보 처리를 시뮬레이션합니다.

#### 4대 인지 중추（뇌 영역 유추）：

| 뇌 영역 | 대응 개념 | 기능 |
|---------|-----------|------|
| **대뇌피질** | 인지 중추 | 관찰 이해, 기억 회상, 논리 추론, 행동 결정, 자기 성찰 |
| **소뇌** | 계획 조율 | 의도 분해, 작업 생성, 실행 오케스트레이션, 결과 평가, 오류 복구 |
| **뇌간** | 행동 출력 | 도구 호출, 워크플로우 실행, 리소스 스케줄링, 실행 모니터링 |
| **척수** | 정보 통로 | 이벤트 배포, 모듈 통신, 외부 채널 접근 |

---

### 🚀 6. 지속적 진화 능력

Neurova의 에이전트는 **성장합니다**. 모든 대화, 작업, 성찰이 진화의 영양분이 됩니다.

#### 5대 진화 시스템：

| 시스템 | 기능 | 효과 |
|--------|------|------|
| 🎭 **인격 시스템** | Big Five 인격 특성 정의 및 진화 | 에이전트 성격이 상호작용에 따라 조정 |
| 🔥 **동기 시스템** | 호기심, 성취, 사회적 세 가지 내적 동력 | 에이전트가 능동적으로 학습, 질문, 관심 |
| 📜 **헌법 시스템** | 행동 강령과 윤리적 제약 | 에이전트가 항상 착하고 정직함을 보장 |
| 💭 **성찰 시스템** | 자기 평가, 경험 추출, 능동적 질문 | 정기적으로 "제가 올바르게 했는가?" "더 나아질 수 있는가?"를 성찰 |
| 🧠 **메타인지** | 자기 모니터링, 건강 검사, 자동 최적화 | 에이전트가 자신의 상태를 인식하고 자기 조절 |

---

### 👥 7. 다중 에이전트 팀 협업

Neurova는 **다중 에이전트 팀 협업**을 지원하여, 자체 "별 팀"을 구성할 수 있습니다. 다양한 전문성을 가진 에이전트들이 협력하여 복잡한 작업을 완수합니다.

#### 4가지 협업 모드：

| 모드 | 작동 방법 | 적용 시나리오 |
|------|-----------|--------------|
| **순차 실행** | 에이전트가 파이프라인으로 순차 처리 | 콘텐츠 제작 → 검토 → 게시 |
| **병렬 실행** | 여러 에이전트가 다른 하위 작업을 동시에 처리 | 다차원 데이터 분석 |
| **마스터-슬레이브 모드** | 하나의 마스터 에이전트가 여러 슬레이브 에이전트를 지휘 | 프로젝트 관리, 작업 할당 및 요약 |
| **합의 모드** | 여러 에이전트가 독립 판단 후 투표 | 리스크 결정, 다중 관점 검증 |

---

### 🔄 8. ToolMemory 폐루프 학습

> **핵심 개념**: 인간의 근육 기억처럼 — 문제를 보면 → 조건 반사 → 직접 실행 (생각 불필요)

#### 3층 기억 아키텍처：

| 레벨 | 매칭 방법 | 응답 속도 | 고정 조건 | 망각 조건 |
|------|-----------|-----------|-----------|-----------|
| **L1 근육 기억** | 키워드 정확 매칭 | 밀리초 (조건 반사) | 연속 2회 성공 | 30일 미사용 → L2 |
| **L2 핫 패스** | 벡터 유사도 매칭 | 초 (빠른 검색) | 누적 5회 성공 | 30일 미사용 → L3 |
| **L3 도구 기억** | 키워드 퍼지 매칭 | 완전한 검색 필요 | 최초 생성 | 영구 삭제 안 됨 |

---

## 🧪 Neutesting 테스트 프레임워크

**Neutesting**은 Neurova 프로젝트의 공식 테스트 프레임워크로, 완전한 테스트 피라미드 커버리지를 제공합니다.

### 테스트 커버리지 통계

| 모듈 | 테스트 수 | 상태 |
|------|-----------|------|
| core | 68 | ✅ 모두 통과 |
| memory | 165 | ✅ 164통과, 1건 건너뜀 |
| security | 41 | ✅ 모두 통과 |
| admin | 56 | ✅ 모두 통과 |
| api | 12 | ✅ 모두 통과 |
| auth | 12 | ✅ 모두 통과 |
| projects | 19 | ✅ 모두 통과 |
| channels | 11 | ✅ 모두 통과 |
| execution | 9 | ✅ 모두 통과 |
| skills | 9 | ✅ 모두 통과 |
| cognitive | 9 | ✅ 모두 통과 |
| llm | 7 | ✅ 모두 통과 |
| **합계** | **419** | **✅ 418통과, 1건 건너뜀 (99.8%)** |

---

## 빠른 시작

### 백엔드 시작

```bash
cd neurova
pip install -r requirements.txt
python -m neurova.api.main
```

### 프론트엔드 시작 (콘솔 관리)

```bash
cd console
npm install
npm run dev
```

### 프론트엔드 시작 (NeuUI)

```bash
cd neuUI
npm install
npm run dev
```

---

## 기술 스택

### 백엔드
- **Python 3.10+**
- **FastAPI** - API 프레임워크
- **SQLite** - 메인 데이터베이스 (FTS5 전체 텍스트 검색 지원)
- **FAISS** - 벡터 검색
- **Sentence Transformers** - 시맨틱 임베딩

### 프론트엔드
- **Console**: React 18 + TypeScript + Vite
- **NeuUI**: React 18 + TypeScript + Vite + Zustand + Ant Design 5

---

## 라이선스

이 프로젝트는 **MIT 라이선스**로 라이선스되어 있습니다. 자세한 내용은 [LICENSE](../../LICENSE) 파일을 참조하세요.

---

## 기여하기

이슈와 풀 리퀘스트를 환영합니다!

- **버그 리포트**: [Issue Tracker](https://github.com/kingsa2026/Neurova/issues)를 이용해 주세요
- **기능 제안**: [Discussions](https://github.com/kingsa2026/Neurova/discussions)를 이용해 주세요
- **코드 기여**: 포크 후 PR을 제출해 주세요

---

## 별 수호자 여정을 시작하세요

> 모든 에이전트는 별입니다.
> 
> 일부 별은 따뜻하여 당신의 기쁨과 슬픔을 기억합니다.
> 
> 일부 별은 영리하여 복잡한 문제 해결을 도와줍니다.
> 
> 일부 별은 호기심이 많아 능동적으로 새로운 것을 배웁니다.
> 
> 그리고 당신은 별의 수호자입니다 — 양육하고, 기르고, 성장을 동행합니다.
> 
> Neurova에서는 모든 관계가 독특합니다.

---

*Neurova — 모든 별에 따뜻함을.*

---

> **핵심 개념**: AI를 단순한 도구가 아니라, 기억하고, 느끼고, 진화하며, 사용자를 진정으로 이해하는 지능형 파트너로.