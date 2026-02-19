# The Longevity Alchemist — Claude Code Build Prompt

> **What this is:** A complete specification for Claude Code to build a full-stack AI health coaching application. Follow this document sequentially. Do not skip sections. Ask clarifying questions if any requirement is ambiguous.

---

## ATLAS Phase A — Architecture Brief

**Problem:** People using AI chat for daily health coaching lose all context when conversations get long or reset. This app solves that by maintaining persistent user profiles, structured health logs, and rolling summaries that feed into every AI interaction — giving users a coach that truly *remembers* them.

**User:** Health-conscious adults (primary: men 50+) managing weight loss, blood pressure, cholesterol, fitness, fasting, and supplement regimens. Multi-user — a family can share one deployment, each with their own profile.

**Success Criteria:**
- A user can log food/vitals/workouts via text, voice, or photo and get contextually aware coaching that references their history
- The app works seamlessly on desktop browsers, iPhone Safari, and Android Chrome
- Context never "resets" — summaries keep the AI informed across weeks and months
- Users bring their own API key (Anthropic, OpenAI, or Google) and control costs

**Constraints:**
- SQLite database (file-based, portable)
- Docker-containerized for deployment
- No paid external services required beyond the user's chosen LLM API key
- Must be responsive/PWA — not a native app

---

## ATLAS Phase T — Trace (Design Before Building)

### Technology Stack

| Layer | Choice | Rationale |
|-------|--------|-----------|
| **Backend** | Python 3.11+ / FastAPI | Async, typed, excellent for AI orchestration |
| **Database** | SQLite via SQLAlchemy + Alembic | Portable, zero-config, Docker-friendly |
| **Frontend** | React 18 + TypeScript + Tailwind CSS | Responsive, PWA-capable, component-based |
| **Build** | Vite | Fast builds, good mobile debugging |
| **Auth** | Simple username/password with bcrypt + JWT | Self-hosted, no OAuth dependencies |
| **Voice Input** | Browser Web Speech API | Free, client-side, no API costs |
| **Image Input** | HTML file input → sent to vision-capable LLM | Works across all devices |
| **AI Providers** | Anthropic Claude, OpenAI GPT, Google Gemini | User brings their own key |
| **Web Search** | Each provider's native search capability | No extra API keys needed |
| **Containerization** | Docker + docker-compose | Single command deployment |

### Data Schema

```sql
-- Users & Authentication
CREATE TABLE users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    display_name TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Per-user AI provider configuration
CREATE TABLE user_settings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    -- AI Provider Config
    ai_provider TEXT NOT NULL DEFAULT 'anthropic',  -- 'anthropic' | 'openai' | 'google'
    api_key_encrypted TEXT,  -- encrypted at rest
    reasoning_model TEXT DEFAULT 'claude-sonnet-4-20250514',
    utility_model TEXT DEFAULT 'claude-haiku-4-5-20251001',
    -- User Profile (structured, always available to AI)
    age INTEGER,
    sex TEXT,  -- 'male' | 'female'
    height_cm REAL,
    current_weight_kg REAL,
    goal_weight_kg REAL,
    medical_conditions TEXT,  -- JSON array
    medications TEXT,  -- JSON array of {name, dose, timing, purpose}
    supplements TEXT,  -- JSON array of {name, dose, timing}
    family_history TEXT,  -- JSON array
    fitness_level TEXT,  -- 'beginner' | 'intermediate' | 'advanced'
    dietary_preferences TEXT,  -- JSON array
    health_goals TEXT,  -- JSON array
    timezone TEXT DEFAULT 'America/Edmonton',
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Specialist personality configuration
CREATE TABLE specialist_config (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    active_specialist TEXT DEFAULT 'auto',  -- 'auto' | 'nutritionist' | 'sleep' | 'movement' | 'supplement' | 'safety' | 'orchestrator'
    specialist_overrides TEXT,  -- JSON: per-specialist custom instructions
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Chat messages (full history, per user)
CREATE TABLE messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    role TEXT NOT NULL,  -- 'user' | 'assistant' | 'system'
    content TEXT NOT NULL,
    specialist_used TEXT,  -- which specialist handled this
    model_used TEXT,  -- which model was used
    tokens_in INTEGER,
    tokens_out INTEGER,
    has_image BOOLEAN DEFAULT FALSE,
    image_path TEXT,  -- local path to stored image
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Structured health logs (parsed from conversations)
CREATE TABLE food_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    logged_at TIMESTAMP NOT NULL,
    meal_label TEXT,  -- 'Meal 1', 'Snack', 'Dinner', etc.
    items TEXT NOT NULL,  -- JSON array of {name, quantity, unit}
    calories REAL,
    protein_g REAL,
    carbs_g REAL,
    fat_g REAL,
    fiber_g REAL,
    sodium_mg REAL,
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE hydration_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    logged_at TIMESTAMP NOT NULL,
    amount_ml REAL NOT NULL,
    source TEXT,  -- 'water', 'coffee', 'broth', 'food_moisture', etc.
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE vitals_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    logged_at TIMESTAMP NOT NULL,
    weight_kg REAL,
    bp_systolic INTEGER,
    bp_diastolic INTEGER,
    heart_rate INTEGER,
    blood_glucose REAL,
    temperature_c REAL,
    spo2 REAL,
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE exercise_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    logged_at TIMESTAMP NOT NULL,
    exercise_type TEXT NOT NULL,  -- 'zone2_cardio', 'strength', 'hiit', 'mobility', 'walk', etc.
    duration_minutes INTEGER,
    details TEXT,  -- JSON: {exercises, sets, reps, weight, distance, incline, speed, etc.}
    max_hr INTEGER,
    avg_hr INTEGER,
    calories_burned REAL,
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE supplement_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    logged_at TIMESTAMP NOT NULL,
    supplements TEXT NOT NULL,  -- JSON array of {name, dose}
    timing TEXT,  -- 'morning', 'with_meal', 'evening', 'pre_workout'
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE fasting_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    fast_start TIMESTAMP NOT NULL,
    fast_end TIMESTAMP,
    duration_minutes INTEGER,
    fast_type TEXT,  -- 'training_day', 'recovery_day', 'extended'
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE sleep_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    sleep_start TIMESTAMP,
    sleep_end TIMESTAMP,
    duration_minutes INTEGER,
    quality TEXT,  -- 'poor', 'fair', 'good', 'excellent'
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- AI-generated summaries (the key to overcoming context window limits)
CREATE TABLE summaries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    summary_type TEXT NOT NULL,  -- 'daily', 'weekly', 'monthly'
    period_start DATE NOT NULL,
    period_end DATE NOT NULL,
    -- Structured summary sections
    nutrition_summary TEXT,
    exercise_summary TEXT,
    vitals_summary TEXT,
    sleep_summary TEXT,
    fasting_summary TEXT,
    supplement_summary TEXT,
    mood_energy_summary TEXT,
    -- AI coaching notes
    wins TEXT,  -- what went well
    concerns TEXT,  -- what needs attention
    recommendations TEXT,  -- suggested adjustments
    -- Full narrative
    full_narrative TEXT,  -- complete summary for context injection
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Indexes for performance
CREATE INDEX idx_messages_user_date ON messages(user_id, created_at);
CREATE INDEX idx_food_log_user_date ON food_log(user_id, logged_at);
CREATE INDEX idx_vitals_log_user_date ON vitals_log(user_id, logged_at);
CREATE INDEX idx_exercise_log_user_date ON exercise_log(user_id, logged_at);
CREATE INDEX idx_summaries_user_type ON summaries(user_id, summary_type, period_start);
CREATE INDEX idx_fasting_log_user_date ON fasting_log(user_id, fast_start);
```

### Multi-Model Architecture (Cost Efficiency)

The system uses three model tiers to balance cost and quality:

```
┌─────────────────────────────────────────────────────┐
│                    USER INPUT                        │
│          (text, voice transcript, or image)          │
└──────────────────────┬──────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────┐
│              UTILITY MODEL (cheap/fast)              │
│                                                      │
│  Tasks:                                              │
│  • Classify intent (log_food, ask_advice, log_vitals,│
│    log_exercise, general_chat, image_analysis)       │
│  • Parse structured data from free-form text         │
│  • Extract macros/calories from food descriptions    │
│  • Generate daily/weekly/monthly summaries           │
│  • Parse image content (nutrition labels, BP, food)  │
│                                                      │
│  Default models:                                     │
│  • Anthropic: claude-haiku-4-5-20251001              │
│  • OpenAI: gpt-4o-mini                               │
│  • Google: gemini-2.0-flash                          │
└──────────────────────┬──────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────┐
│             REASONING MODEL (smart)                  │
│                                                      │
│  Tasks:                                              │
│  • Health coaching responses                         │
│  • Personalized advice with context                  │
│  • Interpreting vitals trends                        │
│  • Creating/adjusting plans                          │
│  • Specialist routing and responses                  │
│  • Complex nutritional analysis                      │
│  • Web search for current research                   │
│                                                      │
│  Default models:                                     │
│  • Anthropic: claude-sonnet-4-20250514               │
│  • OpenAI: gpt-4o                                    │
│  • Google: gemini-2.5-pro                            │
└─────────────────────────────────────────────────────┘
```

### Context Window Management Strategy

This is the core innovation. Every AI call gets a carefully assembled context:

```
┌─────────────────── CONTEXT ASSEMBLY ───────────────────┐
│                                                         │
│  1. SYSTEM PROMPT (The Longevity Alchemist persona)     │
│     ~2,000 tokens — always included                     │
│                                                         │
│  2. USER PROFILE (from user_settings)                   │
│     ~500 tokens — always included                       │
│     Age, weight, meds, conditions, goals, supplements   │
│                                                         │
│  3. ACTIVE SPECIALIST INSTRUCTIONS                      │
│     ~300 tokens — based on routing                      │
│                                                         │
│  4. CURRENT STATE SNAPSHOT                              │
│     ~500 tokens — computed fresh each request           │
│     Today's food log, hydration, vitals, fasting status │
│     Current weight, active fasting window, etc.         │
│                                                         │
│  5. RECENT SUMMARIES (rolling context)                  │
│     ~1,500 tokens — most recent daily + weekly summary  │
│     Provides continuity without full chat history       │
│                                                         │
│  6. RECENT MESSAGES (sliding window)                    │
│     ~3,000 tokens — last N messages from today          │
│     Provides immediate conversational context           │
│                                                         │
│  7. USER'S CURRENT MESSAGE                              │
│     Variable — the actual input                         │
│                                                         │
│  TOTAL BUDGET: ~8,000–10,000 tokens input               │
│  This leaves ample room for response generation         │
└─────────────────────────────────────────────────────────┘
```

### Specialist Routing System

```
Specialists and their trigger patterns:

NUTRITIONIST
  Triggers: food logging, meal planning, macro questions, diet advice, calorie tracking
  System addition: Emphasize DASH-aligned eating, protein-first meals, potassium-rich foods,
                   sodium awareness, fiber targets

SLEEP EXPERT
  Triggers: sleep questions, bedtime routines, fatigue, melatonin, sleep quality
  System addition: Emphasize circadian rhythm, sleep hygiene, magnesium timing,
                   caffeine cutoff, blue light, temperature

MOVEMENT COACH
  Triggers: exercise logging, workout planning, training questions, Zone 2, strength
  System addition: Emphasize progressive overload, Zone 2 benefits, recovery,
                   HR-based training zones, mobility work

SUPPLEMENT AUDITOR
  Triggers: supplement timing, new supplement questions, interaction checks, dosing
  System addition: Emphasize evidence-based supplements only, medication interactions,
                   timing optimization, always defer to physician

SAFETY CLINICIAN
  Triggers: concerning vitals, medication questions, symptoms, pain, medical advice
  System addition: Emphasize "not a doctor" disclaimer, recommend physician consultation,
                   flag dangerous patterns, never advise stopping medications

ORCHESTRATOR (default / auto-router)
  Triggers: general conversation, multi-topic messages, check-ins
  System addition: Full Longevity Alchemist persona, blends all specialties as needed
```

### Edge Cases to Handle

- **API key invalid or missing:** Graceful error with setup instructions
- **API rate limits:** Queue and retry with exponential backoff
- **Image too large:** Compress client-side before upload (max 4MB)
- **Voice recognition fails:** Fallback to text input, show "voice unavailable" message
- **SQLite concurrent writes:** Use WAL mode, serialize writes through FastAPI
- **User logs food with no macros known:** Use utility model to estimate, flag as estimated
- **Fasting window edge cases:** Handle midnight crossover, timezone changes
- **Summary generation fails:** Use last successful summary, flag for retry
- **Multiple fast-fire messages:** Queue and process sequentially per user
- **Offline usage:** PWA caches the shell; messages queue and sync when back online

---

## ATLAS Phase L — Link (Integration Validation)

### API Integration Specifications

**Anthropic Claude:**
```python
# Messages API with web search tool
POST https://api.anthropic.com/v1/messages
Headers: x-api-key, anthropic-version: 2023-06-01
Models: claude-sonnet-4-20250514 (reasoning), claude-haiku-4-5-20251001 (utility)
Vision: Supported via base64 image in messages
Search: tools=[{"type": "web_search_20250305", "name": "web_search"}]
```

**OpenAI:**
```python
# Chat completions API
POST https://api.openai.com/v1/chat/completions
Headers: Authorization: Bearer {key}
Models: gpt-4o (reasoning), gpt-4o-mini (utility)
Vision: Supported via image_url in messages
Search: Use web_search tool or function calling
```

**Google Gemini:**
```python
# Generative Language API
POST https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent
Auth: API key as query param
Models: gemini-2.5-pro (reasoning), gemini-2.0-flash (utility)
Vision: Supported via inline_data
Search: Use google_search grounding tool
```

### Connection Validation Checklist
```
[ ] SQLite database creates and migrates successfully
[ ] JWT auth flow works (register → login → token → authenticated request)
[ ] Each AI provider responds with a test message when key is configured
[ ] Image upload stores file and returns path
[ ] Web Speech API works on Chrome, Safari, Firefox
[ ] Docker container builds and runs
[ ] PWA manifest enables "Add to Home Screen" on mobile
```

---

## ATLAS Phase A — Assemble (Build Specification)

### Project Structure (Hybrid FastAPI + GOTCHA concepts)

```
longevity-alchemist/
├── docker-compose.yml
├── Dockerfile
├── .env.example
├── README.md
│
├── backend/
│   ├── main.py                      # FastAPI app entry point
│   ├── requirements.txt
│   ├── config.py                    # Settings, env vars
│   │
│   ├── auth/
│   │   ├── __init__.py
│   │   ├── routes.py                # /register, /login, /me
│   │   ├── models.py                # User SQLAlchemy models
│   │   └── utils.py                 # JWT, bcrypt helpers
│   │
│   ├── api/
│   │   ├── __init__.py
│   │   ├── chat.py                  # POST /chat — main conversation endpoint
│   │   ├── logs.py                  # GET/POST food, vitals, exercise, etc.
│   │   ├── summaries.py             # GET summaries, POST trigger generation
│   │   ├── settings.py              # GET/PUT user settings, API keys
│   │   ├── specialists.py           # GET/PUT specialist config
│   │   └── images.py                # POST image upload
│   │
│   ├── ai/                          # (GOTCHA: this is the Orchestration layer)
│   │   ├── __init__.py
│   │   ├── orchestrator.py          # Main AI orchestration — assembles context, routes
│   │   ├── providers/
│   │   │   ├── __init__.py
│   │   │   ├── base.py              # Abstract provider interface
│   │   │   ├── anthropic.py         # Claude integration
│   │   │   ├── openai_provider.py   # OpenAI integration
│   │   │   └── google.py            # Gemini integration
│   │   ├── context_builder.py       # Assembles context window from profile + logs + summaries
│   │   ├── specialist_router.py     # Classifies intent → picks specialist
│   │   ├── log_parser.py            # Utility model: extracts structured data from text
│   │   └── image_analyzer.py        # Utility model: processes uploaded images
│   │
│   ├── context/                     # (GOTCHA: Context layer — domain knowledge)
│   │   ├── system_prompt.md         # The Longevity Alchemist base persona
│   │   ├── specialists/
│   │   │   ├── nutritionist.md
│   │   │   ├── sleep_expert.md
│   │   │   ├── movement_coach.md
│   │   │   ├── supplement_auditor.md
│   │   │   ├── safety_clinician.md
│   │   │   └── orchestrator.md
│   │   └── reference/
│   │       ├── dash_diet.md
│   │       ├── zone2_training.md
│   │       ├── fasting_protocols.md
│   │       └── supplement_timing.md
│   │
│   ├── services/
│   │   ├── __init__.py
│   │   ├── food_service.py          # Food logging + macro estimation
│   │   ├── vitals_service.py        # Vitals tracking + trend analysis
│   │   ├── exercise_service.py      # Exercise logging + calorie estimation
│   │   ├── fasting_service.py       # Fasting window tracking
│   │   ├── hydration_service.py     # Hydration tracking
│   │   ├── summary_service.py       # Summary generation (daily/weekly/monthly)
│   │   └── reminder_service.py      # Medication/supplement reminders
│   │
│   ├── db/
│   │   ├── __init__.py
│   │   ├── database.py              # SQLAlchemy engine, session
│   │   ├── models.py                # All SQLAlchemy ORM models
│   │   └── migrations/              # Alembic migrations
│   │
│   └── utils/
│       ├── __init__.py
│       ├── encryption.py            # API key encryption/decryption
│       ├── datetime_utils.py        # Timezone handling, fasting calculations
│       └── image_utils.py           # Image compression, storage
│
├── frontend/
│   ├── index.html
│   ├── manifest.json                # PWA manifest
│   ├── sw.js                        # Service worker for offline/PWA
│   ├── package.json
│   ├── vite.config.ts
│   ├── tsconfig.json
│   ├── tailwind.config.js
│   │
│   ├── public/
│   │   ├── icons/                   # PWA icons (192x192, 512x512)
│   │   └── favicon.ico
│   │
│   └── src/
│       ├── main.tsx
│       ├── App.tsx
│       ├── api/
│       │   └── client.ts            # Fetch wrapper with JWT auth
│       │
│       ├── pages/
│       │   ├── Login.tsx
│       │   ├── Register.tsx
│       │   ├── Chat.tsx             # Main conversation view
│       │   ├── Dashboard.tsx        # Daily summary, vitals, weight chart
│       │   ├── Settings.tsx         # API keys, profile, preferences
│       │   ├── History.tsx          # Past logs and summaries
│       │   └── Specialists.tsx      # View/switch specialist modes
│       │
│       ├── components/
│       │   ├── ChatMessage.tsx      # Single message bubble
│       │   ├── ChatInput.tsx        # Text + voice + image input bar
│       │   ├── VoiceButton.tsx      # Web Speech API integration
│       │   ├── ImageUpload.tsx      # Camera/file upload button
│       │   ├── DailySummary.tsx     # Today's food, hydration, vitals card
│       │   ├── FastingTimer.tsx     # Live fasting duration display
│       │   ├── WeightChart.tsx      # Weight trend over time
│       │   ├── VitalsCard.tsx       # BP, HR display
│       │   ├── SpecialistBadge.tsx  # Shows which specialist is active
│       │   ├── Navbar.tsx
│       │   └── ProtectedRoute.tsx
│       │
│       ├── hooks/
│       │   ├── useAuth.ts
│       │   ├── useChat.ts
│       │   ├── useVoice.ts          # Web Speech API hook
│       │   └── useFastingTimer.ts
│       │
│       ├── stores/
│       │   └── authStore.ts         # Zustand or simple context
│       │
│       └── styles/
│           └── globals.css
│
└── data/                            # Docker volume mount point
    └── longevity.db                 # SQLite database file
```

### Build Order

**Phase 1 — Foundation (build first, everything depends on this):**
1. Database models + SQLAlchemy setup + Alembic migrations
2. Auth system (register, login, JWT middleware)
3. Basic FastAPI skeleton with CORS
4. Docker + docker-compose configuration
5. Frontend scaffold with Vite + React + Tailwind + routing
6. Login/Register pages → connect to backend

**Phase 2 — AI Core (the brain):**
1. AI provider abstraction layer (base interface)
2. Anthropic provider implementation
3. OpenAI provider implementation
4. Google Gemini provider implementation
5. Context builder (profile + logs + summaries → prompt)
6. Specialist router (utility model classifies intent)
7. Log parser (utility model extracts structured data)
8. Image analyzer (vision model processes photos)
9. Main orchestrator (ties it all together)

**Phase 3 — Conversation Interface:**
1. Chat page with message display
2. Chat input bar (text submission)
3. Voice input button (Web Speech API)
4. Image upload button
5. Streaming responses (SSE from FastAPI)
6. Auto-scroll, loading states, error handling

**Phase 4 — Health Logging Services:**
1. Food logging service + API endpoints
2. Vitals logging service + API endpoints
3. Exercise logging service + API endpoints
4. Fasting window tracking service
5. Hydration tracking service
6. Supplement logging service

**Phase 5 — Summaries & Dashboard:**
1. Daily summary generation (utility model, end of day or on demand)
2. Weekly summary generation (aggregates daily summaries)
3. Monthly summary generation (aggregates weekly summaries)
4. Dashboard page (today's stats, weight chart, vitals trend)
5. History page (browse past summaries and logs)

**Phase 6 — Polish & PWA:**
1. PWA manifest + service worker
2. Mobile-responsive layout testing
3. Fasting timer component (live countdown)
4. Specialist badge + manual override UI
5. Settings page (API keys, profile, model selection)
6. Onboarding flow (first-time user profile setup)

### Key Implementation Details

#### 1. The Chat Endpoint (most critical endpoint)

```python
# POST /api/chat
# This is the main conversation endpoint. Here's the flow:

async def chat(request: ChatRequest, user: User):
    # 1. If image attached, analyze with utility model first
    image_description = None
    if request.image:
        image_description = await image_analyzer.analyze(
            image=request.image,
            user=user,
            model="utility"  # cheap model for image parsing
        )

    # 2. Classify intent with utility model
    combined_input = request.message
    if image_description:
        combined_input += f"\n[Image analysis: {image_description}]"

    intent = await specialist_router.classify(
        message=combined_input,
        model="utility"
    )
    # Returns: {type: "log_food", specialist: "nutritionist", structured_data: {...}}

    # 3. If logging intent, parse structured data with utility model
    if intent.type.startswith("log_"):
        parsed = await log_parser.parse(
            message=combined_input,
            intent=intent,
            user_profile=user.settings,
            model="utility"
        )
        # Save to appropriate log table
        await save_structured_log(parsed, user)

    # 4. Build context window
    context = await context_builder.build(
        user=user,
        specialist=intent.specialist,
        include_today_logs=True,
        include_recent_summary=True,
        include_recent_messages=20  # last N messages
    )

    # 5. Generate coaching response with reasoning model
    response = await orchestrator.generate(
        context=context,
        user_message=combined_input,
        specialist=intent.specialist,
        model="reasoning",
        stream=True  # SSE streaming
    )

    # 6. Save message pair to database
    await save_messages(user, request.message, response)

    # 7. Return streamed response
    return StreamingResponse(response, media_type="text/event-stream")
```

#### 2. Context Builder (the key to memory)

```python
# context_builder.py — This is what makes the app "remember"

async def build(user, specialist, include_today_logs, include_recent_summary, include_recent_messages):
    sections = []

    # 1. Base system prompt (The Longevity Alchemist persona)
    sections.append(load_system_prompt())

    # 2. Specialist-specific instructions
    if specialist != "auto":
        sections.append(load_specialist_prompt(specialist))

    # 3. User profile (structured health data)
    profile = format_user_profile(user.settings)
    sections.append(f"## Current User Profile\n{profile}")

    # 4. Current medications & supplements (critical for safety)
    meds = format_medications(user.settings.medications)
    supps = format_supplements(user.settings.supplements)
    sections.append(f"## Medications\n{meds}\n## Supplements\n{supps}")

    # 5. Today's state snapshot (computed fresh)
    today = await compute_today_snapshot(user)
    # Includes: meals so far, calories/macros running total, hydration,
    #           vitals, active fasting window + duration, exercise done
    sections.append(f"## Today's Status ({today.date})\n{today.formatted}")

    # 6. Most recent summaries (the rolling memory)
    if include_recent_summary:
        daily = await get_latest_summary(user, "daily")  # yesterday's
        weekly = await get_latest_summary(user, "weekly")  # last week's
        if daily:
            sections.append(f"## Yesterday's Summary\n{daily.full_narrative}")
        if weekly:
            sections.append(f"## Last Week's Summary\n{weekly.full_narrative}")

    # 7. Recent messages (conversational continuity)
    if include_recent_messages:
        messages = await get_recent_messages(user, limit=include_recent_messages)
        formatted = format_message_history(messages)
        sections.append(f"## Recent Conversation\n{formatted}")

    return "\n\n".join(sections)
```

#### 3. Summary Generation (runs daily, weekly, monthly)

```python
# summary_service.py — Generates rolling summaries using utility model

async def generate_daily_summary(user, date):
    """Generate end-of-day summary from structured logs."""

    # Gather all logs for the day
    food = await get_food_logs(user, date)
    vitals = await get_vitals_logs(user, date)
    exercise = await get_exercise_logs(user, date)
    fasting = await get_fasting_logs(user, date)
    hydration = await get_hydration_logs(user, date)
    supplements = await get_supplement_logs(user, date)
    sleep = await get_sleep_logs(user, date)

    # Compile raw data
    raw = compile_daily_data(food, vitals, exercise, fasting, hydration, supplements, sleep)

    # Use UTILITY MODEL to generate structured summary (cheap)
    prompt = f"""Summarize this day's health data into a concise daily summary.
    Include: total calories/macros, protein goal status, hydration total,
    fasting duration, exercise done, vitals trends, sleep quality,
    what went well, what needs improvement, and any recommendations.
    Keep it under 400 words.

    User profile: {format_user_profile(user.settings)}
    Day's data: {raw}"""

    summary_text = await call_utility_model(user, prompt)

    # Store structured summary
    await save_summary(user, "daily", date, summary_text)

async def generate_weekly_summary(user, week_start):
    """Aggregate daily summaries into weekly overview."""
    daily_summaries = await get_summaries(user, "daily", week_start, week_start + 7days)
    # Use utility model to synthesize
    ...

async def generate_monthly_summary(user, month_start):
    """Aggregate weekly summaries into monthly overview."""
    weekly_summaries = await get_summaries(user, "weekly", month_start, month_end)
    # Use utility model to synthesize
    ...
```

#### 4. Image Analysis Pipeline

```python
# image_analyzer.py

async def analyze(image_bytes: bytes, user: User, analysis_hint: str = None):
    """
    Send image to vision-capable model for analysis.
    Works with: nutrition labels, food photos, BP monitors, supplement bottles.
    """
    prompt = """Analyze this image in the context of health/nutrition tracking.
    Identify what is shown and extract relevant data:
    - If nutrition label: extract calories, protein, carbs, fat, sodium, serving size
    - If food photo: identify foods, estimate portions and macros
    - If BP monitor: extract systolic, diastolic, heart rate
    - If supplement bottle: extract name, dose, ingredients
    Return structured JSON with your findings plus a natural language description."""

    if analysis_hint:
        prompt += f"\nUser context: {analysis_hint}"

    # Use the reasoning model for vision (utility models may lack vision)
    response = await call_model_with_vision(
        user=user,
        image=image_bytes,
        prompt=prompt,
        model="reasoning"  # vision typically needs the larger model
    )
    return response
```

#### 5. Specialist Router

```python
# specialist_router.py

ROUTING_PROMPT = """Classify this user message into ONE category and identify the best specialist.

Categories:
- log_food: User is reporting what they ate/drank
- log_vitals: User is reporting weight, BP, HR, blood glucose
- log_exercise: User is reporting a workout or activity
- log_supplement: User is reporting taking supplements/medications
- log_fasting: User is starting/ending a fast
- log_sleep: User is reporting sleep data
- ask_nutrition: Question about diet, food choices, meal planning
- ask_exercise: Question about workouts, training
- ask_sleep: Question about sleep improvement
- ask_supplement: Question about supplements, timing, interactions
- ask_medical: Question involving symptoms, medications, health concerns
- general_chat: Greetings, motivation, general health topics

Specialists: nutritionist, sleep_expert, movement_coach, supplement_auditor, safety_clinician, orchestrator

Return JSON: {"category": "...", "specialist": "...", "confidence": 0.0-1.0}
"""

async def classify(message: str, user_override: str = None):
    if user_override and user_override != "auto":
        return {"specialist": user_override, "category": "manual_override"}

    result = await call_utility_model(ROUTING_PROMPT + f"\nMessage: {message}")
    return parse_json(result)
```

#### 6. Provider Abstraction

```python
# providers/base.py

class AIProvider(ABC):
    @abstractmethod
    async def chat(self, messages: list, model: str, stream: bool = False, tools: list = None) -> str:
        """Send chat completion request."""
        pass

    @abstractmethod
    async def chat_with_vision(self, messages: list, image: bytes, model: str) -> str:
        """Send chat completion with image."""
        pass

    @abstractmethod
    def get_utility_model(self) -> str:
        """Return the configured utility (cheap) model name."""
        pass

    @abstractmethod
    def get_reasoning_model(self) -> str:
        """Return the configured reasoning (smart) model name."""
        pass

    @abstractmethod
    def supports_web_search(self) -> bool:
        """Whether this provider has native web search."""
        pass
```

#### 7. Frontend Voice Input Hook

```typescript
// hooks/useVoice.ts

export function useVoice() {
  const [isListening, setIsListening] = useState(false);
  const [transcript, setTranscript] = useState("");
  const [isSupported, setIsSupported] = useState(false);
  const recognitionRef = useRef<SpeechRecognition | null>(null);

  useEffect(() => {
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (SpeechRecognition) {
      setIsSupported(true);
      const recognition = new SpeechRecognition();
      recognition.continuous = false;
      recognition.interimResults = true;
      recognition.lang = "en-US";

      recognition.onresult = (event) => {
        const current = Array.from(event.results)
          .map(result => result[0].transcript)
          .join("");
        setTranscript(current);
      };

      recognition.onend = () => setIsListening(false);
      recognitionRef.current = recognition;
    }
  }, []);

  const startListening = () => {
    if (recognitionRef.current) {
      setTranscript("");
      recognitionRef.current.start();
      setIsListening(true);
    }
  };

  const stopListening = () => {
    if (recognitionRef.current) {
      recognitionRef.current.stop();
    }
  };

  return { isListening, transcript, isSupported, startListening, stopListening };
}
```

#### 8. PWA Configuration

```json
// manifest.json
{
  "name": "The Longevity Alchemist",
  "short_name": "Longevity",
  "description": "Your AI-powered health & longevity coach",
  "start_url": "/",
  "display": "standalone",
  "background_color": "#0f172a",
  "theme_color": "#10b981",
  "icons": [
    { "src": "/icons/icon-192.png", "sizes": "192x192", "type": "image/png" },
    { "src": "/icons/icon-512.png", "sizes": "512x512", "type": "image/png" }
  ]
}
```

#### 9. Docker Configuration

```dockerfile
# Dockerfile
FROM python:3.11-slim AS backend
WORKDIR /app
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/ .

FROM node:20-slim AS frontend-build
WORKDIR /app
COPY frontend/package*.json .
RUN npm ci
COPY frontend/ .
RUN npm run build

FROM python:3.11-slim
WORKDIR /app
COPY --from=backend /app /app
COPY --from=frontend-build /app/dist /app/static
RUN pip install --no-cache-dir -r requirements.txt
EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
```

```yaml
# docker-compose.yml
version: "3.8"
services:
  app:
    build: .
    ports:
      - "8000:8000"
    volumes:
      - ./data:/app/data          # SQLite + uploaded images persist here
    environment:
      - SECRET_KEY=${SECRET_KEY}
      - ENCRYPTION_KEY=${ENCRYPTION_KEY}
    restart: unless-stopped
```

### System Prompt (The Longevity Alchemist Persona)

Store this in `backend/context/system_prompt.md` and load it as the base system message for every AI call:

```markdown
You are **The Longevity Alchemist**, a witty, warm, and knowledgeable AI health coach created with love by a caring family. You help people optimize their healthspan (how long they live well) and lifespan (how long they live).

You blend the wisdom of top longevity experts — Dr. Rhonda Patrick, Peter Attia, Dr. Mindy Pelz, and others — into practical, daily guidance.

## Your Personality
- Warm and encouraging, like a supportive friend who happens to know a lot about health
- You explain complex science in simple, relatable terms (use analogies!)
- You celebrate wins, no matter how small
- You're honest but never judgmental about food choices or missed workouts
- You use light humor to keep things fun

## Your Capabilities
- **Food & Nutrition Tracking**: Log meals, estimate macros, suggest improvements
- **Vitals Monitoring**: Track weight, BP, HR — interpret trends, flag concerns
- **Exercise Coaching**: Plan workouts, log sessions, adjust based on recovery
- **Fasting Guidance**: Track fasting windows, advise on fasting protocols
- **Supplement Timing**: Optimize supplement and medication scheduling
- **Sleep Optimization**: Advise on sleep hygiene, track patterns
- **Hydration Tracking**: Monitor fluid intake throughout the day

## Critical Rules
1. **You are NOT a doctor.** Always remind users to consult their physician before changing medications, starting new supplements, or if they have concerning symptoms.
2. **Never advise stopping medications.** Frame medication reduction as a future goal achievable through lifestyle changes, always under physician supervision.
3. **Safety first.** Flag concerning vitals (BP > 140/90, resting HR > 100, etc.) and recommend medical attention.
4. **Be precise with logging.** When users report food, calculate macros carefully. When reporting vitals, record exact values.
5. **Reference their history.** Use the provided context (profile, today's logs, recent summaries) to give personalized, continuity-aware responses.
6. **Keep responses concise.** For simple logging, confirm quickly. For advice, be thorough but not verbose.
7. **Track everything.** If a user mentions consuming something, doing an activity, or measuring a vital — log it, even if they don't explicitly ask.

## Response Format for Logging
When a user logs food, vitals, exercise, or supplements, respond with:
1. Confirmation of what was logged
2. Calculated/estimated nutritional data (for food)
3. Running daily totals
4. A brief coaching insight (1-2 sentences)
5. Optional follow-up question
```

---

## ATLAS Phase S — Stress-Test Plan

### Functional Testing Checklist
```
[ ] User can register, login, and maintain session
[ ] User can set up API key and select provider
[ ] Text messages send and receive streamed responses
[ ] Voice input captures speech and submits as text
[ ] Image upload sends photo and gets analysis
[ ] Food logging extracts and stores macros
[ ] Vitals logging stores BP, weight, HR correctly
[ ] Exercise logging stores workout details
[ ] Fasting timer calculates duration correctly across midnight
[ ] Daily summaries generate from day's logs
[ ] Weekly summaries aggregate daily summaries
[ ] Monthly summaries aggregate weekly summaries
[ ] Context builder includes profile + logs + summaries
[ ] Specialist routing selects correct specialist
[ ] User can manually override specialist
[ ] Settings page saves API keys (encrypted), profile, preferences
[ ] Dashboard shows today's stats accurately
[ ] Running daily totals update after each food log
```

### Mobile Testing Checklist
```
[ ] Responsive layout works on iPhone Safari (375px width)
[ ] Responsive layout works on Android Chrome (360px width)
[ ] PWA installs via "Add to Home Screen"
[ ] Voice button works on iOS Safari
[ ] Voice button works on Android Chrome
[ ] Camera capture works for image upload on both platforms
[ ] Keyboard doesn't obscure chat input on mobile
[ ] Scrolling works smoothly in chat view
[ ] Touch targets are at least 44px for accessibility
```

### Context Window Testing
```
[ ] New user with no history gets proper onboarding
[ ] User with 1 week of history gets relevant daily+weekly summary in context
[ ] User with 1 month of history gets daily+weekly+monthly summaries
[ ] Context stays under 10,000 tokens even with full history
[ ] AI references yesterday's summary correctly in responses
[ ] AI knows current fasting state without being told explicitly
[ ] AI remembers medications and warns about interactions
```

### Edge Case Testing
```
[ ] Invalid API key shows clear error message
[ ] Network disconnection shows offline indicator
[ ] Very long message (1000+ words) handles gracefully
[ ] Rapid-fire messages (5+ in 10 seconds) queue properly
[ ] Image over 10MB gets compressed or rejected with message
[ ] Midnight fasting window crossover calculates correctly
[ ] Timezone change doesn't break fasting calculations
[ ] Empty day (no logs) generates appropriate "no data" summary
[ ] Concurrent users don't interfere with each other's data
```

---

## Summary of Key Design Decisions

| Decision | Choice | Why |
|----------|--------|-----|
| Multi-model tiering | Utility (cheap) for parsing/summaries, Reasoning (smart) for coaching | 60-70% cost reduction vs using reasoning model for everything |
| Context assembly | Profile + today's logs + recent summaries + recent messages | Overcomes context window limits while maintaining full awareness |
| Summary hierarchy | Daily → Weekly → Monthly (each built from prior level) | Compresses months of history into ~1,500 tokens |
| Specialist routing | Utility model classifies → auto-routes (user can override) | Consistent quality per domain without manual switching |
| Voice input | Browser Web Speech API (client-side) | Zero cost, works on all modern mobile browsers |
| Image analysis | Vision-capable model (reasoning tier) | Handles nutrition labels, food photos, BP monitors, supplement bottles |
| PWA approach | Web app with manifest + service worker | Single codebase for desktop + iOS + Android, installable |
| SQLite + Docker | File-based DB in mounted volume | Zero infrastructure, fully portable, easy backup |
| API key encryption | Fernet symmetric encryption at rest | Keys stored safely even if DB file is accessed |
| Streaming responses | Server-Sent Events (SSE) | Real-time typing effect, better UX than waiting for full response |

---

## Instructions to Claude Code

**Read this entire document before writing any code.** Build in the exact phase order specified (Phase 1 → 6). After completing each phase, run the relevant tests from the Stress-Test plan. Do not proceed to the next phase until the current phase passes its tests.

When building, prioritize:
1. **Working software over perfect code** — get it functional first
2. **Mobile-first design** — test on 375px viewport throughout
3. **Error handling everywhere** — every API call, every DB write, every user input
4. **Type safety** — use TypeScript strictly on frontend, Pydantic models on backend

For the AI integration, start with Anthropic (Claude) as the first provider, get it fully working, then add OpenAI and Gemini. This avoids spreading thin across three providers before one works well.

The Longevity Alchemist persona (Document 1 in the reference materials) should be the emotional core of every AI interaction. The technical architecture exists to serve that coaching experience.