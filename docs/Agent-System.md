# Agent System

Travel Planner's AI capabilities are built on a lightweight agent framework. This page explains how the framework works, how agents are defined, what each specialist agent does, and how the system handles failures.

---

## BaseAgent

Every agent inherits from `BaseAgent` (`backend/app/agents/base_agent.py`). BaseAgent is responsible for:

1. **Loading the agent definition** — reads `.agents/{name}.md`, parses the YAML frontmatter, and stores the system prompt body
2. **Building the conversation** — constructs the `messages` array with the system prompt and a user message derived from the search context
3. **Calling the Anthropic API** — uses the `claude-agent-sdk` with configurable model, max_tokens, and max_turns from frontmatter
4. **Retrying on failure** — up to 4 attempts with exponential backoff before giving up
5. **Parsing the response** — applies a 3-strategy JSON extraction fallback
6. **Returning a typed result** — all agents return a Pydantic model, never raw dicts

BaseAgent exposes one method that subclasses implement:

```python
async def run(self, context: SearchContext) -> AgentResult:
    ...
```

---

## Agent definition format

Agent prompts live in `.agents/` at the project root. Each file is a markdown document with YAML frontmatter:

```markdown
---
name: flights
description: Finds typical flight routes, airlines, and price guidance for a destination
tools: []
max_turns: 3
---

You are a specialist travel flights analyst. Given a destination, travel dates,
origin country, and budget, provide structured information about...

[rest of system prompt]
```

**Frontmatter fields:**

| Field | Type | Description |
|---|---|---|
| `name` | string | Agent identifier, must match the filename |
| `description` | string | Human-readable description, used in logs |
| `tools` | list | Reserved for future tool-use; currently empty for most agents |
| `max_turns` | int | Maximum conversation turns passed to the SDK |

This design means prompt engineers can iterate on agent behaviour by editing markdown files without touching Python. Changes are picked up on next application start (or hot-reload in development).

---

## The 8 specialist agents

### FlightsAgent

Generates guidance on flight options between the user's origin country and destination. Output covers typical routes, airlines that serve the route, rough price ranges for the travel dates, and booking strategy advice (when to book, whether to use budget airlines, layover considerations). Does not make live API calls — relies on the model's training data and DuckDuckGo search for current context.

### HotelsAgent

Breaks down accommodation options by neighbourhood and type. Output covers areas of the city worth staying in (with reasoning), accommodation categories from budget hostels to boutique hotels, approximate price ranges per night, and booking tips. Neighbourhoods are contextualised to the user's stated interests — a user interested in nightlife gets different neighbourhood recommendations than one interested in museums.

### ActivitiesAgent

Generates a list of activities, experiences, and attractions for the destination. After the agent returns, the backend applies relevance scoring:

**Relevance scoring pipeline:**
1. The agent returns a list of activities, each with a name and description
2. `sentence-transformers` encodes the description of each activity and the user's interests string into embedding vectors
3. Cosine similarity is computed between each activity embedding and the interests embedding
4. Activities are sorted descending by similarity score
5. The sorted list is what gets streamed to the browser

This means a user who lists "street food and local markets" as interests will see food-focused activities ranked above standard tourist attractions, even if the model listed them in a different order.

### VisaAgent

Provides entry requirement information specific to the user's nationality. Output covers visa category (visa-free, visa on arrival, e-visa, embassy visa), application process, required documents, processing times, fees, and any notable conditions (e.g. onward ticket required, sufficient funds check). Nationality is passed as part of the search context.

### SimAgent

Covers mobile connectivity at the destination: which local carriers to consider, typical prepaid SIM data plans and pricing, whether eSIM is available, coverage quality notes, and where to buy (airport, convenience stores, carrier shops). Also notes whether the user's home country roaming is likely to be a better option for short trips.

### TipsAgent

Cultural and practical travel tips: local customs and etiquette, safety considerations, health precautions, tipping culture, bargaining norms, dress codes for religious sites, local laws tourists sometimes inadvertently break, and any destination-specific practical advice that does not fit neatly into the other agent categories.

### GettingAroundAgent

Transport options within the destination city and country: airport transfer options with price ranges, public transport coverage and how to use it, ride-hailing app availability, taxi culture (metered vs negotiated, reliability), car rental considerations, and intercity transport for multi-city itineraries.

### ForexAgent

Currency and money guidance: local currency and ISO code, current rough exchange rate context, whether to exchange before travel or at destination, ATM availability and typical fees, credit card acceptance, digital payment adoption, and any currency controls or cash-preference considerations.

---

## Retry and JSON parsing logic

**Retry:** Each agent wraps its Anthropic API call in a retry loop with up to 4 attempts. On `APIStatusError` (rate limits, server errors) or network timeouts, the agent waits with exponential backoff before retrying. On the 4th failure, it returns a structured error result rather than raising an exception — the orchestrator can still stream partial results to the browser.

**JSON parsing (3-strategy fallback):**

The Anthropic API is instructed to return structured JSON, but model outputs are not always perfectly formed. BaseAgent applies three strategies in order:

1. **Direct parse** — attempt `json.loads()` on the full response text
2. **Code block extraction** — look for ` ```json ... ``` ` fences and parse the content inside
3. **Regex extraction** — find the first `{...}` block in the response using a regex and attempt to parse it

If all three fail, the agent returns a fallback result with an error flag set, which the frontend renders as a "not available" section rather than a crash.

---

## ItineraryAgent

The ItineraryAgent runs after Phase 1 completes. It receives:
- The activities list (after relevance scoring and sorting)
- The hotels result (neighbourhood and accommodation data)
- The original search context (destination, dates, budget, interests)

It synthesises a day-by-day itinerary that logically groups activities, ties mornings/afternoons/evenings to sensible locations, and references specific accommodation areas. The output is a structured JSON object with one entry per day.

**60-second timeout:** If the model takes longer than 60 seconds, the orchestrator falls back to a template-based itinerary generator that distributes activities across the days mechanically. The fallback is clearly marked as auto-generated in the response.

---

## ChatAgent

The ChatAgent powers the follow-up chat interface. It differs from the specialist agents in that it is conversational — it maintains message history across turns within a session.

When a user sends a message in the chat interface, the ChatAgent first runs intent detection to decide whether the message is travel-planning related. If it is, the agent responds with travel expertise in the context of the current trip plan. If the message is clearly off-topic (e.g. "write me a Python script"), the agent politely redirects to travel topics. This keeps the chat focused without being overly restrictive.

Chat responses are also streamed via SSE, handled by the dedicated `chatWorker.js` Web Worker on the frontend.
