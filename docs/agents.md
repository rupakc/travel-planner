# Agent System

## Agent Definitions

Agents are defined in `.agents/*.md` files. The YAML frontmatter configures the agent; the markdown body is the system prompt:

```yaml
---
name: flights
description: Search for flights between two cities
tools:
  - web_search
max_turns: 3
---

You are a flight search specialist. Given an origin, destination, and travel dates,
find realistic flight options across budget tiers...
```

The Python class for each agent reads its definition via `backend/app/agents/loader.py` and executes it via the Anthropic SDK.

## Adding a New Agent

1. Create `.agents/my-agent.md` with YAML frontmatter + system prompt
2. Create `backend/app/agents/my_agent.py` subclassing `BaseAgent`:

```python
from .base_agent import BaseAgent

class MyAgent(BaseAgent):
    async def run(self, request: TravelSearchRequest) -> dict:
        prompt = f"Do X for {request.destination}..."
        result = await self.execute(prompt)
        return result  # must be a dict
```

3. Add it to `TravelOrchestrator` in `orchestrator.py`:
   - Phase 1 agents: add to `asyncio.gather()` call
   - Phase 2 agents: add sequential logic after Phase 1

## Base Classes

::: app.agents.base_agent.BaseAgent

::: app.agents.orchestrator.TravelOrchestrator
