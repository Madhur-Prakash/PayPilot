---
title: Authentication
---

PayPilot uses short-lived bearer tokens.

```bash
curl -s -X POST "$BASE/api/v1/auth/login" \
  -H 'Content-Type: application/json' \
  -d '{"email": "owner@juniperoak.com", "password": "Autopilot@2024"}'
```

The response carries `data.tokens.access_token`. Send it on every call:

```bash
curl -s "$BASE/api/v1/supply/demand" -H "Authorization: Bearer $TOKEN"
```

* Access tokens expire after 30 minutes; `POST /api/v1/auth/refresh` (HttpOnly
  refresh cookie) issues a new one.
* Every response is an envelope: `{"success": true, "data": ..., "meta": {...}}`, or
  `{"success": false, "error": {"code", "message", "details"}}`.
* Everything is scoped to the caller's merchant. Permissions follow the role:

| Role | Can |
| --- | --- |
| Owner | everything, including users |
| Admin | approve purchases and payments, execute |
| Analyst | source and negotiate - **cannot** approve or pay (403) |
| Staff | receive goods, inventory actions |
| Viewer | read only |
