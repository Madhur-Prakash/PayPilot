<div align="center">

# Documentation

**PayPilot** · Team PayFlux

[![Back to project](https://img.shields.io/badge/-Back_to_project_README-475569?style=flat-square&logo=markdown&logoColor=white)](../README.md)
[![Installation](https://img.shields.io/badge/-Installation-16a34a?style=flat-square)](INSTALLATION.md)
[![Architecture](https://img.shields.io/badge/-Architecture-64748b?style=flat-square)](ARCHITECTURE.md)
[![Agents](https://img.shields.io/badge/-Agents-2563eb?style=flat-square)](AGENTS.md)
[![Agent memory](https://img.shields.io/badge/-Agent_memory-7c3aed?style=flat-square)](MEMORY.md)
[![Automation](https://img.shields.io/badge/-Automation-b45309?style=flat-square)](../n8n/README.md)
[![API](https://img.shields.io/badge/-API_reference-0f766e?style=flat-square)](API.md)

</div>

---

## Start here

New to the project? Read in this order.

| # | Document | Time | What you get |
| :--: | --- | :--: | --- |
| 0 | [**Project overview**](PROJECT_OVERVIEW.md) | 10 min | **Start here:** what it is, why PayPal is central, every sponsor tool and where it is used, key features, criteria mapped to evidence, what is verified |
| 1 | [Installation](INSTALLATION.md) | 10 min | A running local stack |
| 2 | [Demo script](DEMO.md) | 3 min | The signature scenario, end to end |
| 3 | [Hackathon notes](HACKATHON.md) | 5 min | What was built for the PayPal AI Hackathon, tools used, judge testing |
| 3b | [Devpost draft](DEVPOST.md) | 5 min | Ready-to-paste submission text, section by section |
| 3c | [Video script](VIDEO_SCRIPT.md) | 5 min | The 3-minute demo video, shot by shot, with narration, the numbers to expect and a recording checklist |
| 4 | [Supply Agents](SUPPLY_AGENTS.md) | 15 min | The agent-to-agent procurement network and its controls |
| 5 | [PayPal](PAYPAL.md) | 10 min | Every PayPal API used, modes, webhooks, sandbox setup |
| 5b | [Sponsor tools](SPONSORS.md) | 10 min | What each sponsor tool is used for, what is live vs a labelled fallback, how it was verified |
| 6 | [Architecture](ARCHITECTURE.md) | 15 min | Why it is built this way |
| 7 | [Agents](AGENTS.md) | 15 min | How the AI layer actually works |
| 8 | [Agent memory](MEMORY.md) | 10 min | What the agents remember (pgvector), and how tenants stay apart |

---

## By task

### I want to run it

| Document | |
| --- | --- |
| [Installation](INSTALLATION.md) | Prerequisites, platform notes, step-by-step, verification |
| [Configuration](CONFIGURATION.md) | Every environment variable, and how to wire each integration |
| [Troubleshooting](TROUBLESHOOTING.md) | Symptom, cause, fix |

### I want to deploy it

| Document | |
| --- | --- |
| [Deployment](DEPLOYMENT.md) | Docker Compose, managed Postgres, Supabase, cloud platforms, Render Blueprint |
| [Deployment: production checklist](DEPLOYMENT.md#production-checklist) | What to change before real traffic |
| [Security](SECURITY.md) | The threat model this implementation addresses |

### I want to understand it

| Document | |
| --- | --- |
| [Architecture](ARCHITECTURE.md) | Layering, the five rules, data model, observability |
| [Agents](AGENTS.md) | The seven agents, LangGraph wiring, the tool registry |
| [Agent memory](MEMORY.md) | Long-term memory on pgvector, tenant isolation |
| [Supply Agents](SUPPLY_AGENTS.md) | Inventory intelligence, supplier agents, signed protocol, negotiation, lifecycle |
| [Supply Intelligence](SUPPLY_INTELLIGENCE.md) | Channel3 product discovery, recommendations lifecycle, the seven Merchant OS agents, PayPal orders for approved purchases |
| [PayPal](PAYPAL.md) | Client, simulator, sync, webhooks, approval gates, Agent Toolkit evaluation |
| [Inventory automation](../n8n/README.md) | The outbox relay, the n8n workflows, and what triggers them |
| [Security](SECURITY.md) | Auth, RBAC, tenant isolation, approval gates, auditing |
| [Data](DATA.md) | How the demo dataset is generated and why it reproduces |

### I want to build on it

| Document | |
| --- | --- |
| [API reference](API.md) | Every endpoint, envelopes, error codes, permissions |
| [Contributing](CONTRIBUTING.md) | Conventions, and adding a feature end to end |
| [Testing](TESTING.md) | What is covered, how to run it, how to extend it |

### I want to demo it

| Document | |
| --- | --- |
| [Demo script](DEMO.md) | Five minutes, with the exact numbers and what to say |
| [Data](DATA.md#what-comes-out) | The figures the dataset produces |

---

## All documents

| Document | Summary |
| --- | --- |
| [INSTALLATION.md](INSTALLATION.md) | Get the stack running on macOS, Linux or Windows |
| [CONFIGURATION.md](CONFIGURATION.md) | Environment reference; Groq, Langfuse, Vapi, Supabase, embeddings |
| [DEPLOYMENT.md](DEPLOYMENT.md) | Containers, managed databases, cloud targets, hardening |
| [ARCHITECTURE.md](ARCHITECTURE.md) | System design, the rules it enforces, and the bugs tests caught |
| [AGENTS.md](AGENTS.md) | The agent system: graph, state, tools, prompts, failure handling |
| [SECURITY.md](SECURITY.md) | Authentication, authorization, isolation, approval, auditing |
| [DATA.md](DATA.md) | The deterministic demo dataset and its generator |
| [API.md](API.md) | Endpoint reference and the permission matrix |
| [TESTING.md](TESTING.md) | The 105-test suite, and how to add to it |
| [DEMO.md](DEMO.md) | The five-minute walkthrough |
| [TROUBLESHOOTING.md](TROUBLESHOOTING.md) | Common problems and their fixes |
| [CONTRIBUTING.md](CONTRIBUTING.md) | Working in this codebase |

---

## Conventions used in these docs

**Commands** assume the repository root unless a `cd` is shown.

```bash
make setup     # runs from the repo root
```

**Dollar amounts** are written `$9,840` in prose and rendered `$9,840` in the
product, using US digit grouping.

**Code references** link to the file:
[`services/analytics/service.py`](../backend/app/services/analytics/service.py).

**Callouts** are used sparingly:

> **Note.** Something worth knowing.

> **Warning.** Something that will bite you.

**Every figure quoted** in these documents was measured from the running system at
seed `20240917`, not estimated.

---

<div align="center">

[Project README](../README.md) · [Installation](INSTALLATION.md) ·
[Architecture](ARCHITECTURE.md) · [API](API.md) · [Demo](DEMO.md)

</div>
