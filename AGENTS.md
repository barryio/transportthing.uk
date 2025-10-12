# Agent Guidelines for transportthing.uk

## Commands
**Python/Django:**
- Install: `uv sync --group dev --group test`
- Lint: `uv run ruff check . && uv run ruff format --check .`
- Format: `uv run ruff format .`
- Test all: `uv run python manage.py test`
- Test single: `uv run python manage.py test app.tests.TestClass.test_method`
- Test file: `uv run python manage.py test app.test_module`

**JavaScript/TypeScript:**
- Install: `npm install`
- Build: `npm run build`
- Watch: `npm run watch`
- Lint: `npm run lint` (TypeScript strict checking)
- Test all: `npm test`
- Test single: `npm test -- --testNamePattern="test name"`
- Format: `npx biome format --write .`

**Pre-commit:** `pre-commit run --all-files`

## Code Style
**Python:** 123 char lines (flake8). snake_case vars/functions, PascalCase classes. Type hints required. Django ORM patterns. Standard library imports first, then third-party, then local. Ruff lints SIM117, F401.

**JavaScript/TypeScript:** 2-space indent. camelCase vars/functions, PascalCase components. Strict TypeScript. React JSX. ES6+ features. Error boundaries. Biome lints recommended rules with noParameterAssign/suspicious warnings.

**General:** Pre-commit hooks enforce formatting (ruff, biome, djade for Django templates). Meaningful commits with conventional prefixes. Never commit secrets. Use Django REST framework patterns for APIs.