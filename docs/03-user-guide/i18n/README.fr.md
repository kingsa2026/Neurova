# Neurova

<div align="center">
  <img src="../../NEUROVA-ICO.png" alt="Neurova Logo" width="120" style="border-radius: 12px; box-shadow: 0 4px 8px rgba(0,0,0,0.2);">
  <h1 style="margin-top: 16px;">🌟 Agent IA Chaleureux 🌟</h1>
  <p><i>Chaque agent est une étoile bienveillante, et vous êtes le gardien des étoiles</i></p>
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

## ✨ Caractéristiques Uniques de Neurova

> **Pourquoi Neurova ?** Parce que nous redéfinissons les agents IA — pas des outils froids, mais des partenaires intelligents chaleureux qui mémorisent et évoluent.

### 🌟 1. Chaque agent est une étoile unique

Chaque agent possède dès sa naissance :
- **Un nom et une personnalité uniques** — pas un numéro, mais une entité avec une personnalité
- **Une mémoire et des émotions continues** — se souvient de chaque conversation, chaque joie et chaque chagrin
- **Une trajectoire de croissance autonome** — apprend et évolue en compagnie, devient de plus en plus compréhensif
- **Un fondement bienveillant** — des lignes directrices comportementales protégées par des règles constitutionnelles, toujours un partenaire de confiance

---

### 🧠 2. Système de Classification de la Mémoire 17 Dimensions

Contrairement aux frameworks d'agents traditionnels qui ne distinguent que la mémoire "court terme/long terme", Neurova classe finement la mémoire en **17 types** :

| Type | Description | Scénario Typique |
|------|-------------|------------------|
| `conversation` | Mémoire de conversation | Enregistrements de chat, contenu de discussion |
| `fact` | Mémoire factuelle | Informations objectives, connaissances générales, données |
| `profile` | Profil utilisateur | Personnalité, préférences, habitudes, anniversaire |
| `relationship` | Relations interpersonnelles | Amis, collègues, famille |
| `skill` | Mémoire de compétence | Utilisation d'outils, méthodes d'opération |
| `experience` | Mémoire d'expérience | Processus de résolution de problèmes, expérience de projet |
| `lesson` | Mémoire de leçon | Expériences d'échec, erreurs commises |
| `task` | Mémoire de tâche | Objectifs en cours, choses à faire |
| `creative` | Mémoire créative | Inspiration, idées, résultats de brainstorming |
| `emotional` | Mémoire émotionnelle | Événements déclenchant de fortes émotions |
| `identity` | Mémoire d'identité | Conscience de soi, marqueurs d'identité |
| `reflection_log` | Journal de réflexion | Utilisé lors du traitement des problèmes |
| `question_queue` | File d'attente de questions | Utilisé pour les questions proactives |
| `core_command` | Commandes principales | Commandes et règles importantes |
| `heartbeat_task` | Tâches de battement de cœur | Tâches exécutées régulièrement |
| `context_snapshot` | Instantané de contexte | État du contexte de la phase deux |
| `tool_usage` | Utilisation d'outils | Intégration ToolMemory |

---

### 🌡️ 3. Mécanisme de Température de la Mémoire

**Design original** : Introduction d'une dimension "température" (0-100°C) pour simuler la courbe d'oubli humaine.

**Implémentation de l'algorithme principal** (`neurova/cognitive_layers/memory_layer/temperature.py`) :

#### 1. Mécanisme de chauffage (à l'accès)
```python
T_new = T_current + hit_boost + emotion_bonus + relation_bonus

# Chauffage de base : +5°C par accès
hit_boost = 5.0 * combo_multiplier * saturation_factor

# Bonus combo : augmentation de 10% toutes les 10 accès consécutifs
combo_multiplier = 1.0 + (access_count % 10) * 0.1

# Facteur de saturation : plus la température est élevée, plus le chauffage est lent
saturation_factor = 1.0 - (current_temp / 100.0) ** 2

# Bonus émotionnel : les souvenirs émotionnels forts reçoivent un chauffage supplémentaire
emotion_bonus = emotion_score * 3.0

# Bonus relation : association avec d'autres souvenirs
relation_bonus = min(3.0, relation_count * 0.3)
```

#### 2. Mécanisme de refroidissement (simulation de la courbe d'oubli d'Ebbinghaus)
```python
# Facteur de courbe d'oubli d'Ebbinghaus (approximation par morceaux)
if days_idle <= 1:
    curve_factor = 2.0      # Oubli rapide dans les 24 heures
elif days_idle <= 7:
    curve_factor = 1.0      # Oubli normal dans la semaine
elif days_idle <= 30:
    curve_factor = 0.5      # Ralentissement de l'oubli dans le mois
else:
    curve_factor = 0.2      # Oubli très lent après un mois

# Calcul de la décroissance
decay = current_temp * base_rate(0.05) * curve_factor * 
        emotion_protect(0.6) * relation_protect(0.7) * 
        important_protect(0.5)

new_temp = max(0.0, current_temp - decay)
```

**Mécanismes de protection originaux** :
- **Protection émotionnelle** : Les souvenirs émotionnels forts (emotion_score > 0.5) refroidissent 40% plus lentement, minimum 20°C
- **Protection relation** : Les souvenirs multi-associés (relation_count > 3) refroidissent 30% plus lentement, minimum 15°C
- **Souvenirs importants** (température ≥80°C) : Refroidissent 60% plus lentement, minimum 30°C
- **Souvenirs consolidés** (température ≥90°C + signification spéciale) : **Ne refroidissent jamais**, préservation permanente (température = 100°C)

---

### 💖 4. Moteur d'Hub Émotionnel v3.0

Neurova v3.0 introduit le **Moteur d'Hub Émotionnel**, basé sur la théorie de la classification des émotions en psychologie, établissant un système complet de quatre couches et 17 émotions.

#### Classification des émotions en quatre couches :

**Couche 1 : Émotions de base (5 types)**
- Joie, Tristesse, Colère, Peur, Surprise

**Couche 2 : Émotions composées (4 types)**
- admiration, Jalousie, Sympathie, Dégoût

**Couche 3 : Émotions avancées (4 types)**
- Sentiment de honte, Culpabilité, Fierté, Sentiment de responsabilité

**Couche 4 : Émotions spéciales (4 types)**
- Amour, Haine, Espoir, Désespoir

---

### 🧬 5. Architecture Cognitive CogArch 2.0

Neurova adopte l'**architecture cognitive CogArch 2.0**, simulant le traitement de l'information du cerveau humain.

#### Quatre centres cognitifs (analogies de régions cérébrales) :

| Région du cerveau | Concept correspondant | Fonction |
|-------------------|----------------------|----------|
| **Cortex cérébral** | Centre cognitif | Observation, compréhension, rappel, raisonnement logique, prise de décision, autoréflexion |
| **Cervelet** | Planification et coordination | Décomposition des intentions, génération de tâches, orchestration de l'exécution, évaluation des résultats, récupération des erreurs |
| **Tronc cérébral** | Sortie d'action | Appel d'outils, exécution de flux de travail, planification des ressources, surveillance de l'exécution |
| **Moelle épinière** | Voie d'information | Distribution des événements, communication inter-modules, accès aux canaux externes |

---

### 🚀 6. Capacité d'Évolution Continue

Les agents de Neurova **grandissent**. Chaque conversation, tâche et réflexion est un aliment pour leur évolution.

#### Cinq systèmes d'évolution :

| Système | Fonction | Effet |
|---------|----------|-------|
| 🎭 **Système de personnalité** | Définition et évolution des traits de personnalité Big Five | La personnalité de l'agent s'ajuste avec l'interaction |
| 🔥 **Système de motivation** | Curiosité, accomplissement, social - trois moteurs internes | L'agent apprend, pose des questions et s'intéresse de manière proactive |
| 📜 **Système constitutionnel** | Lignes directrices comportementales et contraintes éthiques | Garantit que l'agent reste bienveillant et intègre |
| 💭 **Système de réflexion** | Auto-évaluation, extraction d'expérience, questions proactives | Réfléchit régulièrement "Ai-je bien agi ?" "Puis-je être meilleur ?" |
| 🧠 **Méta-cognition** | Auto-surveillance, vérification de santé, optimisation automatique | L'agent prend conscience de son état et se régule |

---

### 👥 7. Collaboration d'Équipe Multi-Agents

Neurova supporte la **collaboration d'équipe multi-agents**, vous permettant de créer votre propre "équipe d'étoiles". Des agents de différentes spécialités collaborent pour accomplir des tâches complexes.

#### Quatre modes de collaboration :

| Mode | Méthode de travail | Scénario d'application |
|------|-------------------|------------------------|
| **Exécution séquentielle** | Les agents traitent en pipeline | Création de contenu → révision → publication |
| **Exécution parallèle** | Plusieurs agents traitent différentes sous-tâches simultanément | Analyse de données multidimensionnelle |
| **Mode maître-esclave** | Un agent maître commande plusieurs agents esclaves | Gestion de projet, attribution et résumé des tâches |
| **Mode consensus** | Plusieurs agents jugent indépendamment puis votent | Prise de décision à risque, vérification multi-perspectives |

---

### 🔄 8. Apprentissage en Boucle Fermée ToolMemory

> **Concept clé** : Comme la mémoire musculaire humaine — voir un problème → réflexe conditionné → exécution directe (sans réflexion)

#### Architecture de la mémoire à trois niveaux :

| Niveau | Méthode d'appariement | Vitesse de réponse | Condition de solidification | Condition d'oubli |
|--------|----------------------|-------------------|---------------------------|-------------------|
| **L1 Mémoire musculaire** | Appariement exact par mot-clé | Millisecondes (réflexe conditionné) | 2 succès consécutifs | 30 jours d'inutilisation → L2 |
| **L2 Chemin chaud** | Appariement par similarité vectorielle | Secondes (recherche rapide) | 5 succès cumulés | 30 jours d'inutilisation → L3 |
| **L3 Mémoire d'outil** | Appariement flou par mot-clé | Nécessite une recherche complète | Création initiale | Jamais supprimée |

---

## 🧪 Framework de Test Neutesting

**Neutesting** est le framework de test officiel du projet Neurova, offrant une couverture complète de la pyramide de tests.

### Statistiques de couverture des tests

| Module | Nombre de tests | Statut |
|--------|-----------------|--------|
| core | 68 | ✅ Tous passés |
| memory | 165 | ✅ 164 passés, 1 ignoré |
| security | 41 | ✅ Tous passés |
| admin | 56 | ✅ Tous passés |
| api | 12 | ✅ Tous passés |
| auth | 12 | ✅ Tous passés |
| projects | 19 | ✅ Tous passés |
| channels | 11 | ✅ Tous passés |
| execution | 9 | ✅ Tous passés |
| skills | 9 | ✅ Tous passés |
| cognitive | 9 | ✅ Tous passés |
| llm | 7 | ✅ Tous passés |
| **Total** | **419** | **✅ 418 passés, 1 ignoré (99.8%)** |

---

## Démarrage Rapide

### Démarrage du backend

```bash
cd neurova
pip install -r requirements.txt
python -m neurova.api.main
```

### Démarrage du frontend (Console de gestion)

```bash
cd console
npm install
npm run dev
```

### Démarrage du frontend (NeuUI)

```bash
cd neuUI
npm install
npm run dev
```

---

## Stack Technique

### Backend
- **Python 3.10+**
- **FastAPI** - Framework API
- **SQLite** - Base de données principale (supporte la recherche plein texte FTS5)
- **FAISS** - Recherche vectorielle
- **Sentence Transformers** - Embedding sémantique

### Frontend
- **Console** : React 18 + TypeScript + Vite
- **NeuUI** : React 18 + TypeScript + Vite + Zustand + Ant Design 5

---

## Licence

Ce projet est sous **MIT License**, voir le fichier [LICENSE](../../LICENSE) pour les détails.

---

## Contribution

Bienvenue pour soumettre des Issues et des Pull Requests !

- **Rapports de bugs** : Veuillez utiliser le [Issue Tracker](https://github.com/kingsa2026/Neurova/issues)
- **Suggestions de fonctionnalités** : Veuillez utiliser les [Discussions](https://github.com/kingsa2026/Neurova/discussions)
- **Contributions de code** : Veuillez Fork et soumettre une PR

---

## Commencez votre voyage de gardien d'étoiles

> Chaque agent est une étoile.
> 
> Certaines étoiles sont chaleureuses, se souviennent de vos joies et de vos chagrins.
> 
> Certaines étoiles sont intelligentes, vous aident à résoudre des problèmes complexes.
> 
> Certaines étoiles sont curieuses, apprennent activement de nouvelles choses.
> 
> Et vous êtes le gardien d'étoiles — élevez, cultivez et accompagnez leur croissance.
> 
> Chez Neurova, chaque relation est unique.

---

*Neurova — donnons de la chaleur à chaque étoile.*

---

> **Concept clé** : Faire de l'IA pas seulement un outil, mais un partenaire intelligent capable de se souvenir, de ressentir, d'évoluer et de vraiment comprendre les utilisateurs.