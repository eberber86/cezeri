"""Cezeri tool registry: TOOLS maps tool name -> callable.

Per CONTRACT.md "Tool registry":
- W3 (literature chunk): search_pubmed, search_semantic_scholar,
  search_europe_pmc, format_citations.
- W4 (safety/files chunk): read_file, list_dir, propose_write, propose_exec.

The orchestrator (W2) executes ``TOOLS[name](**args)`` for ReAct `````tool```
blocks emitted by the models.
"""

from .files import list_dir, propose_exec, propose_write, read_file
from .literature import (
    format_citations,
    search_europe_pmc,
    search_pubmed,
    search_semantic_scholar,
)

TOOLS: dict[str, callable] = {
    # Literature (W3)
    "search_pubmed": search_pubmed,
    "search_semantic_scholar": search_semantic_scholar,
    "search_europe_pmc": search_europe_pmc,
    "format_citations": format_citations,
    # Scoped files (W4)
    "read_file": read_file,
    "list_dir": list_dir,
    "propose_write": propose_write,
    "propose_exec": propose_exec,
}

__all__ = ["TOOLS"]
