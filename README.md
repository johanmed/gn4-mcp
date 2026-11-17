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

### Example

Query: What are the classical traits available in GN for HS rats?

```
Here's the complete picture of **classical (published/phenotype) traits** for HS (Heterogeneous Stock) rats in GN4 — three groups, no expression probesets included:

## 1. HSNIH-Palmer — NIH Heterogeneous Stock (Palmer) — **508 phenotype traits**
- **505 traits from "Unpublished data from HSNIH-Palmer group" (Palmer, Chen, Solberg Woods, Flagel, Robinson et al., 2020)** + 3 traits from *"Genetics of nicotine use and the influence of social cues in adolescent rats"* (2020)
- Overwhelmingly **behavioral / neuropsychiatric** (~465 CNS-behavior + 37 psychiatry-motivation + 8 pharmacology traits)
- Major assay families (by abbreviation prefix):
  - `social` (82) — social behavior measures
  - `reaction` (77) — reaction-time / response measures
  - `pavca` (67) — **Pavlovian Conditioned Approach** (sign-tracking vs goal-tracking, lever/magazine contacts per day, learning index)
  - `nicsa` (62) — **nicotine self-administration**
  - `light` (51) — light–dark box anxiety measures
  - `locomotor` (32) — locomotor activity
  - `novelty` (21), `ccc`/`ccp` (29) — cocaine conditioned place preference/sensitization
  - `elevate` (10) — elevated plus/zero maze
  - `crf`, `open field`, plus a handful of cofactors/metadata (weight, sex, batch, color)

## 2. HSNIH-RGSMC — NIH HS (Rat Genome Sequencing & Mapping Consortium 2013) — **147 phenotype traits**
- All from one paper: *Baud et al., "Combined sequence-based and genetic mapping analysis of complex traits in outbred rats," **Nature Genetics** 45:767–775, 2013* (PMID 23708188)
- Broad physiological phenotyping:
  - **Musculoskeletal** (43) — femur structure/biomechanics, bone density
  - **Immunology** (42) — immune traits (EAE/collagen-induced arthritis-related)
  - **Blood biochemistry / metabolism** (14+8) — glucose tolerance (AUC, G30/G60/G120), lipids, renal/liver function
  - **CNS behavior** (10) — anxiety assays (open field, zero maze, conditioned freezing, Box-Cox normalized)
  - **Red blood cell** (9), **cardiovascular** (8, incl. tail-cuff blood pressure, heart weight), **platelet function** (7)
  - **Skin pigmentation** (4), regeneration, renal, body weight

## 3. HSNIH-Palmer_r4 — HSNIH-Palmer (adipose/liver cohort) — **0 published traits**
- This newer group (Feb 2026 genotypes) has no phenotype records yet — it currently only carries the two RNA-Seq expression datasets (adipose `HSNIH-PalmerAT0226`, liver `HSNIH-PalmerLiv0226`).

**Total: 655 classical traits** (508 + 147). Want me to pull the actual strain values or QTL peak info for any specific trait (e.g., a `pavca` sign-tracking trait or blood pressure)?

```

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
