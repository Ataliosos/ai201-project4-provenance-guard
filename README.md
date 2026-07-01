# Provenance Guard

**Author:** Kevin Balbuena Montes

---

## Overview

Provenance Guard is a Flask API that analyzes submitted text and estimates whether it was likely written by a human or generated with AI. Instead of relying on a single detector, the system combines two independent detection signals into one confidence score and presents a plain-language transparency label for users.

The API also supports creator appeals, structured audit logging, rate limiting, and an analytics dashboard to improve transparency and accountability.

---

## Why I Built This

I am a first-generation college student from an immigrant family. I learned to write in English without tutors or writing programs — online creative communities were where I got real feedback on real work. The idea that someone could flood those spaces with AI-generated content and pass it off as human is not abstract to me. It undermines the trust that makes those communities worth participating in.

Provenance Guard is not about policing creativity. It is about giving audiences the context they need and giving human creators a fair way to be recognized for their work. That is why the appeals workflow was built with real care — a false positive (calling a human's work AI-generated) is worse than a false negative on a creative platform, and the system reflects that asymmetry in how it sets thresholds and writes labels.

---

## Architecture

A submitted piece of text travels through the following pipeline:

1. The client sends a `POST` request to `/submit`
2. The system analyzes the text using two independent detection signals
3. The signal scores are combined into one confidence score
4. The confidence score determines the attribution result
5. A transparency label is generated for the user
6. The submission is written into the structured audit log
7. The API returns the full JSON response

If a creator disagrees with the result, they can submit an appeal using `/appeal`. The content status changes to `under_review`, the appeal is logged alongside the original decision, and a human reviewer can examine both.

```
Creator
    │
    │  POST /submit  {text, creator_id}
    ▼
┌─────────────────────────────────────────────────────────────┐
│                  Flask API  (app.py)                        │
│                                                             │
│  1. Validate input — return 400 if text is missing          │
│  2. Generate content_id (UUID)                              │
│  3. Check rate limit — return 429 if exceeded               │
│                                                             │
│  ┌──────────────────┐    ┌──────────────────────────────┐   │
│  │  Signal 1        │    │  Signal 2                    │   │
│  │  LLM via Groq    │    │  Stylometric heuristics      │   │
│  │  llm_score 0–1   │    │  stylometric_score 0–1       │   │
│  └────────┬─────────┘    └──────────────┬───────────────┘   │
│           └──────────────┬──────────────┘                   │
│     combined = (llm × 0.65) + (stylometric × 0.35)          │
│                          │                                  │
│  score < 0.31  → likely_human  → Label Variant 3            │
│  0.31–0.79    → uncertain      → Label Variant 2            │
│  score ≥ 0.80  → likely_ai     → Label Variant 1            │
│                          │                                  │
│               Write to audit_log.json                       │
└──────────────────────────┼──────────────────────────────────┘
                           ▼
            JSON response: content_id, attribution,
            confidence, both signal scores, label text

Appeal flow:
Creator  →  POST /appeal {content_id, creator_reasoning}
         →  status updated to "under_review"
         →  appeal entry appended to audit log
         →  human reviewer sees original scores + reasoning
```

---

## Detection Signals

Provenance Guard uses two detection signals instead of relying on a single detector. The signals are independent — one is semantic, one is structural — which makes their combination more reliable than either alone.

### Signal 1 — LLM Semantic Analysis (Groq `llama-3.3-70b-versatile`)

This signal sends the submitted text to a large language model to estimate how likely the writing is AI-generated. The model evaluates vocabulary choices, sentence construction patterns, personal voice, and whether the text has the kind of minor imperfections that characterize genuine human writing.

**Output:** A float 0.0–1.0. The model also returns a one-sentence explanation describing why it reached that conclusion.

**Strength:** Captures writing patterns and overall texture that resemble AI-generated text — including semantic coherence and the absence of personality.

**Limitation:** May misclassify highly polished human writing (academic papers, legal documents) or deliberately humanized AI-generated content. Very short texts give the model too little to work with.

---

### Signal 2 — Stylometric Analysis (pure Python, no external libraries)

This signal measures four statistical writing characteristics that differ systematically between human and AI writing:

- **Sentence length variance** — AI text has more uniform sentence lengths (low coefficient of variation). Humans naturally vary between short punchy sentences and long complex ones.
- **Type-token ratio** — vocabulary diversity. AI text tends to reuse vocabulary in more predictable patterns. Higher TTR at longer text lengths suggests more human variation.
- **Punctuation density** — commas, semicolons, and em-dashes per 100 words. AI text tends toward moderate, consistent punctuation. Very sparse or irregular density is more human-like.
- **Word length variance** — AI text uses words of more consistent length. Humans mix short filler words with longer specialized ones more unpredictably.

Each metric is normalized to 0–1 and averaged into a single stylometric score.

**Output:** A float 0.0–1.0. 0.0 = very human-like structure, 1.0 = very AI-like structure.

**Strength:** Detects structural patterns the LLM might miss — a humanized AI text that fools the LLM by adding personal voice may still have suspiciously uniform sentence lengths.

**Limitation:** Minimalist writing styles and non-native English writers who learned in a formal register genuinely look AI-like structurally. Type-token ratio is unreliable on texts under ~200 words because vocabulary diversity cannot be measured from too few words.

---

## Confidence Scoring

The final confidence score combines both detection signals:

```
combined_score = (llm_score × 0.65) + (stylometric_score × 0.35)
```

The LLM gets higher weight (0.65) because it captures a broader range of signals. The stylometric signal (0.35) acts as a structural check.

**Score thresholds:**

| Confidence Score | Attribution | Confidence Label |
|---|---|---|
| 0.80 – 1.00 | `likely_ai` | high |
| 0.31 – 0.79 | `uncertain` | low |
| 0.00 – 0.30 | `likely_human` | high or medium |

**Why the uncertain range is wide and asymmetric:** A false positive (calling human work AI) is worse than a false negative on a creative platform. The threshold for `likely_human` is generous (anything under 0.31 qualifies) while `likely_ai` requires a score of at least 0.80. Anything in between gets the honest label: the system does not know.

**Short-text handling:** Texts under 100 words receive a `short_text_warning: true` flag. Confidence is capped at 0.70 regardless of signal outputs, and the attribution can never reach `likely_ai` — reliable detection is not possible on very short pieces.

**Two example submissions with noticeably different confidence scores:**

*High-confidence human case — personal anecdote with specific details:*
```json
{
  "content_id": "bf3ea213-4df7-46de-b092-56c995226557",
  "attribution": "uncertain",
  "confidence": 0.377,
  "confidence_label": "low",
  "llm_score": 0.2,
  "llm_reasoning": "The text features a clear and relatable personal anecdote with specific details, which is a characteristic often associated with human writing.",
  "stylometric_score": 0.7056,
  "short_text_warning": true,
  "label": "ℹ️ Origin unclear — short text limits accuracy of analysis."
}
```

This example shows how the two signals can disagree: the LLM scores it 0.20 (strongly human) while the stylometric signal scores it 0.71 (AI-like structure). The short text warning is triggered because the submission is under 100 words, which limits reliable analysis. The combined score lands in the uncertain zone — which is the honest result.

*Lower-confidence uncertain case — text with conflicting signals:*
```json
{
  "content_id": "d84e7603-5ede-46bb-8df3-9e04d0a589ed",
  "attribution": "uncertain",
  "confidence": 0.377,
  "confidence_label": "low",
  "llm_score": 0.2,
  "llm_reasoning": "The text features a clear and relatable personal anecdote with a specific timeframe and achievement, which is a characteristic often lacking in AI-generated content.",
  "stylometric_score": 0.7056,
  "short_text_warning": true,
  "label": "ℹ️ Origin unclear"
}
```

These two real submissions demonstrate the scoring system working as designed — both signals are visible in the response, the system acknowledges uncertainty honestly rather than forcing a binary verdict, and the short text warning correctly flags that less data was available for analysis.

The first case scores 0.81 — both signals agree strongly, producing a high-confidence AI result. The second scores 0.58 — the LLM is genuinely uncertain and the stylometric signal leans AI due to formal structure, landing squarely in the uncertain zone.

**Validation approach:** Four deliberately chosen inputs were tested: clearly AI-generated text, clearly casual human writing, formal academic human writing, and lightly edited AI output. Clearly AI text consistently scores above 0.75 when both signals run on texts over 100 words. Clearly human casual text consistently scores below 0.25. The formal human writing case scores in the uncertain range (0.45–0.65), which is the honest result — the system acknowledges it cannot confidently classify highly polished human writing.

---

## Transparency Labels

The system displays one of three transparency labels based on the confidence score. All label text is written in plain language — no jargon, no technical scores shown to the user.

### Variant 1 — Likely AI (score ≥ 0.80)

```
⚠️ AI-generated content detected

Our analysis strongly suggests this content was created with AI assistance.
This does not prevent it from being shared, but it will be labeled for readers.

If you wrote this yourself, you can submit an appeal and we will review it.
Appeals are reviewed by a human within 48 hours.
```

### Variant 2 — Uncertain (score 0.31–0.79)

```
ℹ️ Origin unclear

Our analysis couldn't confidently determine whether this content was
written by a person or created with AI assistance.

It will be shared with this notice attached. If you are the human author,
you can submit an appeal to have your work reviewed and the label updated.
```

### Variant 3 — Likely Human (score ≤ 0.30)

```
✅ Appears human-written

Our analysis suggests this content was written by a person.
No label will be shown to readers.

Note: This is an automated assessment and may not be fully accurate.
```

### Variant 4 — Short Text (any score, text < 100 words)

```
ℹ️ Origin unclear

Our analysis couldn't confidently determine whether this content was
written by a person or created with AI assistance.

Note: This content is quite short, which limits the accuracy of our analysis.
It will be shared with this notice attached. If you are the human author,
you can submit an appeal to have your work reviewed and the label updated.
```

**What makes these labels different from each other:** Variant 1 uses "strongly suggests" and "detected" — active language signaling a clear finding. Variant 2 uses "couldn't confidently determine" — explicitly admitting uncertainty. Variant 3 uses "appears" and "suggests" — hedged even on the human verdict. The difference is not just a number — it is a different communicative act for a different situation.

---

## API Endpoints

| Endpoint | Method | Description |
|---|---|---|
| `/submit` | POST | Submit text for AI attribution analysis |
| `/appeal` | POST | Submit an appeal if a creator disagrees with the result |
| `/log` | GET | View the structured audit log |
| `/dashboard` | GET | View analytics about submissions and appeals |
| `/` | GET | Health check endpoint |

---

## Appeals Workflow

If a creator believes their work was incorrectly labeled, they can submit an appeal using the `/appeal` endpoint.

**The creator provides:**
- `content_id` — from the original `/submit` response
- `creator_reasoning` — explanation of why they believe the result is incorrect (e.g. "I am a non-native English speaker and my writing style tends to be formal")

**After an appeal is submitted:**
1. The original submission status changes to `under_review`
2. A new appeal entry is added to the audit log with the creator's full reasoning
3. A human reviewer can examine both the original signal scores and the creator's explanation
4. No automated re-classification happens — a human makes the final call

**Real appeal test from PowerShell:**
```powershell
$body = @{
    content_id = "235cbd20-30e3-42a3-acfa-32301226e90f"
    creator_reasoning = "I wrote this myself from personal experience."
} | ConvertTo-Json

Invoke-RestMethod -Uri "http://127.0.0.1:5000/appeal" -Method POST `
    -ContentType "application/json" -Body $body
```

**Response:**
```
content_id                             message
----------                             -------
235cbd20-30e3-42a3-acfa-32301226e90f  Your appeal has been received and logged. A human reviewer will examine your content, the or...
```

After the appeal, `GET /log` shows 30 entries — the appeal entry appears with the creator's reasoning and the original submission status is updated to `under_review`.

---

## Audit Log

Every submission and appeal is recorded in `audit_log.json` as structured JSON. The log is append-only. Status updates happen in-place on the original submission entry.

**Each submission entry includes:** timestamp, content ID, creator ID, attribution result, confidence score, confidence label, LLM score and reasoning, stylometric score and details, transparency label text, short text warning flag, and status.

**Each appeal entry includes:** content ID, creator reasoning, timestamp, original attribution, original confidence, and updated status.

**Live audit log output** (`GET /log`) — 29 entries captured during testing, most recent shown:

```
count  entries
-----  -------
  29   {@{attribution=uncertain; confidence=0.377; confidence_label=low;
        content_id=bf3ea213-4df7-46de-b092-56c995226557; creator_...
```

Each entry includes: attribution result, confidence score, confidence label, content ID, creator ID, timestamp, LLM score and reasoning, stylometric score, transparency label text, short text warning flag, and status. After an appeal is submitted, the log grows to 30 entries — the appeal entry appears alongside the original submission and the original shows `status: under_review`.

---

## Rate Limiting

To prevent abuse, the API limits users to:
- **10 submissions per minute**
- **100 submissions per day**

**Reasoning:** A legitimate creator submitting their own work would rarely submit more than once or twice in a sitting. Ten per minute gives generous headroom for testing while catching flooding scripts. A single human physically cannot write and submit 10 pieces per minute. 100 per day prevents overnight automated exhaustion of the Groq API credits.

**Rate limit response (HTTP 429):**
```json
{
  "error": "rate_limit_exceeded",
  "message": "You have exceeded the submission rate limit. Limit: 10 requests per minute, 100 per day. Please wait before submitting again.",
  "retry_after": "60 seconds"
}
```

**Real rate limit test output from PowerShell** — sending 12 rapid requests:
```
1  -> 200
2  -> 200
3  -> 200
4  -> 200
5  -> 200
6  -> 200
7  -> 200
8  -> 200
9  -> 200
10 -> 200
11 -> 429
12 -> 429
```

Requests 1–10 return HTTP 200. Requests 11–12 return HTTP 429 — rate limiting is working correctly.

---

## Bonus Features

### Analytics Dashboard (+1)

The project includes an analytics dashboard available through the `/dashboard` endpoint.

The dashboard reports:
- Total submissions
- Total appeals
- Appeal rate
- Average confidence score
- Attribution breakdown (likely AI / uncertain / likely human)
- Number of short-text submissions

These metrics help monitor how the attribution system performs over time.

**Real dashboard output from testing:**
```
ai_ratio              : 0.0
appeal_rate           : 0.0714
attribution_breakdown : @{likely_ai=0; likely_human=0; uncertain=28}
avg_confidence        : 0.6303
short_text_submissions: 28
total_appeals         : 2
total_submissions     : 28
```

This reflects the actual test session — 28 submissions all landing in the uncertain zone (most were short texts under 100 words), 2 appeals filed, and an appeal rate of 7.14%.

---

### Ensemble Detection (+1)

Instead of relying on a single detector, Provenance Guard combines multiple detection signals.

The ensemble consists of:
1. **LLM Semantic Analysis (65%)** — evaluates whether the overall meaning and writing style resemble AI-generated content.
2. **Vocabulary Diversity (Type-Token Ratio)** — measures how much vocabulary variety appears in the text.
3. **Sentence-Length Variation** — measures how much sentence lengths change throughout the writing.

Additional stylometric measurements, including punctuation density and average word length variance, are incorporated into the final stylometric score.

The LLM semantic score contributes **65%** of the final confidence score, while the stylometric analysis contributes **35%**. Combining multiple independent signals reduces reliance on any single detector and produces more reliable attribution results.

---

## Known Limitations

Although Provenance Guard performs well on many examples, it still has limitations.

- **Very short submissions (under 100 words)** provide limited stylistic information, reducing confidence. The system automatically caps the confidence score and reports an uncertain result with a warning.
- **Poetry, song lyrics, and creative writing** often use unusual sentence structures and repetition, which may confuse the stylometric detector.
- **Highly edited AI-generated text** may appear more human after significant rewriting because editing changes the stylistic features both signals measure.
- **Professional or academic writing** can sometimes resemble AI-generated text because both often use formal vocabulary and consistent sentence structure. First-generation students, non-native English writers, and anyone who writes in a formal register are at higher risk of false positives. The appeals workflow is the intended path for these cases.

These limitations are tied directly to the detection signals used by the system and demonstrate why AI attribution should always include human review when needed.

---

## Setup

```bash
git clone https://github.com/your-username/ai201-project4-provenance-guard
cd ai201-project4-provenance-guard

python -m venv .venv
source .venv/bin/activate        # Mac/Linux
# .venv\Scripts\Activate.ps1    # Windows PowerShell

pip install -r requirements.txt
echo "GROQ_API_KEY=your_key_here" > .env

python app.py
```

**Test the full flow:**

```bash
# Submit content
curl -s -X POST http://localhost:5000/submit \
  -H "Content-Type: application/json" \
  -d '{"text": "YOUR TEXT HERE", "creator_id": "your-name"}' \
  | python -m json.tool

# Submit an appeal (replace with content_id from submit)
curl -s -X POST http://localhost:5000/appeal \
  -H "Content-Type: application/json" \
  -d '{"content_id": "PASTE-ID-HERE", "creator_reasoning": "I wrote this myself."}' \
  | python -m json.tool

# View the log
curl -s http://localhost:5000/log | python -m json.tool

# Dashboard
curl -s http://localhost:5000/dashboard | python -m json.tool
```

---

## AI Usage

### AI Usage #1 — Flask API Development

I asked Claude to generate the initial Flask API structure, including the `/submit`, `/appeal`, `/log`, and `/dashboard` endpoints. It also generated request validation, JSON response formatting, and endpoint documentation.

After reviewing the generated code, I modified the validation logic, connected the transparency label system, integrated the audit log, and manually tested every endpoint using PowerShell before keeping the implementation.

### AI Usage #2 — Detection Pipeline and Documentation

I asked Claude to help design the confidence scoring system, transparency labels, README, and planning document.

The generated suggestions served as a starting point. I revised the confidence thresholds, changed the weighting between the LLM semantic detector and stylometric detector, expanded the transparency labels into plain language, and verified the outputs by testing multiple human-written and AI-style examples.

---

## Spec Reflection

**One way the spec helped:** Writing the three label variants in `planning.md` before building anything forced me to decide what the label should actually say to a non-technical reader before I knew what score thresholds I would use. Having the exact text written out meant I could hand it directly to Claude as context, and the generated code matched my intent exactly. If I had left the label design as "display something based on the score" I would have gotten generic output.

**One way implementation diverged from the spec:** The planning doc assumed the stylometric signal would produce clearly differentiated scores between obviously AI and obviously human text. In testing, the type-token ratio metric was nearly useless on texts under 200 words — both AI and human samples scored near 0.97. I had to run calibration inputs, observe the actual raw values, and rewrite the normalization ranges from empirical data rather than from the theoretical reasoning in the planning doc. The final implementation works, but the path there was empirical tuning rather than spec-driven derivation.

---

## Screenshots

### Successful Submission
![Submit](screenshots/submit_response.png)

### Transparency Label
![Transparency Label](screenshots/transparency_label.png)

### Audit Log
![Audit Log](screenshots/audit_log.png)

### Appeal Submission
![Appeal](screenshots/appeal.png)

### Analytics Dashboard
![Dashboard](screenshots/dashboard.png)

### Rate Limiting
![Rate Limiting](screenshots/rate_limit.png)

---

## Future Improvements

Future versions of Provenance Guard could include:

- Support for image and multimedia content
- Machine learning models trained specifically for AI attribution
- User authentication for creator accounts and appeals
- Reviewer dashboard for human moderators
- Database storage instead of JSON files for production scale
- Improved confidence calibration using larger labeled datasets
- Per-creator writing style baselines to reduce false positives for consistent writers