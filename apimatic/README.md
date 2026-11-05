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

```bash
npm i -g @apimatic/cli@2        # Node 24+
apimatic auth login
cd apimatic
apimatic portal serve           # build the portal and preview it locally
apimatic sdk generate           # SDKs (run with --help for the language flags)
apimatic plugin generate        # PayPilot's Context Plugin (uses src/apimatic.json "plugin")
apimatic plugin publish         # prints the git commands to publish it; review, then run them
```

Then host the portal (see APIMatic's *Host Your Portal*), set `portal.pluginUrl` and
`portal.site.url` in `src/apimatic.json`, and link the portal from the README and
the Devpost submission.
