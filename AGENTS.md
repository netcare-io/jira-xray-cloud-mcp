# AGENTS.md

Guidance for coding agents working on this repository.

## What this is

An MCP server (FastMCP 4, Python 3.12) exposing **Xray Cloud** (test management for Jira Cloud) as tools:
the REST API v2 for imports, exports, attachments and backups, and the GraphQL API for everything else.
Tools are grouped into toolsets, each split into a read and a write half, selected via `XRAY_TOOLSETS`;
`XRAY_TOOLS` adds/removes single tools on top, and `XRAY_READ_ONLY` removes all write tools. Credentials
come from the environment or per request from HTTP headers (`XRAY_AUTH_MODE`). User-facing docs are in
`README.md`.

## Layout

```
server.py                  entrypoint: `mcp = create_server()` (fastmcp.json / docker-compose use server.py:mcp)
xray_mcp/config.py         Settings (pydantic-settings, env prefix XRAY_)
xray_mcp/client.py         XrayClient: connection pool, per-key token cache, with_credentials(), REST
                           request(), graphql(), read-only guard, credentials_from_headers(),
                           graphql_operation_types() (detects mutations)
xray_mcp/registry.py       Toolset / ToolSpec / ToolsetPart (read/write half), select_toolsets(),
                           select_tools() (XRAY_TOOLSETS + XRAY_TOOLS), register_tools()
xray_mcp/server.py         create_server(settings, transport=None): lifespan with the client, xray_list_toolsets
xray_mcp/toolsets/         one module per toolset, each exporting `toolset`; ALL_TOOLSETS in __init__.py
xray_mcp/toolsets/_common.py  XRAY dependency (binds header credentials), shared Annotated param types,
                           key->id resolution, search/change helpers, GraphQL selections
xray_mcp/xray_schema.graphql  Xray GraphQL schema (graphdoc format, package data; used by
                           xray_graphql_schema and by the tests)
tests/                     pytest suite against a fake Xray (see Testing)
.github/workflows/         ci.yml (PRs, main), release.yml (v* tags), see CI and releases
scripts/                   release.sh, docker-build-and-publish.sh (Harbor), run-inspector.sh
.agent/                    local copies of third-party reference docs (see below). Git-ignored.
```

## Xray API reference (read this before touching an endpoint)

The GraphQL schema is bundled: `xray_mcp/xray_schema.graphql` (30 queries, 66 mutations, with field docs,
reconstructed from https://us.xray.cloud.getxray.app/doc/graphql/). Check argument nullability and return
types there.

`.agent/` holds local copies of third-party docs. The repo is public and these are not ours, so the
folder is git-ignored and a fresh clone does not have it. Where it exists:
- `xray-docs/rest-api-v2.md`: all REST v2 endpoints, auth, base URLs, rate limits, GraphQL essentials. Start here.
- `xray-docs/schema.graphql`: a copy of `xray_mcp/xray_schema.graphql`; keep them identical.
- `xray-docs/graphql-schema-reference.md`: the schema per operation and type, with the official examples.
- `xray-docs/postman-requests.md`: every request of the official Postman collection, with GraphQL bodies
  and variables. The raw collection plus sample payloads (`xray_result.json`, `testexec_info.json`) sit next to it.
- `fastmcp-upgrade-from-v3-to-v4.md`: FastMCP 3 → 4 changes. The fastmcp skill documents v3.

Sources: REST API v2 https://docs.getxray.app/space/XRAYCLOUD/44565892/REST+API, GraphQL
https://docs.getxray.app/space/XRAYCLOUD/44568019, Postman collection
https://github.com/Xray-App/xray-postman-collections, FastMCP https://gofastmcp.com/llms.txt.

## Design decisions

- **Filter at registration, not by visibility.** `register_toolsets()` only calls `mcp.tool()` for allowed
  tools, so a tool that is disabled or a write tool in read-only mode does not exist on the server.
  `XrayClient` also refuses GraphQL mutations and non-GET REST calls when `read_only` is set.
  Keep both layers.
- **Toolsets are split into halves.** `ToolsetPart` = `<name>_read` / `<name>_write` (a half exists only if
  it has tools). `XRAY_TOOLSETS` selects halves: `default`, `all`, a group name (`tests` = both halves),
  a half, fnmatch wildcards, `-token` removes; left to right. `XRAY_TOOLS` then adds/removes single tools
  with the same syntax (`_apply()` in registry.py serves both). Read-only filtering runs last, in
  `register_tools()`, so it wins over `XRAY_TOOLS`.
- **Unknown names raise at startup**: any toolset/tool token or pattern that matches nothing raises
  `ValueError` (`select_toolsets` / `select_tools`), so a typo cannot silently change the tool list.
- **Credentials (`XRAY_AUTH_MODE`)**: `env` (default) uses `XRAY_CLIENT_ID`/`XRAY_CLIENT_SECRET`;
  `headers` reads `X-Xray-Client-Id`/`X-Xray-Client-Secret` per request. The lifespan holds one
  `XrayClient` (pool + token cache); `_get_client` returns `client.with_credentials(...)`, a shallow copy
  sharing pool and cache. Tokens are cached per sha256(id + secret), max `MAX_CACHED_TOKENS`, with one
  lock per key (weak refs, so they vanish). Missing headers bind no credentials; the first API call raises
  a message naming the headers. OAuth was decided against for now; Xray itself only has API keys.
- **Keys in, ids to Xray.** GraphQL only accepts issue ids. `resolve_ids(client, kind, refs)` passes
  numeric refs through and looks keys up via `get<Kind>s(jql: "key in (...)")`, which also checks the
  issue type. Keys are validated against `_KEY_RE` before they go into JQL (injection guard); keep that.
  Project keys → ids go through `resolve_project_id` (`getProjectSettings`). Defect lists
  (`addDefectsToTestRun` etc.) accept keys natively and are not resolved.
- **The client comes from the lifespan.** Tools declare `client: XrayClient = XRAY` (a `Depends`,
  hidden from the input schema). `create_server(transport=...)` injects an `httpx2` transport for tests.
- **Token:** `POST /authenticate` returns a JSON string. It is cached for 23h (Xray: 24h). On a 401 the
  client re-authenticates once.
- **Fewer, broader tools where the API is redundant**: e.g. `xray_add_test_associations` covers four
  `add*ToTest` mutations, `xray_update_test_run` combines `updateTestRun` + `updateTestRunStatus`,
  `xray_update_test_run_step` wraps `updateTestRunStep` (status/comment/defects/evidence). Every tool's
  description ends up in the model's context (~65k chars for all tools), so do not add 1:1 wrappers
  when an existing tool can take a parameter instead.
- `backup` is opt-in (`Toolset(default=False)`): it is an admin operation with large downloads.

## Conventions

- Tool names: `xray_<verb>_<object>`, unique across toolsets. Every tool returns `dict[str, Any]`
  (FastMCP structured output); wrap scalars, e.g. `{"result": ...}`.
- Declare tools with `@toolset.tool(read_only=..., destructive=..., idempotent=...)`. The flags become
  MCP annotations and the tags (`toolset:<name>_read|_write`, `read`|`write`); `read_only` decides the
  half the tool belongs to and whether it exists in read-only mode.
- The docstring is the tool description, one sentence written for the model. Describe parameters with
  `Annotated[..., Field(description=...)]`, reusing the types in `_common.py` (`IssueRef`, `Limit`, `JiraFields`, ...).
- GraphQL: always use variables, never interpolate user values into documents. Only static selection
  strings are formatted in. Leave optional args out via `compact(...)`. Every connection needs
  `limit` (1–100).
- User errors → `ValueError` (FastMCP turns it into a tool error); API failures → `XrayApiError` (a `ToolError`).
- Files start with the netcare copyright + SPDX header. Code, comments and docs are in English.

## Adding a tool

1. Find the operation in `xray_mcp/xray_schema.graphql` (REST: `.agent/xray-docs/rest-api-v2.md` or the
   Xray REST docs) and check argument nullability and the return type's fields.
2. Add the function to the matching `xray_mcp/toolsets/<name>.py` (new toolset: create the module,
   add it to `ALL_TOOLSETS` and the `.env.example` names list). Add it to the README table and tool counts.
3. Add argument sets to `CASES` in `tests/test_graphql_tools.py` (REST tools: a test in
   `tests/test_rest_tools.py` and the name in `NON_GRAPHQL`). `test_every_tool_has_a_case` fails otherwise.
4. Run `pytest`.

## Testing

- `pytest` (asyncio auto mode). About 20s. There are no live Xray credentials in this environment,
  so nothing calls the real API.
- `tests/conftest.py`: `FakeXray` is an `httpx2.MockTransport` handler that records calls, answers
  `/authenticate`, and validates **every GraphQL document and its variables** against the bundled schema
  with `graphql-core` (graphdoc format converted to SDL in `xray_schema()`). It answers key-lookup
  queries with deterministic ids (`fake_issue_id("CALC-12") == "1000012"`). Hooks: `fake.rest`,
  `fake.graphql_data`, `fake.graphql_response`.
- `connect(**settings_overrides)` fixture → FastMCP in-memory `Client`. Default settings: `toolsets="all"`.
  In-memory clients have no HTTP request, so header credentials are tested with
  `fastmcp.utilities.tests.asgi_client(server, headers=...)` (real HTTP stack, no port), see `tests/test_auth.py`.
- Check a real start with:
  `XRAY_READ_ONLY=true fastmcp run server.py:mcp --transport http --port 8765` (first start takes ~5s).

## CI and releases

- `main` only accepts pull requests (ruleset: PR, green checks, no force push or deletion). Work on a branch.
- `.github/workflows/ci.yml` runs on every PR and push to main: `pytest` on Python 3.12 and 3.13, and a
  build of the Docker `production` stage (not pushed). Its job names are the ruleset's required checks,
  so renaming a job means updating the ruleset.
- `.github/workflows/release.yml` runs on `v*` tags. It checks that the tag is on main and equals
  `v` + `version` from pyproject.toml, runs pytest, pushes the image to
  `ghcr.io/netcare-io/jira-xray-cloud-mcp` (`<version>`, `<major>.<minor>`, `latest`) and creates the
  GitHub release.
- `scripts/release.sh <version>`: the first run opens a version-bump PR; after it is merged, the second
  run on main pushes the tag. `scripts/docker-build-and-publish.sh` pushes to the internal Harbor
  (`harbor.netcare.local`, not reachable from GitHub runners) by hand.

## Gotchas

- **FastMCP 4 is pinned exactly (`fastmcp==4.0.10`).** It uses `httpx2`, not `httpx`. Protocol type
  fields are snake_case (`ToolAnnotations(read_only_hint=...)`, `tool.input_schema`). The default client
  mode is sessionless, so don't rely on `ctx.set_state` persisting between calls.
- Docker `base` stage installs the package before the sources are copied. It stubs `server.py` and the
  `xray_mcp/`, `xray_mcp/toolsets/` packages. **New subpackages must be added to that stub and to
  `[tool.setuptools] packages` in pyproject.toml.**
- Xray GraphQL answers errors with HTTP 200 and `{"errors": [...]}`; `XrayClient.graphql` raises on them.
- Some mutation signatures are asymmetric, e.g. `addTestExecutionsToTest` takes `versionId`
  but `removeTestExecutionsFromTest` doesn't (see `_VERSIONED` in `toolsets/tests.py`). Always check the schema.
- XML result imports: query params (`projectKey`, `testExecKey`, ...) apply only to the non-multipart
  endpoint. With `info`/`testInfo`, everything goes into the multipart JSON parts.
- Rate limit: 300 requests / 5 min (Enterprise 1000). Key resolution costs one extra GraphQL call per
  kind, so prefer ids when you already have them.

## Open / not implemented

- **Decision: Jira stays out unless it has an Xray relation.** No generic Jira tools (issues,
  transitions, comments). Candidates that do qualify, not built yet: linking a Test to a requirement
  (coverage is a Jira issue link; the Xray API has no mutation for it) and creating a defect for a failed
  test run. Both need Jira credentials in addition to the Xray key.
- **Decision: no OAuth for now.** Header credentials cover multi-user deployments. If OAuth comes back,
  the MCP server would have to be its own authorization server that binds the user's Xray key to its
  tokens (FastMCP `OAuthProvider`, see `providers/in_memory.py`), because Xray has no OAuth.
- Deliberately no dedicated tools for `getStatus` / `getStepStatus` by name (`xray_get_statuses` lists
  all) or `updateTestFolder` / `updatePreconditionFolder` (`xray_move_to_folder` covers them). Both are
  reachable via `xray_graphql_query` / `xray_graphql_mutation`.
