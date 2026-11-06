# PayPilot on APIMatic

This folder is an [APIMatic](https://docs.apimatic.io/v4/) project for **PayPilot's
own API**. From it the APIMatic CLI builds:

* a **developer portal** - API reference with a live playground, code samples, the
  guides in `src/content/`, and AI page actions (`llms.txt`);
* **SDKs** in Python and TypeScript - what an external supplier agent or a merchant
  integration would use;
* a **Context Plugin** for PayPilot - so AI coding agents (Claude Code, Cursor, VS
  Code, Codex) integrate with PayPilot from grounded context, the same way the
  PayPal Context Plugin helped build PayPilot's PayPal integration.

```
apimatic/
  src/
    apimatic.json          portal branding/navigation, plugin identity, SDK languages
    spec/openapi.json      generated - do not edit (see below)
    content/               portal home page and guides (Markdown + nav.json)
```

## Refresh the spec

```bash
python scripts/export_openapi.py   # writes docs/openapi.json and apimatic/src/spec/openapi.json
```

The export adds the server URLs, a real description, and readable operation ids
(`create_procurement`, `capture_payment` - they become SDK method names).

## Build (needs an APIMatic account)

The CLI is `@apimatic/cli` 2.x (Node 22.14+): `npm i -g @apimatic/cli@2`. Every build
command needs you signed in - either once with `apimatic auth login` (opens the
browser), or with an API key from the APIMatic dashboard (**Account -> API Keys**) in
the root `.env` as `APIMATIC_API_KEY`. The scripts pass it as `--auth-key` and never
print it.

```bash
scripts/apimatic.sh             # refresh spec, validate, portal, Python + TypeScript SDKs, plugin
scripts/apimatic.sh serve       # live preview at http://localhost:23513
scripts/apimatic.sh portal      # just the static portal -> apimatic/portal
```

On Windows PowerShell: `.\scripts\apimatic.ps1` with the same steps.

Outputs (all generated and git-ignored - rebuild them with the script): `apimatic/portal/`
(static site, also rebuilt on deploy), `apimatic/sdk/python`, `apimatic/sdk/typescript`,
`apimatic/plugin/`. The portal's *SDKs* and *Context Plugin* pages offer the same SDKs and
plugin as zip downloads.

## Using the Python SDK

```bash
pip install ./apimatic/sdk/python      # or download python.zip from the portal
```

```python
from pay_pilot_api import PayPilotApiClient

# environment="production" is the hosted API; base_url points at any other server.
with PayPilotApiClient(base_url="http://localhost:8000") as anon:
    session = anon.auth_api.login({"email": "owner@juniperoak.com", "password": "Autopilot@2024"})
    token = session.data.tokens.access_token

with PayPilotApiClient(base_url="http://localhost:8000", http_bearer=token) as client:
    radar = client.paypal.subscription_radar(days_back=90, days_ahead=45)
    print(radar.data["summary"])
    procurements = client.supply_agents.list_procurement()
```

`AsyncPayPilotApiClient` has the same methods as coroutines. Methods are grouped like the API
tags (`client.supply_agents`, `client.paypal`, `client.inventory`, ...); the full list is in
the generated `api-reference.md`.
`apimatic plugin publish` prints the git commands to publish the plugin; review them
before running.

## Host it

`render.yaml` includes **`paypilot-docs`**, a free Render static site that runs
`apimatic portal generate` on every deploy and serves `apimatic/portal`. Set
`APIMATIC_API_KEY` on that service when Render asks. `portal.site.url` in
`src/apimatic.json` is `https://paypilot-docs.onrender.com`; change it if Render gives
the service another name.
