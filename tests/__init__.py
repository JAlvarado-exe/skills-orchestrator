"""Keep the whole suite away from the real user configuration and registry.

The CLI reads ~/.skills-orchestrator/config.json and registry.json by default. Pointing both
environment variables at a folder that is never created makes every test hermetic, whatever is
installed on the machine that runs it.
"""
import os
import tempfile

_GUARD = os.path.join(tempfile.gettempdir(), "skills-orchestrator-tests-no-such-home")
os.environ["SKILLS_ORCHESTRATOR_CONFIG"] = os.path.join(_GUARD, "config.json")
os.environ["SKILLS_ORCHESTRATOR_REGISTRY"] = os.path.join(_GUARD, "registry.json")
