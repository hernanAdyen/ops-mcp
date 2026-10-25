# Implementation MCP — Design (v0.1 draft)

Owner: project owner · Status: draft for review · Date: 2026-10-20

## 1. Goal

One MCP package that gives an Implementation Manager (IM) in Ops everything needed to scope, prototype, test and debug a merchant integration without leaving their AI client. It bundles **tools** (deterministic actions), **skills** (repeatable IM workflows written as SKILL.md) and **connector orchestration** (existing Gmail / Drive / Confluence / Slack connectors).

Non-goals (v0): writing to production systems, replacing Adyen's public Postman/SDK tooling, storing merchant secrets.

## 2. Decisions taken

| Topic | Decision |
|---|---|
| Language | TypeScript, official MCP SDK, zod schemas |
| Runtime | Local Docker container per IM (stdio via `docker run -i`, or HTTP on localhost) |
| Internal access | Container runs on the IM's laptop on VPN, so it can reach internal hosts and local ports. Cloud sessions cannot — the MCP is for local use |
| External data | Hybrid: server holds local/internal tools; skills orchestrate existing connectors (Gmail, Drive, Confluence, Slack) rather than re-implementing them |
| Safety | Read-only by default. Anything that sends, writes or deploys needs an explicit confirm step |

## 3. Architecture

```
AI client (Claude)
   │  MCP (stdio / localhost HTTP)
   ▼
implementation-mcp  (Docker, on IM laptop, VPN)
 ├─ module: checkoutlab   → spawns local Checkout app (Node), returns URL
 ├─ module: checkoutpost  → Adyen OpenAPI → generated tools / request runner
 ├─ module: investigate   → log search by PSP reference (internal API)
 ├─ module: localmain     → wraps the local-main deploy scripts
 ├─ module: proposal      → templates + doc assembly helpers
 └─ skills/               → SKILL.md workflows (proposal, im-investigator, …)
        │
        └─ orchestrate existing connectors: Gmail, Drive, Confluence, Slack, Gong*
```

Repo layout:

```
implementation-mcp/
  src/server.ts            # registers modules
  src/modules/<name>/      # one folder per feature, own tools + tests
  skills/<name>/SKILL.md   # IM workflows
  templates/               # solution-scope and proposal templates
  docker/Dockerfile, compose.yml
  config/adyen.example.env # credentials come from env, never committed
```

Each module is independently enable-able via config so a feature can ship before the others are ready.

## 4. Feature sets

### 4.1 CheckoutLab (local)
**What:** Start a local server hosting a CheckoutLab-style playground so an IM can prototype Adyen Web integrations quickly. Reference: [checkoutlab.dev Drop-in (advanced)](https://www.checkoutlab.dev/advance/dropin?view=preview) — a tool for building and testing Drop-in with the advanced flow, with editable API requests, Checkout configuration, custom CSS and shareable links.

**Tools:** `checkoutlab_start({component, flow, port, config})`, `checkoutlab_stop`, `checkoutlab_status`, `checkoutlab_set_config`.

**Approach:** Ship a small Express/Vite app inside the container: `/sessions` and `/payments` routes proxying to Adyen test endpoints with the IM's test API key, plus a front-end per component (Drop-in, Components, Sessions vs Advanced). Map the container port to the host.

**Open questions:**
- Is CheckoutLab open source or owned internally? If internal, we should vendor or depend on it instead of rebuilding. (The public page gives no repo or licence info.)
- Which components are in scope for v1 — Drop-in only, or also individual Components and Web SDK versions?

### 4.2 CheckoutProposal (solution proposal generator)
**What:** Produce an integration solution scope plus a matching technical solution from Gong calls, email threads, Adyen docs and previous proposals in the shared Drive folder.

**Pipeline (skill-driven):**
1. **Collect** — Gong transcript(s) (see risk below), Gmail threads for the merchant, prior proposals from the shared Drive folder, Confluence/Docs pages.
2. **Extract** — structured requirements: business model, regions, payment methods, platforms, volumes, PCI constraints, timeline, open questions. Each item cites its source (call + timestamp, email, doc).
3. **Draft scope** — fill the integration solution scope template; flag anything missing as *Needs confirmation*, never invent.
4. **Technical solution** — map requirements to Adyen products/integration type (Sessions vs Advanced, Drop-in vs Components, webhooks, tokenization, etc.) using current Adyen docs, with links.
5. **Reuse** — pull wording/architecture patterns from similar past proposals; show which ones were used.
6. **Review** — IM edits; output as a Google/Docs-type doc.

**Tools in server:** `proposal_template_get`, `proposal_requirements_validate` (checks completeness against the template), `proposal_find_similar` (search over indexed previous proposals).

**Open questions / risks:**
- **Gong access.** No Gong connector is attached to this workspace. Options: Gong API from the local container (needs API key + approval), or IM pastes/exports transcripts. Need to confirm what Adyen's InfoSec permits for customer call content.
- Where does the shared Drive folder live and what is the template? Needed to build the template and the similarity index.
- Customer data handling: transcripts and emails contain merchant information; define retention (nothing persisted by default).

### 4.3 CheckoutPost (API testing)
**What:** Fast API testing against Adyen endpoints.

**Options compared:**

| Option | Pros | Cons |
|---|---|---|
| A. Postman MCP + preloaded [Adyen Postman collections](https://www.adyen.com/knowledge-hub/adyen-postman-collections) | Familiar, no maintenance of requests | Needs Postman account/API key; collection drift; less control over safety |
| B. Own client generated from Adyen OpenAPI specs (see [Adyen/adyen-openapi](https://developer.adyen.com/), [OpenAPI write-up](https://medium.com/adyen/improving-the-developer-experience-with-openapi-specification-f90fbf8077cf)) | Always matches the spec, schema validation, test-env guard, tools generated automatically | We own it; auth and example payloads need curation |

**Recommendation:** B as the engine, with Postman collections kept as a source of example payloads. Tools: `api_list_endpoints`, `api_describe(endpoint)`, `api_call(endpoint, body, env=test)`, `api_example(endpoint)`. Hard guard: **TEST environment only** unless explicitly overridden by config; secrets from env, redacted in output.

### 4.4 CheckoutInvestigate (log search by PSP reference)
**What:** Given a PSP reference (and optionally merchant account/time window), return the relevant log lines and a short timeline of the payment.

**Tools:** `logs_by_psp_reference({psp, from?, to?})`, `payment_timeline(psp)`.

**Blocking unknown:** which log system and API (Kibana/OpenSearch/Splunk/other) and how IMs authenticate. Until known, define the tool interface and ship it behind an adapter so the backend can be dropped in. Must respect log access policy and PII redaction (card data, shopper PII) in output.

### 4.5 Local Main
**What:** Skills that walk an IM through standing up an instance of Adyen `main` to test end to end.

**Approach:** Skill + thin tools wrapping existing internal scripts/containers (`localmain_status`, `localmain_up`, `localmain_down`, `localmain_logs`). Prereq checks (Docker, VPN, internal GitLab access, credentials) run first.

**Open questions:** where the canonical local-main docs/scripts live (internal GitLab / Confluence), resource requirements on a laptop, and whether Docker-in-Docker is acceptable (otherwise the MCP calls the host Docker socket or the IM runs a script that the skill guides).

### 4.6 IM Investigator
**What:** A skill that investigates questions the way an IM would: clarify the merchant/integration, check docs first, reproduce with CheckoutPost, trace with CheckoutInvestigate, compare against Local Main if code-level behaviour is in question, and answer with evidence.

**Investigation protocol (draft):**
1. Restate the question and what is known (merchant, env, PSP refs, timestamps).
2. Search public docs, Confluence, and YouTrack (public connector) for known behaviour.
3. Pull payment evidence (logs, timeline) when a PSP reference exists.
4. Reproduce in test with `api_call` or CheckoutLab.
5. Conclude: finding, confidence, evidence links, recommended next step, and what remains unknown.

It is the orchestrator: it calls the other five features rather than duplicating them.

## 5. Skills list (v0)

| Skill | Purpose |
|---|---|
| `im-investigator` | Section 4.6 |
| `solution-proposal` | Section 4.2 |
| `quick-demo` | Spin up CheckoutLab with a merchant-like config |
| `api-test` | Guided API testing with CheckoutPost |
| `psp-trace` | Log search workflow |
| `local-main` | Local deployment workflow |

Follow the Adyen skill conventions (`adyen-domain-job` naming, read-only default, approval gates, eval cases).

## 6. Security and compliance

- Credentials from environment/secret store only; never in tool output or committed config.
- TEST environment default; live requires explicit config plus per-call confirmation.
- Redact PAN, shopper PII and API keys in logs and tool responses.
- No persistent storage of Gong/email content; proposals are written only to the destination the IM chooses.
- Cloud sessions cannot reach internal systems (VPN), so the MCP is positioned as local-only.

## 7. Phasing

| Phase | Deliverable | Depends on |
|---|---|---|
| 0 | Repo skeleton, Dockerfile, module registry, CI | — |
| 1 | CheckoutPost (OpenAPI → tools) + `api-test` skill | Adyen OpenAPI specs |
| 2 | CheckoutLab local server + `quick-demo` skill | Decision on CheckoutLab source |
| 3 | CheckoutProposal skill + templates (connector-based) | Template + Drive folder, Gong decision |
| 4 | CheckoutInvestigate adapter | Log backend + auth |
| 5 | Local Main skill/tools | Internal deploy docs |
| 6 | IM Investigator orchestrator + evals | Phases 1–5 |

Rationale: 1 and 2 need no internal access, so they prove the architecture early; 3 delivers the most IM time saved; 4–5 need internal answers.

## 8. Open questions (need answers to proceed)

1. Is CheckoutLab open source / internal? Which components for v1?
2. Gong: API access allowed for this use? Or manual transcript input?
3. Location of the shared Drive proposals folder and the scope/proposal template.
4. Log system, API and auth for PSP-reference search.
5. Where the Local Main scripts/docs live and the expected laptop footprint.
6. Distribution: Docker image in an internal registry? Who maintains it?
7. Security review: does an MCP that reads customer call content and logs need sign-off first?
