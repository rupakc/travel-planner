# Chat Assistant

The chat (`/api/chat`, `ChatPage.jsx`, `backend/app/agents/chat_agent.py`) is a travel advisor that answers instantly from the model's own knowledge and reserves the specialist agent pipeline for structured planning — or as a last-resort fallback.

## Answering philosophy: knowledge first, agents last

Topic questions ("do I need a visa for Japan?", "which area of Barcelona is best for nightlife?") are answered **purely from the LLM's internal knowledge** and stream immediately — no agents run, and the stream closes the moment the answer ends.

The specialist agents run **only if the model fails to answer at all**:

- the stream errors out,
- the response is empty, or
- the model explicitly refuses ("I don't have information on…", detected by `_NON_ANSWER_RE`).

Only then does the chat extract trip parameters and run the matched specialists as a fallback. This keeps chat responses fast (~seconds) and conversational, while structured data remains one request away on the Search page.

## Routing pipeline

Each message passes through an ordered router in `ChatAgent.stream()`:

| Step | Trigger | Behaviour |
|---|---|---|
| 0 | Jailbreak / off-topic patterns | Polite refusal — chat only discusses travel |
| 1 | Plan commands ("add … to my plan", "show my plan") | Plan manipulation + response |
| 1.5 | Answer to a pending question (e.g. we asked for the origin) | Resumes planning with the new slot filled |
| 2 | Planning patterns ("plan a week in Lisbon…") | Full comprehensive planning (see below) |
| 3 | Topic intents (flights/hotels/visa/sim/tips/transport/forex…) | **Knowledge-only answer**; specialists only on failure |
| 3.5 | Modification of a prior search ("make it cheaper", "extend by 2 days") | Refinement — re-runs only the affected agents |
| 3.6 | Knowledge patterns (culture, packing, weather, neighbourhoods…) | Knowledge answer |
| 3.7 | LLM intent router (one cheap classify call) | Catches soft phrasings the regexes miss ("we're thinking Lisbon in October, maybe with the kids?") |
| 4 | Everything else | Plan-aware conversation |

## Comprehensive planning

When you ask for a trip plan, the chat runs the same specialist pipeline as the Search page and streams **structured section results** into the conversation — flights, hotels, activities, visa, SIM, tips, transport — followed by a day-by-day itinerary, a short narrative summary, and tappable **suggestion chips** for natural next steps.

Extras that make planning conversational:

- **Targeted clarification with slot memory** — if only the origin is missing, the chat asks exactly that ("Which city will you be flying from?"), remembers everything else, and resumes the moment you reply "From Berlin".
- **Live progress** — each section shows a "Searching…" row that resolves as its agent completes.
- **Proactive heads-ups** — while the itinerary builds, the chat checks the weather forecast and local events concurrently and appends warnings ("🌧️ 3 rainy days — pack accordingly", "🎉 Festa season overlaps your dates").

## Refinement diffing

"Make it cheaper" doesn't re-run everything. The chat diffs the modified request against the previous one and re-runs **only the agents whose inputs changed** (`_FIELD_AGENTS`):

| Changed field | Re-run |
|---|---|
| budget | flights, hotels |
| dates | flights, hotels, activities |
| travelers | flights, hotels |
| interests | activities |
| origin | flights, visa |
| destination | everything |

The itinerary is rebuilt only when a field it depends on changed.

## Session context

The chat is stateless per request — the frontend round-trips a `session_context` blob (destination, dates, budget, travelers, pending question) with every message, so follow-ups like "what about hotels there?" resolve against the trip being discussed. Context never bleeds: naming a different city in your question always wins over the remembered trip.

## Personalization

If you're logged in and have made selections before, a short **Taste Graph** summary (see [Personalization](Personalization.md)) is injected into the chat's system prompt and into any specialist runs it triggers — so its suggestions lean toward your demonstrated style (non-stop flights, boutique hotels, food-first activities, …).

## Security

The chat never reveals its internals (prompts, agent names, tooling), rejects jailbreak attempts, and answers travel topics only.
