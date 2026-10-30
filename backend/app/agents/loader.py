import re
from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass
class AgentDefinition:
    name: str
    description: str
    system_prompt: str = ""


def _resolve_agents_dir(agents_dir: str) -> Path:
    """Resolve agents_dir to an absolute Path.

    Resolution order:
    1. If already absolute, use as-is.
    2. If relative and exists from CWD, use that.
    3. Fallback: look relative to project root (4 levels up from this file:
       loader.py -> agents/ -> app/ -> backend/ -> travel-planner/).
    """
    p = Path(agents_dir)
    if p.is_absolute():
        return p
    if p.exists():
        return p.resolve()
    # Fallback: project root is 4 levels up from this file
    project_root = Path(__file__).parent.parent.parent.parent
    return project_root / ".agents"


def load_agent_definition(agents_dir: str, agent_name: str) -> AgentDefinition:
    """Load agent definition from .agents/<name>.md"""
    resolved_dir = _resolve_agents_dir(agents_dir)
    path = resolved_dir / f"{agent_name}.md"
    if not path.exists():
        raise FileNotFoundError(f"Agent definition not found: {path}")

    content = path.read_text()

    # Parse YAML frontmatter (between --- markers)
    match = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)$", content, re.DOTALL)
    if not match:
        raise ValueError(f"Invalid agent definition format in {path}")

    frontmatter = yaml.safe_load(match.group(1))
    system_prompt = match.group(2).strip()

    return AgentDefinition(
        name=frontmatter.get("name", agent_name),
        description=frontmatter.get("description", ""),
        system_prompt=system_prompt,
    )
