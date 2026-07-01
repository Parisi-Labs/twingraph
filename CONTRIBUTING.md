# Contributing

Thanks for working on TwinGraph. The core package is intentionally small and
dependency-clean, so most contributions should preserve these boundaries:

- `twingraph` must not import product/application code.
- Runtime connectors, optimizers, model implementations, data warehouses, and
  UI code stay outside the package.
- The base runtime dependency budget is stdlib + `pydantic`.
- Public examples must be illustrative and must not include customer data,
  private infrastructure details, credentials, or generated operator evidence.

## Development

```bash
python -m pip install -e ".[dev]"
pytest
ruff check src/twingraph tests
python -m twingraph._schema_tool > schema/twingraph-0.1.schema.json
```

Run the full test suite before opening a pull request. If you change pydantic
models, regenerate the JSON Schema and make sure `tests/test_schema_parity.py`
passes.

## Design Guidelines

- Prefer typed primitives and registry seams over ad hoc dictionaries.
- Keep compile deterministic and side-effect free.
- Add type-pack vocabulary only when it describes reusable IR concepts, not a
  single customer or internal product workflow.
- Keep diagnostics stable and actionable.
- Do not hide uncertainty. Use evidence, provenance, confirmation state, and
  validation results to make boundaries explicit.
