# 6. The Ge Fei catalog is read live; calls are recorded

Status: accepted (2026-11-13, rebuild)

`/api/v1/tools` and `/api/openapi.json` are the only source of which endpoints exist and what they take. The client stores each catalog snapshot and can call any tool in it, including OpenAPI-only operations (`me`, `usage`). Nothing in the repo lists endpoints by hand, so new endpoints are callable the day they ship.

HTTP is the integration; MCP is for exploration the agent does not cite. Every call records parameters, URL, status, `requestId`, credits actually charged and the full response. Identical successful query calls are reused for 7 days (knowledge base 30) to avoid paying twice; data services are re-listed each run but batch details are fetched only when new, recent or previously failed.
