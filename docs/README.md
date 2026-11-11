<div align="center">

# PayPilot documentation

Technical documentation for PayPilot, built by Team PayFlux.

[![Project README](https://img.shields.io/badge/-Project_README-0b2a6f?style=flat-square)](../README.md)
[![Quick start](https://img.shields.io/badge/-Quick_start-16a34a?style=flat-square)](QUICKSTART.md)
[![Architecture](https://img.shields.io/badge/-Architecture-003087?style=flat-square)](ARCHITECTURE.md)
[![Deployment](https://img.shields.io/badge/-Deployment-46E3B7?style=flat-square)](DEPLOYMENT.md)
[![API reference](https://img.shields.io/badge/-API_reference-0f766e?style=flat-square)](API.md)

</div>

---

## Reading paths

| If you want to | Read, in order |
| --- | --- |
| Run it locally in five minutes | [Quick start](QUICKSTART.md) |
| Set up a development environment | [Installation](INSTALLATION.md) -> [Configuration](CONFIGURATION.md) -> [Troubleshooting](TROUBLESHOOTING.md) |
| Deploy it | [Deployment](DEPLOYMENT.md) -> [Configuration](CONFIGURATION.md) -> [Security](SECURITY.md) |
| Understand the system | [Architecture](ARCHITECTURE.md) -> [Agents](AGENTS.md) -> [Supply Agents](SUPPLY_AGENTS.md) -> [PayPal integration](PAYPAL.md) |
| Integrate with the API | [API reference](API.md) -> [API portal and SDKs](APIMATIC.md) -> [Security](SECURITY.md) |
| Change the code | [Contributing](CONTRIBUTING.md) -> [Testing](TESTING.md) -> [Data](DATA.md) |

---

## All documents

### Getting started

| Document | Contents |
| --- | --- |
| [Quick start](QUICKSTART.md) | Running in five minutes with Docker, Make or PowerShell; first things to try |
| [Installation](INSTALLATION.md) | Prerequisites, platform notes, manual setup without Make, verification |
| [Configuration](CONFIGURATION.md) | Every environment variable, grouped, with defaults and how to enable each integration |
| [Deployment](DEPLOYMENT.md) | Docker Compose, Render Blueprint, other container hosts, migrations, production checklist |
| [Troubleshooting](TROUBLESHOOTING.md) | Symptom, cause and fix for setup, database, auth, frontend, agents and Docker |

### System design

| Document | Contents |
| --- | --- |
| [Architecture](ARCHITECTURE.md) | The modular monolith, request lifecycle, layering rules, data model, events, realtime, observability |
| [Agents](AGENTS.md) | The three LangGraph workflows, the 49-tool registry, prompts, structured output, LLM failure handling |
| [Agent memory](MEMORY.md) | Long-term memory on pgvector, recall, tenant isolation |
| [Security](SECURITY.md) | Authentication, tokens, RBAC, tenant isolation, approval gates, auditing, redaction |
| [Data](DATA.md) | Table groups, migrations, portable column types and the deterministic demo dataset |

### Domains

| Document | Contents |
| --- | --- |
| [Supply Agents](SUPPLY_AGENTS.md) | Inventory intelligence, the financial engine, supplier agents, signed protocol, negotiation, three-way match, reconciliation |
| [Supply Intelligence](SUPPLY_INTELLIGENCE.md) | Channel3 product discovery, ranking, comparison, recommendations and their lifecycle, approved purchases |
| [PayPal integration](PAYPAL.md) | Modes, every PayPal API used, customer checkout, webhooks, approval gates, sandbox setup, MCP |
| [Integrations](INTEGRATIONS.md) | Channel3, AG Grid, AG Studio, Bryntum, APIMatic, Render, Redis, Elasticsearch, Kernel, Zapier, Postman |
| [Automation](AUTOMATION.md) | The transactional outbox, the relay, the n8n workflows and signed callbacks |

### Building on it

| Document | Contents |
| --- | --- |
| [API reference](API.md) | All endpoints with their permissions, the response envelope, error codes, the permission matrix |
| [API portal and SDKs](APIMATIC.md) | Exporting the OpenAPI spec, building the APIMatic portal, Python and TypeScript SDKs |
| [Testing](TESTING.md) | Suite layout, fixtures, what each suite proves, writing new tests |
| [Contributing](CONTRIBUTING.md) | Project rules, where code goes, backend and frontend conventions, adding a feature end to end |

### Diagrams

| File | Shows |
| --- | --- |
| [`assets/architecture.svg`](assets/architecture.svg) | System architecture: clients, request pipeline, services, agent layer, approval gate, data, external services. Regenerate with `python scripts/build_architecture_diagram.py` |
| [`assets/architecture.png`](assets/architecture.png) | The same diagram as a 3200 x 2280 PNG |
| [`assets/money-loop.svg`](assets/money-loop.svg) | The PayPal money loop: customer payment to reconciled supplier payment |

Mermaid diagrams (request lifecycle, procurement state machine, event flow, deployment topology) are inline in
[Architecture](ARCHITECTURE.md), [Supply Agents](SUPPLY_AGENTS.md), [Automation](AUTOMATION.md) and
[Deployment](DEPLOYMENT.md).

---

## Conventions

* Commands run from the repository root unless a `cd` is shown.
* Code references link to the file, for example [`services/supply/policy.py`](../backend/app/services/supply/policy.py).
* API paths are shown without the `/api/v1` prefix where the context makes it clear.
* Amounts are US dollars from the seeded demo merchant (seed `20240917`) unless stated otherwise.
* Every count in these documents (200 API operations, 62 tables, 49 agent tools, 51 permissions, 65 pages) is
  taken from the code: the OpenAPI export, the SQLAlchemy models, the tool registry, the permission enum and the
  Next.js page files.

---

<div align="center">

[Project README](../README.md) | [Quick start](QUICKSTART.md) | [Architecture](ARCHITECTURE.md) | [API reference](API.md)

</div>
