"""Observability tests reuse the agent fixtures: scripted runs on real documents."""

from tests.modules.agent.conftest import (  # noqa: F401
    agent_pipeline,
    agent_settings,
    make_document,
    run_agent,
)
