### GitHub Actions

This folder contains the CI checks for the repo:

- `unit-test.yml` runs unit tests and validates the runtime config contract for API, pipeline, and harvester profiles.
- `integration-test.yml` runs Postgres-backed integration tests.
- `docker-check.yml` builds the CPU Docker image, checks the pipeline CLI, validates runtime config inside the image, and smoke-tests the API container.

`tests/generator_contract/` is deliberately not run by any workflow: it calls OpenAI for real and is non-deterministic. It runs by hand at the points listed in CONTRIBUTING.md ("The generator contract suite").
