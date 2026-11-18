# Register a local methodology

A workflow is a guide you already use, such as field research or a staged editorial review. Register it explicitly to keep unrelated Markdown out of the search index. The shipped [field study](../examples/field-study/) is a complete example.

1. Add a JSON catalog to the configuration's `catalogs` list. Relative paths resolve beside the config file.
2. Add an item with `"kind": "workflow"`, a stable lowercase `id`, a `name`, a searchable `description`, and an `entry` pointing to an existing Markdown overview inside the catalog's directory.
3. Place `workflow.json` beside the overview. Give each phase an `id` and a relative Markdown `instructions` path inside that guide. List any earlier phase IDs in `requires`. Set `requires_approval` to `true` when the owner must approve that phase.
4. Run `scan` after editing catalog entries. Use `find` with task vocabulary to discover the overview. The phase resolver reads the manifest at invocation time.

```sh
python -m orchestrator workflow workflow/field-study --config examples/field-study/config.json --json
```

The response reports `done`, `ready`, `waiting` and `complete`. A gated phase appears as `requires-approval` until the caller passes an explicit approval. After the owner approves review and observations are complete, run:

```sh
python -m orchestrator workflow workflow/field-study --done observe --approved review --config examples/field-study/config.json
```

Use globally unique workflow IDs across catalogs. The resolver rejects ambiguous IDs, missing instruction files, dependencies on later phases and paths that resolve outside the guide. Completion and approval flags describe facts supplied by the caller. The command prints instructions to open and leaves execution and consent with the host.
