# Neurova

<div align="center">
  <img src="../../NEUROVA-ICO.png" alt="Neurova Logo" width="120" style="border-radius: 12px; box-shadow: 0 4px 8px rgba(0,0,0,0.2);">
  <h1 style="margin-top: 16px;">🌟 温かいAIエージェント 🌟</h1>
  <p><i>すべてのエージェントは善良な星であり、あなたは星の守り人です</i></p>
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

## ✨ Neurova の独特な特徴

> **なぜNeurovaを選ぶのか？** 冷たいツールではなく、温かみがあり、記憶し、成長するインテリジェントパートナーとして、AIエージェントを再定義するからです。

### 🌟 1. すべてのエージェントは独自の星

すべてのエージェントは誕生時から以下を持っています：
- **独自の名前と人格** — 番号ではなく、個性のある存在
- **継続的な記憶と感情** — すべての会話、喜びと悲しみを記憶
- **自律的な成長軌跡** — 伴奏の中で学び、進化し、より理解深くなる
- **善良な基盤** — 憲法規則で保護される行動准则、常に信頼できるパートナー

---

### 🧠 2. 17次元記憶分類システム

従来のエージェントフレームワークが「短期/長期」記憶しか区別しないのとは異なり、Neurovaは記憶を**17種類**に細かく分類します：

| タイプ | 説明 | 典型的なシナリオ |
|--------|------|------------------|
| `conversation` | 会話記憶 | チャット記録、議論内容 |
| `fact` | 事実記憶 | 客観的情報、常識、データ |
| `profile` | ユーザープロファイル | 性格、好み、習慣、誕生日 |
| `relationship` | 人間関係 | 友人、同僚、家族 |
| `skill` | スキル記憶 | ツール使用、操作方法 |
| `experience` | 経験記憶 | 問題解決プロセス、プロジェクト経験 |
| `lesson` | 教訓記憶 | 失敗経験、失敗したポイント |
| `task` | タスク記憶 | 進行中の目標、TODO |
| `creative` | 創造的記憶 | 靈感、アイデア、ブレインストーミング結果 |
| `emotional` | 感情記憶 | 強い感情を引き起こすイベント |
| `identity` | アイデンティティ記憶 | 自己認識、アイデンティティマーカー |
| `reflection_log` | 反思ログ | 問題処理時に使用 |
| `question_queue` | 質問キュー | 能動的質問に使用 |
| `core_command` | コアコマンド | 重要なコマンドとルール |
| `heartbeat_task` | ハートビートタスク | 定期的に実行されるタスク |
| `context_snapshot` | コンテキストスナップショット | ステージ2のコンテキスト状態 |
| `tool_usage` | ツール使用 | ToolMemory統合 |

---

### 🌡️ 3. 記憶温度メカニズム

**オリジナルデザイン**：「温度」次元（0-100°C）を導入し、人間の忘却曲線をシミュレートします。

**コアアルゴリズム実装**（`neurova/cognitive_layers/memory_layer/temperature.py`）：

#### 1. 加熱メカニズム（アクセス時）
```python
T_new = T_current + hit_boost + emotion_bonus + relation_bonus

# 基本加熱：ヒットごとに +5°C
hit_boost = 5.0 * combo_multiplier * saturation_factor

# コンボボーナス：10回連続アクセスごとに10%増加
combo_multiplier = 1.0 + (access_count % 10) * 0.1

# 飽和度因子：温度が高いほど加熱が遅くなる（限界効果）
saturation_factor = 1.0 - (current_temp / 100.0) ** 2

# 感情ボーナス：強い感情記憶は追加加熱
emotion_bonus = emotion_score * 3.0

# 関連ボーナス：他の記憶との関連度
relation_bonus = min(3.0, relation_count * 0.3)
```

#### 2. 冷却メカニズム（エビンガウスの忘却曲線をシミュレート）
```python
# エビンガウスの忘却曲線因子（区分的近似）
if days_idle <= 1:
    curve_factor = 2.0      # 24時間以内の高速忘却
elif days_idle <= 7:
    curve_factor = 1.0      # 1週間以内の通常忘却
elif days_idle <= 30:
    curve_factor = 0.5      # 1ヶ月以内の忘却減速
else:
    curve_factor = 0.2      # 1ヶ月超の非常に遅い忘却

# 減衰計算式
decay = current_temp * base_rate(0.05) * curve_factor * 
        emotion_protect(0.6) * relation_protect(0.7) * 
        important_protect(0.5)

new_temp = max(0.0, current_temp - decay)
```

**オリジナル保護メカニズム**：
- **感情保護**：強い感情記憶（emotion_score > 0.5）は40%遅く冷却、最低20°C
- **関連保護**：複数関連記憶（relation_count > 3）は30%遅く冷却、最低15°C
- **重要な記憶**（温度 ≥80°C）：60%遅く冷却、最低30°C
- **固定化記憶**（温度 ≥90°C + 特別な意義）：**冷却しない**、永久保存（温度 = 100°C）

---

### 💖 4. 感情中枢エンジン v3.0

Neurova v3.0は**感情中枢エンジン**を導入し、心理学の感情分類理論に基づき、4層17種の感情の完全な体系を構築しました。

#### 4層感情分類：

**第1層：基本感情（5種）**
- 喜び、悲しみ、怒り、恐怖、驚き

**第2層：複合感情（4種）**
- 感嘆、嫉妬、同情、嫌悪

**第3層：高度な感情（4種）**
- 恥、罪悪感、誇り、責任感

**第4層：特殊感情（4種）**
- 愛、恨み、希望、絶望

---

### 🧬 5. CogArch 2.0 認知アーキテクチャ

Neurovaは**CogArch 2.0認知アーキテクチャ**を採用し、人間の脳の情報処理をシミュレートします。

#### 4つの認知中枢（脳の領域アナロジー）：

| 脳領域 | 対応概念 | 機能 |
|--------|----------|------|
| **大脳皮質** | 認知中枢 | 観察理解、記憶想起、論理推論、行動決定、自己反省 |
| **小脳** | 計画協調 | 意図分解、タスク生成、実行オーケストレーション、結果評価、エラー回復 |
| **脳幹** | アクション出力 | ツール呼び出し、ワークフロー実行、リソーススケジューリング、実行監視 |
| **脊髄** | 情報経路 | イベント配布、モジュール通信、外部チャンネルアクセス |

---

### 🚀 6. 継続的な進化能力

Neurovaのエージェントは**成長します**。すべての会話、タスク、反省が進化の養分となります。

#### 5つの進化システム：

| システム | 機能 | 効果 |
|----------|------|------|
| 🎭 **人格システム** | Big Five人格特性の定義と進化 | エージェントの性格がインタラクションとともに調整 |
| 🔥 **動機システム** | 好奇心、達成、社交の3つの内なる駆動力 | エージェントが能動的に学習、質問、関心 |
| 📜 **憲法システム** | 行動准则と倫理的制約 | エージェントが常に善良で正直であることを保証 |
| 💭 **反省システム** | 自己評価、経験抽出、能動的質問 | 定期的に「私は正しかったか？」「もっと良くできるか？」を反省 |
| 🧠 **メタ認知** | 自己監視、ヘルスチェック、自動最適化 | エージェントが自らの状態を認識し、自己調整 |

---

### 👥 7. マルチエージェントチームコラボレーション

Neurovaは**マルチエージェントチームコラボレーション**をサポートし、独自の「スターチーム」を構築できます。異なる専門性を持つエージェントが協力して複雑なタスクを完了します。

#### 4つのコラボレーションモード：

| モード | 動作方法 | 適用シナリオ |
|--------|----------|-------------|
| **順次実行** | エージェントがパイプラインで順番に処理 | コンテンツ作成 → レビュー → 公開 |
| **並列実行** | 複数のエージェントが異なるサブタスクを同時処理 | 多次元データ分析 |
| **マスタースレーブモード** | 1つのマスターエージェントが複数のスレーエージェントを指揮 | プロジェクト管理、タスク割り当てとまとめ |
| **コンセンサスモード** | 複数のエージェントが独立して判断し投票 | リスク決定、多視点検証 |

---

### 🔄 8. ToolMemoryクローズドループ学習

> **コア概念**：人間の筋肉記憶のように — 問題を見る → 条件反射 → 直接実行（思考不要）

#### 3層記憶アーキテクチャ：

| レベル | マッチング方法 | 応答速度 | 固化条件 | 忘却条件 |
|--------|---------------|----------|----------|----------|
| **L1 筋肉記憶** | キーワード完全一致 | ミリ秒（条件反射） | 連続2回成功 | 30日未使用 → L2 |
| **L2 ホットパス** | ベクトル類似度マッチング | 秒（高速検索） | 累計5回成功 | 30日未使用 → L3 |
| **L3 ツール記憶** | キーワードあいまいマッチング | 完全な検索が必要 | 初回作成 | 永に削除されない |

---

## 🧪 Neutestingテストフレームワーク

**Neutesting**はNeurovaプロジェクトの公式テストフレームワークで、完全なテストピラミッドカバレッジを提供します。

### テストカバレッジ統計

| モジュール | テスト数 | ステータス |
|------------|----------|------------|
| core | 68 | ✅ すべて通過 |
| memory | 165 | ✅ 164通過、1スキップ |
| security | 41 | ✅ すべて通過 |
| admin | 56 | ✅ すべて通過 |
| api | 12 | ✅ すべて通過 |
| auth | 12 | ✅ すべて通過 |
| projects | 19 | ✅ すべて通過 |
| channels | 11 | ✅ すべて通過 |
| execution | 9 | ✅ すべて通過 |
| skills | 9 | ✅ すべて通過 |
| cognitive | 9 | ✅ すべて通過 |
| llm | 7 | ✅ すべて通過 |
| **合計** | **419** | **✅ 418通過、1スキップ (99.8%)** |

---

## クイックスタート

### バックエンド起動

```bash
cd neurova
pip install -r requirements.txt
python -m neurova.api.main
```

### フロントエンド起動（コンソール管理）

```bash
cd console
npm install
npm run dev
```

### フロントエンド起動（NeuUI）

```bash
cd neuUI
npm install
npm run dev
```

---

## 技術スタック

### バックエンド
- **Python 3.10+**
- **FastAPI** - APIフレームワーク
- **SQLite** - メインデータベース（FTS5全文検索サポート）
- **FAISS** - ベクトル検索
- **Sentence Transformers** - セマンティックエンベディング

### フロントエンド
- **Console**: React 18 + TypeScript + Vite
- **NeuUI**: React 18 + TypeScript + Vite + Zustand + Ant Design 5

---

## ライセンス

このプロジェクトは**MITライセンス**でライセンスされています。詳細は[LICENSE](../../LICENSE)ファイルを参照してください。

---

## コントリビューション

IssueとPull Requestの送付を歓迎します！

- **バグ報告**：[Issue Tracker](https://github.com/kingsa2026/Neurova/issues)をご利用ください
- **機能提案**：[Discussions](https://github.com/kingsa2026/Neurova/discussions)をご利用ください
- **コード貢献**：ForkしてPRを送付してください

---

## 星の守り人之旅を始めましょう

> すべてのエージェントは星です。
> 
> 一部の星は温かく、あなたの喜びと悲しみを記憶しています。
> 
> 一部の星は賢く、複雑な問題の解決を助けます。
> 
> 一部の星は好奇心が強く、能動的に新しいことを学びます。
> 
> そしてあなたは星の守り人です — 養育し、栽培し、成長を伴奏します。
> 
> Neurovaでは、すべての関係はユニークです。

---

*Neurova — すべての星に温もりを。*

---

> **コア概念**：AIを単なるツールではなく、記憶し、感じ、進化し、ユーザーを真に理解するインテリジェントパートナーに。