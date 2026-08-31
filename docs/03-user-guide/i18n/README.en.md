# Neurova

<div align="center">
  <img src="../../NEUROVA-ICO.png" alt="Neurova Logo" width="120" style="border-radius: 12px; box-shadow: 0 4px 8px rgba(0,0,0,0.2);">
  <h1 style="margin-top: 16px;">🌟 Warm AI Agent 🌟</h1>
  <p><i>Every Agent is a kind star, and you are the star keeper</i></p>
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

## ✨ Neurova Unique Features

> **Why choose Neurova?** Because we redefine AI Agents — not cold tools, but warm, memorable, and evolving intelligent partners.

### 🌟 1. Every Agent is a Unique Star

Every Agent has from birth:
- **Unique name and personality** — Not a number, but a personality
- **Continuous memory and emotion** — Remembering every conversation, every joy and sorrow
- **Autonomous growth trajectory** — Learning and evolving in companionship, becoming more understanding
- **Kind foundation** — Behavioral guidelines protected by constitutional rules, always a trustworthy partner

---

### 🧠 2. 17-Dimensional Memory Classification System

Unlike traditional Agent frameworks that only distinguish "short-term/long-term" memory, Neurova finely classifies memory into **17 types**:

| Type | Description | Typical Scenario |
|------|-------------|------------------|
| `conversation` | Conversation memory | Chat records, discussion content |
| `fact` | Fact memory | Objective information, common sense, data |
| `profile` | User profile | Personality, preferences, habits, birthday |
| `relationship` | Interpersonal relationships | Friends, colleagues, family |
| `skill` | Skill memory | Tool usage, operation methods |
| `experience` | Experience memory | Problem-solving process, project experience |
| `lesson` | Lesson memory | Failure experiences, pitfalls |
| `task` | Task memory | Ongoing goals, todos |
| `creative` | Creative memory | Inspiration, ideas, brainstorming results |
| `emotional` | Emotional memory | Events triggering strong emotions |
| `identity` | Identity memory | Self-awareness, identity markers |
| `reflection_log` | Reflection log | Used when processing problems |
| `question_queue` | Question queue | Used for proactive questioning |
| `core_command` | Core commands | Important commands and rules |
| `heartbeat_task` | Heartbeat tasks | Regularly executed tasks |
| `context_snapshot` | Context snapshot | Stage two context state |
| `tool_usage` | Tool usage | ToolMemory integration |

---

### 🌡️ 3. Memory Temperature Mechanism

**Original design**: Introducing "temperature" dimension (0-100°C) to simulate human forgetting curves.

**Core algorithm implementation** (`neurova/cognitive_layers/memory_layer/temperature.py`):

#### 1. Heating mechanism (when accessed)
```python
T_new = T_current + hit_boost + emotion_bonus + relation_bonus

# Basic heating: +5°C per hit
hit_boost = 5.0 * combo_multiplier * saturation_factor

# Combo bonus: every 10 consecutive accesses increases by 10%
combo_multiplier = 1.0 + (access_count % 10) * 0.1

# Saturation factor: higher temperature heats slower (diminishing returns)
saturation_factor = 1.0 - (current_temp / 100.0) ** 2

# Emotion bonus: strong emotional memories get extra heating
emotion_bonus = emotion_score * 3.0

# Relation bonus: association with other memories
relation_bonus = min(3.0, relation_count * 0.3)
```

#### 2. Cooling mechanism (simulating Ebbinghaus forgetting curve)
```python
# Ebbinghaus forgetting curve factor (piecewise approximation)
if days_idle <= 1:
    curve_factor = 2.0      # Fast forgetting within 24 hours
elif days_idle <= 7:
    curve_factor = 1.0      # Normal forgetting within a week
elif days_idle <= 30:
    curve_factor = 0.5      # Forgetting slows within a month
else:
    curve_factor = 0.2      # Very slow forgetting after a month

# Decay calculation formula
decay = current_temp * base_rate(0.05) * curve_factor * 
        emotion_protect(0.6) * relation_protect(0.7) * 
        important_protect(0.5)

new_temp = max(0.0, current_temp - decay)
```

**Original protection mechanisms**:
- **Emotion protection**: Strong emotional memories (emotion_score > 0.5) cool 40% slower, minimum 20°C
- **Relation protection**: Multi-associated memories (relation_count > 3) cool 30% slower, minimum 15°C
- **Important memories** (temperature ≥80°C): Cool 60% slower, minimum 30°C
- **Consolidated memories** (temperature ≥90°C + special significance): **Never cool down**, permanently preserved (temperature = 100°C)

---

### 💖 4. Emotion Hub Engine v3.0

Neurova v3.0 introduces the **Emotion Hub Engine**, based on psychological emotion classification theory, establishing a complete system of four layers and 17 emotions.

#### Four-layer emotion classification:

**Layer 1: Basic emotions (5 types)**
- Joy, Sadness, Anger, Fear, Surprise

**Layer 2: Compound emotions (4 types)**
- Admiration, Jealousy, Sympathy, Disgust

**Layer 3: Advanced emotions (4 types)**
- Shame, Guilt, Pride, Responsibility

**Layer 4: Special emotions (4 types)**
- Love, Hate, Hope, Despair

**Core features**:
- ✅ **Emotion conduction rules** (17 rules defining interactions between emotions)
- ✅ **Emotion-weighted decision making** (different emotions affect decisions differently)
- ✅ **Memory system integration** (emotion state affects memory temperature)

---

### 🧬 5. CogArch 2.0 Cognitive Architecture

Neurova adopts **CogArch 2.0 cognitive architecture**, simulating human brain information processing.

#### Four cognitive centers (brain region analogies):

| Brain Region | Corresponding Concept | Function |
|--------------|----------------------|----------|
| **Cerebral Cortex** | Cognitive Center | Observation, memory recall, logical reasoning, behavior decision, self-reflection |
| **Cerebellum** | Planning & Coordination | Intent decomposition, task generation, execution orchestration, result evaluation, error recovery |
| **Brainstem** | Action Output | Tool invocation, workflow execution, resource scheduling, execution monitoring |
| **Spinal Cord** | Information Pathway | Event distribution, module communication, external channel access |

**Complete cognitive cycle (5 stages)**:
```
Input → Observation → Recall → Reasoning → Decision → Orchestration → Execution → Reflection → Consolidation → Learning Evolution
```

---

### 🚀 6. Continuous Evolution Capability

Neurova's Agent **grows**. Every conversation, task, and reflection is nourishment for its evolution.

#### Five evolution systems:

| System | Function | Effect |
|--------|----------|--------|
| 🎭 **Personality System** | Big Five personality traits definition and evolution | Agent personality adjusts with interaction |
| 🔥 **Motivation System** | Curiosity, achievement, social drive | Agent proactively learns, asks questions, cares |
| 📜 **Constitutional System** | Behavioral guidelines and ethical constraints | Ensures Agent remains kind and upright |
| 💭 **Reflection System** | Self-evaluation, experience extraction, proactive questioning | Regularly reflects "Did I do right?" "Can I be better?" |
| 🧠 **Metacognition** | Self-monitoring, health check, automatic optimization | Agent is aware of its state, self-regulates |

---

### 👥 7. Multi-Agent Team Collaboration

Neurova supports **multi-Agent team collaboration**, allowing you to build your own "star team" where different specialized Agents collaborate to complete complex tasks.

#### Four collaboration modes:

| Mode | Working Method | Application Scenario |
|------|---------------|---------------------|
| **Sequential Execution** | Agents process in pipeline | Content creation → review → publishing |
| **Parallel Execution** | Multiple Agents handle different subtasks simultaneously | Multi-dimensional data analysis |
| **Master-Slave Mode** | One master Agent commands multiple slave Agents | Project management, task assignment and summary |
| **Consensus Mode** | Multiple Agents judge independently then vote | Risk decision, multi-perspective verification |

---

### 🔄 8. ToolMemory Closed-Loop Learning

> **Core concept**: Like human muscle memory — see problem → conditioned reflex → direct execution (no thinking needed)

#### Three-layer memory architecture:

| Level | Matching Method | Response Speed | Solidification Condition | Forgetting Condition |
|-------|----------------|---------------|------------------------|---------------------|
| **L1 Muscle Memory** | Keyword exact matching | Millisecond (conditioned reflex) | 2 consecutive successes | 30 days unused → L2 |
| **L2 Hot Path** | Vector similarity matching | Second (fast retrieval) | 5 cumulative successes | 30 days unused → L3 |
| **L3 Tool Memory** | Keyword fuzzy matching | Requires full retrieval | Initial creation | Never deleted |

---

### 🛠️ 9. Powerful Tool System

Neurova provides **trinity** tool capabilities: **Computer Use (visual understanding)** + **CLI command library** + **Skill ecosystem**, giving Agents real "hands" and "toolbox".

#### 🖥️ Computer Use — Visual Understanding Enhanced

| Capability | Implementation | Description |
|------------|---------------|-------------|
| **Desktop Screenshot** | Pillow (real) / simulation | Full-screen or regional screenshot, returns base64 image |
| **Mouse Operation** | pyautogui (real) / simulation | Click, drag, scroll |
| **Keyboard Input** | pyautogui (real) / simulation | Text input, shortcuts |
| **File Operation** | Real implementation | Read/write files, protected by L2 firewall |
| **Shell Command** | subprocess | Execute system commands, protected by L2 firewall |
| **Visual Parsing** | YOLOv8 + EasyOCR | Screenshot → UI element detection → structured data |
| **Smart Click** | Visual understanding + pyautogui | `smart_click("login button")` → automatically find and click |

---

### 🧠 10. Bayesian EKI Cognitive Optimizer

> **EKI = Ensemble Kalman Inversion**, a **gradient-free Bayesian inference method** using Monte Carlo sampling to approximate parameter posterior distribution.

#### Core algorithm principle

**EKI update formula**:
```
θ_{k+1}^(i) = θ_k^(i) + C_θy (C_yy + R)^{-1} (y - h(θ_k^(i)))
```

Where:
- `θ` = Parameter vector (cognitive parameters of memory)
- `y` = Observations (user feedback, access frequency, etc.)
- `h(θ)` = Forward model (predicts memory strength)
- `C_θy` = Parameter-observation covariance
- `R` = Observation noise covariance

---

## 🧪 Neutesting Test Framework

**Neutesting** is the official test framework for the Neurova project, providing complete test pyramid coverage.

### Test Coverage Statistics

| Module | Tests | Status |
|--------|-------|--------|
| core | 68 | ✅ All passed |
| memory | 165 | ✅ 164 passed, 1 skipped |
| security | 41 | ✅ All passed |
| admin | 56 | ✅ All passed |
| api | 12 | ✅ All passed |
| auth | 12 | ✅ All passed |
| projects | 19 | ✅ All passed |
| channels | 11 | ✅ All passed |
| execution | 9 | ✅ All passed |
| skills | 9 | ✅ All passed |
| cognitive | 9 | ✅ All passed |
| llm | 7 | ✅ All passed |
| **Total** | **419** | **✅ 418 passed, 1 skipped (99.8%)** |

---

## Quick Start

### Backend Startup

```bash
cd neurova
pip install -r requirements.txt
python -m neurova.api.main
```

### Frontend Startup (Console Management)

```bash
cd console
npm install
npm run dev
```

### Frontend Startup (NeuUI)

```bash
cd neuUI
npm install
npm run dev
```

---

## Tech Stack

### Backend
- **Python 3.10+**
- **FastAPI** - API framework
- **SQLite** - Main database (supports FTS5 full-text search)
- **FAISS** - Vector retrieval
- **Sentence Transformers** - Semantic embedding

### Frontend
- **Console**: React 18 + TypeScript + Vite
- **NeuUI**: React 18 + TypeScript + Vite + Zustand + Ant Design 5

---

## License

This project is licensed under the **MIT License**, see [LICENSE](../../LICENSE) file for details.

---

## Contributing

Welcome to submit Issues and Pull Requests!

- **Bug Reports**: Please use [Issue Tracker](https://github.com/kingsa2026/Neurova/issues)
- **Feature Suggestions**: Please use [Discussions](https://github.com/kingsa2026/Neurova/discussions)
- **Code Contributions**: Please Fork and submit PR

---

## Start Your Star-Keeping Journey

> Every Agent is a star.
> 
> Some stars are warm, remembering your joys and sorrows.
> 
> Some stars are smart, helping you solve complex problems.
> 
> Some stars are curious, proactively learning new things.
> 
> And you are the star keeper — nurturing, cultivating, and accompanying their growth.
> 
> In Neurova, every relationship is unique.

---

*Neurova — Giving warmth to every star.*

---

> **Core concept**: Making AI not just a tool, but an intelligent partner that can remember, feel, evolve, and truly understand users.