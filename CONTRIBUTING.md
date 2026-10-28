# Contributing to BusinessObjects to Power BI Migration Tool

Thank you for your interest in contributing! This guide covers the development setup,
coding standards, and contribution workflow.

---

## Development Setup

### Prerequisites

- Python 3.12+
- Git

### Getting Started

```bash
# Clone the repository
git clone <repo-url>
cd BOToPowerBI

# Create a virtual environment
python -m venv .venv
.venv\Scripts\activate   # Windows
# source .venv/bin/activate  # macOS/Linux

# Install development tools (same minimum versions as pyproject.toml's dev extra)
python -m pip install "pytest>=8.0" "pytest-cov>=5.0" "ruff>=0.3.0" "pyright>=1.1.350"

# Run tests
python -m pytest tests/ --tb=short -o addopts="" -q
```

Core migration uses the standard library. The requirements file installs optional
cloud dependencies, not development tools; install it only when working on those
integrations. Running from the source checkout avoids relying on package-install
support. A clean-environment installation was not run for the 2026-10-28 doc review.

### Project Structure

```
bo_export/   → Source extraction / parsing
migration_output, powerbi_import/   → Target generation
tests/        → Unit and integration tests
docs/              → Documentation
```

## Coding Standards

### Style

- Follow PEP 8
- Maximum line length: 120 characters (soft limit)
- Use type hints where practical

### Naming Conventions

- Private methods prefixed with `_`
- Constants as `UPPER_SNAKE_CASE`

### Testing

- All new features MUST have tests
- Run `python -m pytest tests/ --tb=short -q` after implementation changes and before committing
- Never weaken assertions to make tests pass

## Contribution Workflow

1. Create a feature branch: `git checkout -b feat/your-feature`
2. Make changes and add tests
3. Run the test suite: `python -m pytest tests/ --tb=short -q`
4. Commit with conventional messages: `feat:`, `fix:`, `test:`, `docs:`
5. Push and create a pull request

## Multi-Agent Architecture

This project uses a specialized agent model. See `docs/AGENTS.md` for details.
Each agent has scoped ownership — check which agent owns the files you're modifying.
