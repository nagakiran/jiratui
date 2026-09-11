# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

JiraTUI is a Text User Interface (TUI) and CLI for interacting with Atlassian Jira (Cloud and Data Center) from the
terminal. Built with [Textual](https://textual.textualize.io/) (UI framework), Rich (rendering) and Click (CLI). It
talks to the Jira Cloud Platform REST API (v2 and v3) or the Jira Data Center REST API.

## Commands

Environment is managed with `uv`. Python `>=3.12,<3.15`.

```shell
make env                       # uv sync --all-groups
make install_pre_commit_hooks  # installs pre-commit + pre-push hooks
```

Lint/format/type-check (all three run in CI and pre-commit):

```shell
make lint       # ruff format --diff, ruff check, mypy (writes /tmp/artifacts/mypy.xml)
make lint-fix   # ruff format + ruff check --fix
```

Tests:

```shell
make test                                            # uv run --no-sync pytest src/jiratui
uv run pytest src/jiratui/api/tests/test_api.py       # single file
uv run pytest src/jiratui/api/tests/test_api.py::test_name -k pattern  # single test
```

Tests live next to the code they cover, in a `tests/` subpackage per module (e.g.
`src/jiratui/widgets/comments/tests/`, `src/jiratui/api_controller/tests/`), not in one central test tree. Shared
fixtures (e.g. `config_for_testing`, a mocked `ApplicationConfiguration`) are in `src/jiratui/conftest.py`. Async
tests are marked with `@pytest.mark.asyncio`.

Manually exercising the TUI while developing (per CONTRIBUTING.md):

```shell
# terminal 1
textual console
# terminal 2
textual run --dev src/jiratui/app.py
```

Docs (Sphinx, in `docs/`):

```shell
make docs-live      # sphinx-autobuild with live reload
make docs-markdown
make docs-html
```

## Architecture

Four layers, each only calling the one below it — **UI and CLI must never call the API layer directly, only through
the API Controller**:

```
widgets/ (Textual UI)  ─┐
                         ├──>  api_controller/controller.py (APIController)  ──>  api/api.py (JiraAPI*)  ──>  Jira REST API
commands/ (CLI, via cli.py) ─┘
```

- **`api/client.py`** — low-level HTTP: `JiraTUIAsyncHTTPClient` (raw/non-JSON, e.g. attachment downloads),
  `JiraClient` (sync JSON, used for attachment uploads), `AsyncJiraClient` (async JSON, the main client). All three
  translate HTTP status codes into the custom exception hierarchy in `exceptions.py` (`ResourceNotFoundException`,
  `AuthorizationException`, `PermissionException`, `ServiceUnavailableException`, etc.) and handle SSL/cert setup and
  Basic vs Bearer auth (`use_bearer_authentication` config).
- **`api/api.py`** — `JiraAPI` (Cloud, REST v3, default), `JiraAPIv2` (Cloud, REST v2), `JiraDataCenterAPI` (on-prem).
  One method per Jira REST endpoint; no cross-endpoint orchestration.
- **`api_controller/controller.py`** — `APIController` is the single entry point used by both the UI and the CLI.
  Picks which of the three `JiraAPI*` classes to instantiate based on config (`cloud`, `jira_api_version`). Every
  public method returns an `APIControllerResponse(success, result, error)` dataclass — callers branch on `.success`
  rather than catching exceptions. `api_controller/factories.py` has `WorkItemFactory` for building domain objects
  from raw API payloads.
- **`config.py`** — `ApplicationConfiguration` (pydantic-settings `BaseSettings`) loaded from a YAML file located via
  `JIRA_TUI_CONFIG_FILE` env var or the XDG base dir spec (see `files.py`), then overridden by env/dotenv/init
  sources (`extra='allow'`, so unknown keys don't error). `CONFIGURATION` is a module-level `ContextVar` set once in
  `JiraApp.__init__`/CLI startup and read anywhere via `CONFIGURATION.get()` — don't thread config through call
  chains, just read the ContextVar.
- **`app.py`** — `JiraApp` (Textual `App`) entry point for the UI; mounts `widgets/screen.py::MainScreen`, which is
  the hub composing nearly every other widget (search filters, results table, tabs for details/comments/attachments/
  worklog/subtasks/related items/remote links).
- **`widgets/`** — organized by domain, each with its own `tests/` subpackage: `attachments/`, `comments/`,
  `related_work_items/`, `remote_links/`, `work_item_details/`, `work_item_info/`, `work_item_subtasks/`,
  `work_item_worklog/`, `create_work_item/`, and `screens/` for modal/full screens (help, config, quit, git, goto,
  jql, history, text search, work item quick view). `widgets/commons/base.py` defines the `BaseFieldWidget` /
  `BaseUpdateFieldWidget` mixins and the `FieldMode` enum (`CREATE`/`UPDATE`) shared by every field widget so the same
  widget classes serve both the "create work item" and "update work item" forms. `widgets/commons/factories.py`'s
  `WidgetBuilder` dynamically builds the right field widget from Jira field metadata (`FieldMetadata`,
  `AllowedValuesParser`).
- **`commands/`** — CLI internals used by `cli.py` (Click groups: `comments`, `config`, `issues`, `ui`, `users`,
  `version`, `themes`). `commands/handler.py::CommandHandler` calls `APIController`; `commands/render.py` has one
  `*Renderer` class per output shape (issue search results, comments, metadata, users/groups, themes, exceptions),
  used to format Rich tables/output for the CLI.
- **`models.py`** — pydantic domain models (`JiraIssue`, `Project`, `JiraUser`, `IssueStatus`, etc.) plus the shared
  `BaseModel`.
- **`utils/`** — `session.py` (`ApplicationSession`, cleared on app unmount), `history.py` (`HistoryManager`/
  `HistoryEntry` for the recently-viewed-items screen), `adf.py` (Markdown ⇄ Atlassian Document Format conversion,
  needed because REST v3 uses ADF for rich text and v2 doesn't), `urls.py` (building external Jira web links).

Import boundary enforced by `import-linter` (`pyproject.toml` `[tool.importlinter]`, also run in pre-commit and
`make lint`): `jiratui` must never import from `docs`.

Style: ruff-formatted with **single quotes**, 100-char lines, isort with `force-sort-within-sections`; see
`ruff.toml` for the full rule set. mypy runs with `strict_optional = false`.
