"""neo-research-briefs: OpenClaw orchestration for research briefs.

The package turns research briefs (captured in Notion or an Obsidian vault)
into an implementation pipeline that spans Discord (collaboration) and
GitHub (durable artifacts).

Modules
-------
- :mod:`neo_research_briefs.config`  - typed configuration loader
- :mod:`neo_research_briefs.models`  - core domain types (ResearchBrief, Status, ...)
- :mod:`neo_research_briefs.adapters` - external-system adapters (all optional)
- :mod:`neo_research_briefs.services.watcher` - idempotent intake loop
- :mod:`neo_research_briefs.cli`     - command-line entry point
"""

from .models import BriefSource, BriefStatus, ResearchBrief

__all__ = ["BriefSource", "BriefStatus", "ResearchBrief", "__version__"]

__version__ = "0.1.0"
