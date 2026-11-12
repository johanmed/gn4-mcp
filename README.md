## GN4 MCP

A remote MCP (Model Context Protocol) server exposing the GeneNetwork4
API to MCP clients: Claude Desktop, claude.ai, Claude Code, or any
MCP client.

### Design decisions

| Decision | Choice |
|---|---|
| Tool surface | Auto-generated from the API's `/openapi.json` (72 tools); the specs summaries become tool descriptions |
| Authentication | Pure pass-through: the `Authorization` header the MCP client sends is forwarded verbatim to the API, which does all verification/authorisation (gn-auth JWTs, resource-level checks) |
| Output validation | Permissive (`validate_output=False`): the proxy never rejects a valid API response over schema drift |
| Oversized responses | Truncated at the MCP layer (default 60k chars) — both the text block *and* the structured payload, so nothing huge crosses the wire |
| Transport | Streamable HTTP, stateless, plain-JSON responses (proxy-friendly) |
| Deployment | Same box as the API is *not* required; runs anywhere with network access to the API; behind nginx at `/gn4-mcp/` |

### Files

- `server.py` — the server
- `test.py` — acceptance checks against the real API
- `start.sh` — start/stop/restart/status (nohup + pid file, matching
  this box's existing pattern; start verifies the server actually
  answers before reporting success)
- `requirements.py` - list of dependencies to install for deployment

### Running

#### Full run

```sh
./start.sh        # start server
./start.sh status
./start.sh restart
./start.sh stop
tail -f /tmp/gn4-mcp.log
```

#### Run server only

The API base URL is a positional argument to `server.py` (required)

Other flags (see `server.py --help`):
- `--target-port` (default 9000)
- `--host` (default 127.0.0.1)
- `--path` (default /gn4-mcp/mcp)
- `--max-chars` (truncation limit, default 60000)
- `--timeout` (upstream API timeout in seconds, default 900).

`--path` should match the path the reverse proxy forwards, so
that when nginx passes the original URL through unmodified, the server
recognises it.

### nginx config

On the box running nginx, add next to the existing `/gn4/` location:

```nginx
location /gn4-mcp/ {
    proxy_pass http://127.0.0.1:9000;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header Connection "";
    proxy_buffering off;
    proxy_read_timeout 1h;
}
```

Public MCP endpoint: `https://vesuvio.pu.ac.ke/gn4-mcp/mcp`

### Connecting to Claude

Users need a gn-auth bearer token. Until self-service issuance exists,
tokens are handed out manually; each user should have their own token
(their baskets/identity in the API are per-token-subject).

**claude.ai / Claude Desktop** — Settings → Connectors → Add custom
connector:

- URL: `https://vesuvio.pu.ac.ke/gn4-mcp/mcp`
- Custom header: `Authorization` = `Bearer <token>`

**Claude Code / CLI clients:**

```sh
claude mcp add --transport http gn4 https://vesuvio.pu.ac.ke/gn4-mcp/mcp \
  --header "Authorization: Bearer <token>"
```

Tokens are static in the connector config. When one expires, the user
updates it in their connector settings.

### Tests

```sh
# Quick online: test the real API through the running server.
./start.sh && ./.venv/bin/python test.py

# Full online suite (token-carrying checks 4-5):
GN4_AUTH_TOKEN=<token> ./.venv/bin/python test.py
```

What is checked:
1. tools listed (72)
2. `version` returns the live API's build info
3. A tool without a token surfaces the API's 401 envelope
4. The same tool with a token succeeds
5. `group_traits BXD` (the 15k-trait listing) comes back truncated


### Implementation notes

- **`get_http_headers()` strips credentials by default.** fastmcp's
  helper deliberately excludes `authorization`/`cookie` from what it
  returns; the MCP's `BearerPassThrough` calls it with
  `include={"authorization"}` — the documented opt-in for proxy
  transports. Removing that `include=` silently breaks all
  authentication (tools would always report the API's 401).
- **httpx2, not httpx.** fastmcp 4 expects an `httpx2.AsyncClient`
  (a fork shipped as a fastmcp dependency); passing a legacy
  `httpx.AsyncClient` goes through a deprecation bridge slated for
  removal.
- **JSON responses arrive as `structured_content`**, which fastmcp
  auto-mirrors into a JSON text block. The truncation middleware caps
  *both*, and replaces the structured payload with a small notice when
  oversized.
- The MCP holds no state and no secrets; restarting it loses nothing.
- The plots endpoints (`/plot/*`) are exposed as tools like everything
  else; they return SVG, which a text-only client can't render. Harmless;
  exclude later with a `route_maps` filter if they prove noisy.
- If the API adds endpoints, the MCP picks them up on restart (the spec
  is fetched at startup).
