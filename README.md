# skills-orchestrator

Platform-agnostic registry, search and safety scanner for agent skills.

> Work in progress (v0.1). The full documentation lands with the first release.

```text
python -m orchestrator scan --root ~/.claude/skills::mine --out registry.json
python -m orchestrator find "write tests before code" --registry registry.json
python -m orchestrator overlaps --registry registry.json
python -m orchestrator doctor --registry registry.json
python -m orchestrator vet path/to/cloned-repo
```

Python 3.9+, standard library only. Run the tests with `python -m unittest discover -s tests -t .`.

License: MIT.
