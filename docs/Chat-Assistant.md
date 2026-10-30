# Chat Assistant

The chat (`POST /api/chat`, `frontend/src/pages/ChatPage.jsx`, `backend/app/agents/chat_agent.py`) is a travel advisor. It answers questions from the model's own knowledge, and it can plan a whole trip inside the conversation.

---

## Models

| Task | Model |
|---|---|
| Conversational answers and the planning narrative | `claude-sonnet-4-6` |
| Intent routing, trip-parameter extraction, plan commands | `claude-haiku-4-5-20251001` |
| The chat itinerary (`.agents/chat-itinerary.md`, `ChatItineraryAgent`) | `claude-haiku-4-5-20251001` |
| Specialist fallbacks and refinements | the specialist agents (Haiku, via `BaseAgent`) |

---

## Knowledge first, specialists last

Topic questions ("do I need a visa for Japan?", "which area of Barcelona is best for nightlife?") are answered **from the model's own knowledge** and stream straight away. No agents run, and no background verification happens.

The specialist agents (visa, sim, tips, getting_around, hotels, activities, flights) run only if the model **fails to answer**: the stream errors, the answer is empty, or the model says it doesn't know. Only then does the chat extract trip parameters and run the matching specialists as a fallback.

---

## Routing

Each message goes through an ordered router in `ChatAgent.stream()`:

| Step | Trigger | Behaviour |
|---|---|---|
| 0 | Jailbreak or off-topic patterns | Polite refusal; chat only discusses travel |
| 1 | Plan commands ("add … to my plan", "remove …", "show my plan", "clear my plan") | `plan_action` events that the frontend applies to My Plan |
| 1.5 | A reply to a pending clarifying question (for example the origin) | Resumes planning with that slot filled |
| 2 | Planning patterns ("plan a week in Lisbon…") | Comprehensive planning, or a clarifying question if something essential is missing |
| 3 | A specific topic (flights, hotels, visa, SIM, tips, transport, forex…) | Knowledge-only answer; specialists only on failure |
| 3.5 | A change to the trip being discussed ("make it cheaper", "add 2 days") | Refinement: re-runs only the affected specialists |
| 3.6 | Knowledge patterns (culture, packing, weather, neighbourhoods…) | Knowledge answer |
| 3.7 | Anything of 4 or more words not caught yet | One Haiku intent-classification call, which catches soft phrasings such as "we're thinking Lisbon in October, maybe with the kids?" |
| 4 | Everything else | Plan-aware conversation |

---

## Comprehensive planning

A planning request streams this sequence (`_run_comprehensive_planning`):

1. `planning_start` with the destination.
2. `trip_map`: city coordinates computed in Python, so the map appears at once.
3. `itinerary_generating`.
4. `comprehensive_itinerary`: the day-by-day plan from the chat-itinerary agent (60 s timeout, 120 s for multi-city).
5. Proactive warnings, checked in parallel while the itinerary builds: rainy or rough-weather days (weather agent) and major events or disruptions on the trip dates (events agent).
6. `session_context_update`, `suggestions` (tappable follow-up chips) and `planning_done`.

The frontend renders this as a `TripPlanView`: a Leaflet map, day cards, a budget tracker, suggestion and follow-up chips, and retry actions. Items can be added to the chat's My Plan drawer, which has the same features as on the Results page.

**Clarifying questions with slot memory.** If only the origin is missing, the chat asks exactly that ("Which city will you be flying from?"), remembers everything else and resumes when the user answers.

`section_result` events (with per-section `agent_status`) are used only in the specialist fallback and the refinement path (`_run_specialist_agents`), where individual specialists run with a 45 s timeout each.

---

## Refinement

"Make it cheaper" does not re-run everything. The chat compares the changed request with the previous one and re-runs only the specialists whose inputs changed (`_FIELD_AGENTS`):

| Changed field | Re-run |
|---|---|
| departure or return date | flights, hotels, activities |
| budget | flights, hotels |
| travellers | flights, hotels |
| interests | activities |
| origin | flights, visa |
| destination | flights, hotels, activities, visa, sim, tips, getting_around |

---

## Session context and history

The chat endpoint is stateless. The frontend sends the messages, current selections, any search results and a `session_context` (destination, dates, budget, travellers, a pending question) with each request, and the server returns `session_context_update` events. Follow-ups like "what about hotels there?" resolve against the trip being discussed, and naming a different city in the question always wins over the remembered trip.

Chat history is stored in the browser under `localStorage['chat_history_<username>']`, trimmed to the last 20 messages if storage is full. `utils/chatHistory.js` builds text stand-ins for structured turns before they are sent back to the model.

---

## Events

`delta` (text), `done`, `error`, `suggestions`, `session_context_update`, `plan_action`, `planning_start`, `trip_map`, `itinerary_generating`, `comprehensive_itinerary`, `planning_done`, `agent_status` and `section_result`. If the server hits an exception, it still closes the stream with a fallback `delta`, then `error` and `done`. The frontend parses the stream in `workers/chatWorker.js`.

---

## Personalization and safety

For signed-in users, the saved preferences and a short Taste Graph summary (see [Personalization](Personalization.md)) are added to the system prompt and to any specialist runs, so suggestions lean towards the user's demonstrated style.

The chat does not reveal its prompts, agent names or tooling, rejects jailbreak attempts and only discusses travel. It does not show verification badges.
