# jira-xray-cloud-mcp

MCP server for [Xray Test Management](https://www.getxray.app/) on Jira Cloud. It exposes the Xray Cloud
REST API v2 and GraphQL API as MCP tools. Tools are grouped into **toolsets**, each split into a read and a
write half that you can switch on and off. Single tools can be added or removed on top of that, and a
**read-only switch** removes every write tool from the server.

- 84 Xray tools in 14 toolsets / 25 halves (31 read, 53 write), plus `xray_list_toolsets`.
- Credentials from the environment (one Xray API key for the server) or from **HTTP request headers**
  (every user brings their own key).
- Tools take Jira issue keys (`CALC-12`) as well as numeric issue ids. Xray's GraphQL API itself only
  accepts ids; the server looks the keys up.
- Write tools carry MCP annotations (`readOnlyHint`, `destructiveHint`, `idempotentHint`), so clients can
  ask for confirmation before destructive calls.
- The raw GraphQL toolset (`xray_graphql_query`, `xray_graphql_mutation`, `xray_graphql_schema`) covers
  whatever the dedicated tools don't. The Xray schema is bundled, so the model can look it up.

## Configuration

All settings are environment variables (see [.env.example](.env.example)):

| Variable                  | Default                          | Meaning |
|---------------------------|----------------------------------|---------|
| `XRAY_AUTH_MODE`          | `env`                            | `env`: one API key for the server, from `XRAY_CLIENT_ID` / `XRAY_CLIENT_SECRET`. `headers`: every HTTP request brings its own key (see [Credentials](#credentials)). |
| `XRAY_CLIENT_ID`          | –                                | Client id of an Xray API key (Xray → Global Settings → API Keys). `env` mode only. |
| `XRAY_CLIENT_SECRET`      | –                                | Client secret of that API key. Every call runs as the key's Jira user. `env` mode only. |
| `XRAY_BASE_URL`           | `https://xray.cloud.getxray.app` | Regional hosts: `https://us.`, `https://eu.`, `https://au.xray.cloud.getxray.app`. |
| `XRAY_READ_ONLY`          | `false`                          | `true` registers read tools only, whatever the selection says. Write tools do not exist on the server, and the HTTP client also refuses mutations and non-GET REST calls as a second safeguard. |
| `XRAY_TOOLSETS`           | `default`                        | Which toolset halves to enable (see below). |
| `XRAY_TOOLS`              | –                                | Single tools to add to or remove from that selection (see below). |
| `XRAY_TIMEOUT`            | `60`                             | HTTP timeout in seconds. |
| `XRAY_MAX_DOWNLOAD_BYTES` | `10485760`                       | Largest file that attachment/backup/export tools return inline. |

### Credentials

Xray Cloud authenticates with API keys only (client id + secret, exchanged for a 24h token that the
server caches).

- **`XRAY_AUTH_MODE=env`** (default): the server uses `XRAY_CLIENT_ID` / `XRAY_CLIENT_SECRET` for every
  caller. Suited to stdio and to single-user deployments.
- **`XRAY_AUTH_MODE=headers`**: every request must carry `X-Xray-Client-Id` and `X-Xray-Client-Secret`.
  Calls then run as that key's Jira user, and tokens are cached per key. `XRAY_CLIENT_ID` /
  `XRAY_CLIENT_SECRET` are ignored. This needs the HTTP transport; serve it over HTTPS only (e.g. behind a
  TLS-terminating reverse proxy), since the headers carry the secret.

### Selecting toolsets

Each toolset is split into a read half (`<name>_read`) and a write half (`<name>_write`). Toolsets without
write tools only have a read half. `XRAY_TOOLSETS` is a comma-separated list, applied left to right:

- `default`: both halves of every toolset except the opt-in ones (currently `backup`)
- `all`: every half
- `<name>`: both halves of a toolset, e.g. `tests`
- `<name>_read` / `<name>_write`: one half, e.g. `tests_read`
- `*` wildcards, e.g. `*_read` (this also matches opt-in toolsets)
- `-<token>`: remove, e.g. `-graphql` or `-*_write`

Examples: `default,backup` · `all,-graphql` · `*_read,test_runs_write` (read everything, write only test
results) · `tests_read,test_executions,test_runs`.

### Selecting single tools

`XRAY_TOOLS` works on top of `XRAY_TOOLSETS`, with the same syntax: `<tool>` adds a tool (also from a
toolset that is not selected), `-<tool>` removes one, `*` wildcards are allowed, and tokens are applied
left to right. Examples: `-xray_delete_*` (no delete tools) · `xray_get_test_run,xray_update_test_run`
(on top of a read selection). `XRAY_READ_ONLY=true` still wins over any tool added here.

The server refuses to start if a toolset, tool or pattern matches nothing, so a typo cannot silently
change the tool list. `xray_list_toolsets` reports what is enabled at runtime.

### Toolsets and tools

| Toolset | Scope | `_read` | `_write` |
|---------|-------|---------|----------|
| `tests` | Test issues, steps, definitions, versions, datasets, links | `xray_get_test`, `xray_get_tests`, `xray_get_expanded_test`, `xray_get_test_versions`, `xray_get_datasets` | `xray_create_test`, `xray_delete_test`, `xray_update_test_type`, `xray_update_test_definition`, `xray_add_test_step`, `xray_update_test_step`, `xray_remove_test_step`, `xray_remove_all_test_steps`, `xray_add_test_associations`, `xray_remove_test_associations` |
| `preconditions` | Precondition issues | `xray_get_precondition`, `xray_get_preconditions` | `xray_create_precondition`, `xray_update_precondition`, `xray_delete_precondition`, `xray_add_tests_to_precondition`, `xray_remove_tests_from_precondition` |
| `test_sets` | Test Set issues | `xray_get_test_set`, `xray_get_test_sets` | `xray_create_test_set`, `xray_delete_test_set`, `xray_add_tests_to_test_set`, `xray_remove_tests_from_test_set` |
| `test_plans` | Test Plan issues | `xray_get_test_plan`, `xray_get_test_plans` | `xray_create_test_plan`, `xray_delete_test_plan`, `xray_add_tests_to_test_plan`, `xray_remove_tests_from_test_plan`, `xray_add_test_executions_to_test_plan`, `xray_remove_test_executions_from_test_plan` |
| `test_executions` | Test Execution issues, environments | `xray_get_test_execution`, `xray_get_test_executions` | `xray_create_test_execution`, `xray_delete_test_execution`, `xray_add_tests_to_test_execution`, `xray_remove_tests_from_test_execution`, `xray_add_test_environments`, `xray_remove_test_environments` |
| `test_runs` | Results: status, comments, defects, evidence, steps, iterations, progress | `xray_get_test_run`, `xray_get_test_runs`, `xray_get_test_progress` | `xray_update_test_run`, `xray_reset_test_run`, `xray_set_test_run_timer`, `xray_update_test_run_defects`, `xray_add_test_run_evidence`, `xray_remove_test_run_evidence`, `xray_update_test_run_step`, `xray_update_test_run_iteration_status`, `xray_update_test_run_example_status` |
| `test_repository` | Folder tree of the Test Repository and of Test Plans | `xray_get_folder` | `xray_create_folder`, `xray_rename_folder`, `xray_move_folder`, `xray_delete_folder`, `xray_move_to_folder`, `xray_remove_from_folder` |
| `coverage` | Requirement coverage | `xray_get_coverable_issue`, `xray_get_coverable_issues` | – |
| `history` | Change history of Xray issues | `xray_get_issue_history` | – |
| `settings` | Statuses, link types, project settings, step libraries | `xray_get_statuses`, `xray_get_issue_link_types`, `xray_get_project_settings`, `xray_get_step_library` | – |
| `imports` | REST: result imports (Xray JSON, Cucumber, Behave, JUnit, TestNG, NUnit, xUnit, Robot), bulk test import, Cucumber features | `xray_get_import_tests_status`, `xray_export_cucumber_features` | `xray_import_execution_results_json`, `xray_import_execution_results_xml`, `xray_import_tests_bulk`, `xray_import_cucumber_features` |
| `attachments` | REST: attachment storage | `xray_get_attachment` | `xray_upload_attachment` |
| `backup` *(opt-in)* | REST: Xray backups (admin) | `xray_get_backup_status`, `xray_download_backup` | `xray_create_backup` |
| `graphql` | Raw GraphQL + schema lookup | `xray_graphql_schema`, `xray_graphql_query` | `xray_graphql_mutation` |

`xray_get_test_progress` counts the Tests of a Test Plan or Test Execution per status on the server (e.g.
"412 Tests: 380 PASSED, 20 FAILED, 12 TODO"), so the model does not need to page through hundreds of runs.

## Running

```bash
# stdio (local MCP clients)
XRAY_CLIENT_ID=... XRAY_CLIENT_SECRET=... jira-xray-cloud-mcp

# HTTP, as in docker-compose.yml
fastmcp run server.py:mcp --transport http --host 0.0.0.0 --port 8000
```

Register it with Claude Code, here locally over stdio, read-only, with a limited set of toolsets:

```bash
claude mcp add xray \
  -e XRAY_CLIENT_ID=... -e XRAY_CLIENT_SECRET=... \
  -e XRAY_READ_ONLY=true -e XRAY_TOOLSETS=tests,test_executions,test_runs,coverage \
  -- jira-xray-cloud-mcp
```

Or connect to a shared HTTP deployment running with `XRAY_AUTH_MODE=headers`, using your own API key:

```bash
claude mcp add --transport http xray https://xray-mcp.example.com/mcp \
  --header "X-Xray-Client-Id: ..." --header "X-Xray-Client-Secret: ..."
```

### Docker

Every release is published to `ghcr.io/netcare-io/jira-xray-cloud-mcp` as `<version>`,
`<major>.<minor>` and `latest`:

```bash
# HTTP, every user brings their own API key
docker run --rm -p 8000:8000 -e XRAY_AUTH_MODE=headers ghcr.io/netcare-io/jira-xray-cloud-mcp:latest \
  fastmcp run server.py:mcp --transport http --host 0.0.0.0 --port 8000

# stdio, e.g. as the command of a local MCP client
docker run --rm -i -e XRAY_CLIENT_ID=... -e XRAY_CLIENT_SECRET=... ghcr.io/netcare-io/jira-xray-cloud-mcp:latest
```

`docker compose up` builds the `production` image locally and reads the variables from `.env`.

## Development

```bash
pip install -e ".[dev]"
pytest
```

The tests run the server in memory against a fake Xray (`httpx2.MockTransport`), and over the in-process
HTTP stack for header credentials. Every GraphQL document a tool sends is validated, together with its
variables, against the bundled Xray schema. A test also fails when a tool is added without a test case.

`main` only accepts pull requests. CI runs `pytest` on Python 3.12 and 3.13 and builds the Docker image
for every PR. To release, run `scripts/release.sh <version>`: the first run opens a PR that bumps the
version, and a second run on `main` after the merge pushes the `v<version>` tag, which publishes the
image and creates the GitHub release.
Notes for coding agents are in [AGENTS.md](AGENTS.md). Xray API docs:
[REST API v2](https://docs.getxray.app/space/XRAYCLOUD/44565892/REST+API),
[GraphQL API](https://docs.getxray.app/space/XRAYCLOUD/44568019).
