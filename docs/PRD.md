# PRODUCT REQUIREMENTS DOCUMENT — ReconLedger

**A passive reconnaissance workbench for structured, repeatable, and citable OSINT**
Portfolio project | Information Systems & Technology - Cybersecurity

| Document | Value |
|---|---|
| Prepared for | Adriel Uribe De La Cruz |
| Version | 1.1 — implementation-readiness revision |
| Date | September 6, 2026 |
| Status | Approved for implementation |
| Release strategy | Local-first phased MVP |
| Implementation shape | React + TypeScript client; async FastAPI API; SQLite |

**Authorized use only:** ReconLedger is designed only for domains, IP space, and organizations the user owns or has written authorization to assess. The application queries approved public or third-party data providers and never communicates directly with the assessed target.

Requirements validated through a clarifying-question cycle. Provider assumptions were checked against official documentation available on September 6, 2026. Version 1.1 incorporates an implementation-readiness review that closed four internal contradictions, added a client-side network boundary, corrected provider assumptions, and made several build-time constraints explicit. Appendix C lists every change.

## Document map

Executive summary · 1. Product definition and boundaries · 2. Users and primary workflow · 3. Discovery decisions and product principles · 4. Scope and release plan · 5. User experience requirements · 6. Functional and data requirements · 7. Technical architecture · 8. Safety, security, and privacy requirements · 9. Non-functional requirements · 10. Testing and definition of done · 11. Risks and mitigations · 12. Ranked roadmap and engineering advice · 13. References · Appendix A. Requirements discovery record · Appendix B. Implementation AI handoff protocol · Appendix C. Revision history (version 1.1)

---

## Executive summary

ReconLedger is a local-first web application that turns passive reconnaissance into a guided, auditable workflow. Passive reconnaissance means collecting information from public and third-party indexes without sending traffic to the assessed target. The product serves students and junior analysts who understand reconnaissance concepts but should not need to memorize many command-line tools or manually reconcile inconsistent output.

The approved MVP uses no-key sources: RDAP for registration data; DNS-over-HTTPS through a public recursive resolver; crt.sh for Certificate Transparency; RIPEstat for ASN and netblock context; Wayback Machine and Common Crawl indexes for historical URLs; and technology inference derived only from archived or already collected evidence. Keyed integrations — GitHub, Shodan, Censys, public email/personnel search, and Have I Been Pwned — follow in release 1.1. A missing key or provider failure never prevents other collectors from completing.

A React/TypeScript dashboard provides strong interaction design, while async FastAPI and httpx fit a workload dominated by parallel outbound API calls. SQLite stores jobs, evidence, scope attestations, and response cache entries. A SQLite-backed worker makes status durable without adding Redis to a student portfolio project. Server-Sent Events (SSE) stream per-source progress, with polling as a fallback. Every finding retains source attribution, retrieval time, and a safe raw-evidence view so exported Markdown and JSON can be cited and reproduced.

**Release outcome:** A reviewer can launch an authorized passive job, watch every collector progress independently, inspect and search evidence, compare two runs, and export a report or subdomain list without the application ever contacting the target directly.

## 1. Product definition and boundaries

### 1.1 Context

The project covers Phase 1, Reconnaissance, in the EC-Council five-phase penetration-testing model. It is cross-mapped to PTES Intelligence Gathering and the Discovery phase described by NIST SP 800-115. These frameworks provide the learning context; this product deliberately implements only passive collection from external data providers. NIST describes discovery as the phase in which information about the target environment is collected and analyzed, while the product's safety policy narrows the permitted techniques further to third-party sources only (R1).

### 1.2 Problem statement

Passive reconnaissance is fragmented across provider websites, APIs, inconsistent schemas, and different authentication models. Beginners often lose the method, evidence trail, and scope record while switching tools. Existing utilities also make it too easy to mix passive collection with direct probing. ReconLedger solves the workflow problem: one authorization gate, one target, visible source readiness, normalized findings, evidence provenance, and reusable exports.

### 1.3 Product vision

Make authorized passive reconnaissance as repeatable as running a test suite and as citable as preparing a research brief.

### 1.4 Goals

- Guide a new analyst from target entry to a defensible reconnaissance report without requiring CLI memorization.
- Enforce a passive-only network boundary through architecture, not only through user-facing policy text.
- Normalize evidence from heterogeneous providers while preserving the original source, retrieval time, and safe raw response.
- Complete useful jobs even when a provider is unavailable, rate-limited, or missing credentials.
- Make repeat runs inexpensive through provider-aware caching and make changes visible through evidence-aware diffs.
- Demonstrate portfolio-level full-stack engineering, accessibility, testing, and security design.

### 1.5 Success measures

| Measure | MVP target | How measured |
|---|---|---|
| Safety | Zero direct connections to the assessed target | Automated transport allowlist tests, a process-wide socket block in CI, and integration logs |
| Client isolation | No browser request from the dashboard reaches the assessed target | Playwright network assertions over every request the client issues |
| Graceful completion | Jobs finish with warnings when at least one selected collector succeeds | Job and collector state assertions |
| Evidence quality | 100% of findings include source, retrieval time, and raw evidence | Schema validation and export tests |
| Cache value | A same-target repeat within TTL makes no duplicate provider calls | Mock transport call counts |
| Usability | A first-time user can launch a valid job without documentation | Two unmoderated testers complete the defined launch task without help; failures are logged in the README |
| Accessibility | No critical automated WCAG 2.2 AA violations in core flows | axe/Playwright checks plus keyboard review |

### 1.6 Non-goals and hard boundary

**Hard scope rule:** The application must never send HTTP, DNS, TLS, ICMP, SMTP, or other traffic to the assessed target or its authoritative infrastructure. All network traffic terminates at an allowlisted third-party provider.

- Port scanning, service probing, host discovery, ping sweeps, or banner grabbing.
- Directory, endpoint, DNS, subdomain, or DKIM-selector brute forcing.
- Credential validation, password testing, vulnerability scanning, exploit validation, or exploitation.
- Sending scan jobs to provider scan-submission APIs. Shodan and Censys are search-only integrations over their existing indexes.
- Any client-side behavior that causes the user browser to contact the assessed target, including clickable original-target links, favicons, previews, and speculative connections.
- Automated phishing, contact enrichment for marketing, individual risk scoring, or collection of private/non-public records.
- A production multi-tenant SaaS, team permissions, SSO, or cloud deployment in the portfolio MVP.

## 2. Users and primary workflow

### 2.1 Primary users

| Persona | Need | Design implication |
|---|---|---|
| Cybersecurity student | Learn a disciplined Phase 1 process and explain the evidence | Teach concepts in context; never hide source provenance |
| Junior analyst | Collect repeatable scope-bound intelligence quickly | Fast defaults, reusable jobs, filters, and exports |
| Instructor or reviewer | Evaluate method, safety, and technical quality | Visible scope record, source states, raw evidence, tests, and legal boundary |

### 2.2 Primary workflow

1. Read the three-sentence first-run explanation of passive reconnaissance and its limits.
2. Enter a domain, IP address, or CIDR block and resolve any inline validation error. Organization input is recognized and explained but is not assessable until release 1.1.
3. Review source toggles, readiness, credential requirements, and target applicability.
4. Confirm ownership or written authorization and optionally record a scope note.
5. Launch the job and watch each collector move through queued, running, done, failed, skipped-no-key, or not-applicable states.
6. Inspect grouped findings, search evidence, expand raw responses, and copy or filter the subdomain table.
7. Reopen history, compare a newer run against an earlier run, and export Markdown, JSON, or subdomain CSV.

### 2.3 Important edge cases

- A syntactically valid target is unsupported by one or more selected collectors.
- A provider returns no records; this is an explicit empty result, not an error.
- A credential is absent, invalid, or lacks a required subscription/verified-domain entitlement.
- A provider returns 429 with Retry-After, times out, changes schema, or returns malformed data.
- A repeat job is served partly or entirely from cache.
- A diff compares jobs with different selected-source sets or incomplete collectors.
- An archived URL redirects to the live target; the redirect must be recorded and not followed.
- An organization name is entered while no installed collector supports that target type.
- A user attempts to open an original-target URL that appears in archive evidence.

## 3. Discovery decisions and product principles

### 3.1 Decisions confirmed with the product owner

| Decision | Selected direction | Reason |
|---|---|---|
| Release boundary | Phased MVP | No-key sources deliver a complete learning workflow without paid-account blockers |
| Client architecture | React + TypeScript | The dashboard has enough live state, filtering, and evidence interaction to justify a dedicated client |
| Deployment model | Local-first, single-user | Keeps the portfolio project focused on recon workflow instead of identity and tenancy |
| AI handoff | PRD plus separate ready-to-paste prompt | The implementation AI receives both the requirements baseline and an explicit clarification protocol |

### 3.2 Product principles

- Safety is structural. A policy banner is not sufficient; outbound destinations are centrally allowlisted and testable.
- Partial results are valid. The user should know exactly which source failed without losing successful evidence.
- Unknown is not absent. An unqueried or failed source cannot justify a 'removed' diff result or a negative security conclusion.
- Evidence precedes interpretation. Posture notes and technology guesses always link back to collected evidence and state confidence.
- The interface teaches the workflow. Source descriptions, empty states, and export methodology should help the user explain what happened.
- Local-first does not mean careless. Inputs, archived content, logs, CSV, Markdown, and secrets are handled as untrusted data.

## 4. Scope and release plan

### 4.1 MVP — complete passive workflow without paid keys

- Domain, IP, and CIDR input classification and canonicalization. Organization input is classified and explained, with launch disabled and a pointer to release 1.1.
- Authorization attestation and saved scope note.
- RDAP, DNS-over-HTTPS, crt.sh, RIPEstat, Wayback CDX, and Common Crawl index collectors.
- Technology inference from archived or already collected evidence only.
- Persistent background jobs, per-source progress, cache, history, diff, global search, subdomain workspace, and all three exports.
- Responsive accessible light/dark dashboard, documentation, screenshots, migrations, and automated tests.

### 4.2 Release 1.1 — credentialed and privacy-sensitive integrations

- GitHub public code search using a token and query limits appropriate to the current API.
- Shodan indexed host/service search only; no scan-submission endpoint may be implemented.
- Censys indexed host search only; no active discovery or target connection.
- Public professional email/personnel footprint through a terms-compliant search provider, with source links and data minimization.
- Have I Been Pwned domain summary only after the domain is verified for the subscriber account; reports show aggregate breach exposure by default.
- Organization target support, enabled by the organization-capable sources introduced in this release.

### 4.3 Provider matrix

| Collector | Release | Target | Credential | Normalized output |
|---|---|---|---|---|
| RDAP | MVP | Domain, IP | None | Registrar/RIR, dates, nameservers, entities/organization, status |
| Public DNS over HTTPS | MVP | Domain | None | A, AAAA, CNAME, MX, NS, SOA, TXT, SPF, DMARC, observed DKIM |
| crt.sh | MVP | Domain | None | Certificate names, issuers, not-before/not-after, derived subdomains; extended timeout budget |
| RIPEstat | MVP | IP, CIDR, derived IP | None | Origin ASN, prefix, holder, routing and registry context |
| Wayback CDX | MVP | Domain | None | Archived URLs, timestamps, status/mime metadata, parameters |
| Common Crawl | MVP | Domain | None | Indexed URLs and capture metadata from the configured recent crawl collections; bounded archived content samples |
| Technology inference | MVP | Domain | None | Evidence-backed technology indicators and confidence |
| GitHub code search | 1.1 | Domain, org | Token | Public references, repository/file URL, matched infrastructure indicator |
| Shodan | 1.1 | IP, CIDR | API key | Indexed hosts, services, banners, provider observation time |
| Censys | 1.1 | IP, CIDR | API token | Indexed hosts, services, certificates, provider observation time |
| Public email/personnel | 1.1 | Domain, org | Provider key | Public professional identity/contact evidence with URL |
| HIBP domain | 1.1 | Domain | Key + verified domain | Aggregate affected aliases and breach names/dates/data classes |

### 4.4 Target-type behavior

| Input type | Validation and canonical form | Collector behavior |
|---|---|---|
| Domain | IDNA/punycode, lowercase, no scheme/path/port, registrable-domain check | All domain-capable sources; CT names remain within the registrable domain |
| IPv4/IPv6 | Python ipaddress canonical text; reject private/reserved unless developer test mode | RDAP and RIPEstat in MVP; keyed index sources later |
| CIDR | Strict network address; MVP limits IPv4 to /16 or narrower and IPv6 to /48 or narrower | Prefix-aware provider queries only; never enumerate or probe every address |
| Organization | 2-120 visible characters, trimmed and normalized for display | No MVP collector accepts organization targets. The MVP classifies the input, disables launch, and explains that organization search ships in release 1.1 with the organization-capable keyed sources. |

**DKIM constraint:** SPF can be parsed from apex TXT and DMARC from the deterministic `_dmarc` label. DKIM has no universal selector-discovery query. ReconLedger may parse selectors observed in archived headers or other collected evidence, but it must never guess or brute-force selectors. When none are observed, the UI reports "Unknown — no passive selector evidence" rather than "DKIM missing."

## 5. User experience requirements

**UX-01 — First-run explanation.** Show a three-sentence panel before the first job that defines passive recon, states what the tool will and will not do, and explains valid input.
- The text is visible without opening help and can be dismissed and restored from Help.
- The panel explicitly states that the app contacts third-party providers only.
- The panel includes examples: `example.com`, `203.0.113.0/24`, and `Example Corp`.

**UX-02 — Single target input.** Provide one primary input with live classification, examples, and actionable inline validation.
- Valid inputs are classified as domain, IP, CIDR, or organization before launch.
- URLs, credentials, wildcard domains, paths, and malformed values show a clear error and do not enable launch.
- The normalized target is previewed; changes are not silently made after the user confirms launch.
- An organization input is classified and acknowledged, launch stays disabled, and the message names release 1.1 rather than reporting a validation error.

**UX-03 — Authorization gate.** Require an unchecked ownership/written-permission checkbox and offer a scope note before every job.
- The launch button stays disabled until the checkbox is selected.
- The exact attestation text, timestamp, normalized target, and optional scope note are saved with the job.
- The attestation and scope note appear in Markdown and JSON exports.

**UX-04 — Source readiness.** List source toggles before launch with description, target applicability, readiness, credential status, and official key link.
- No-key, ready, missing-key, unavailable, and not-applicable states use both text and iconography, not color alone.
- A user may select a missing-key source; launch explains that it will be skipped rather than failing the job.
- Provider links open in a new tab with safe `rel` attributes.

**UX-05 — Per-collector progress.** Display progress for every selected source rather than a single opaque spinner.
- States are queued, running, done, failed, skipped-no-key, not-applicable, and done-cached.
- Each row shows started/finished times, finding count, and a plain-English reason for non-success.
- SSE updates are announced politely to assistive technology without repeatedly stealing focus.
- If SSE disconnects, polling keeps the page current and the UI clearly indicates reconnection.

**UX-06 — Evidence-oriented results.** Group findings into Network Footprint, Technology Stack, Human Layer, and Leaked Data.
- Every finding shows source, retrieval timestamp, summary, evidence URL, and a collapsed raw-evidence control.
- Raw JSON/text renders as inert text; archived HTML is never executed in the browser.
- Posture and inference findings show confidence and link to supporting evidence.
- Empty categories explain whether no findings were returned, sources were skipped, or the category was not applicable.

**UX-07 — Subdomain workspace.** Provide a sortable, filterable, keyboard-accessible subdomain table suitable for Phase 2 handoff.
- Columns include subdomain, source count, sources, first/last evidence date where available, wildcard flag, and in-scope status.
- Rows are normalized, deduplicated, and restricted to the assessed registrable domain.
- Copy selected, copy filtered, and CSV download provide clear success/failure feedback.
- Sorting and filters remain usable at tablet width without horizontal information loss.

**UX-08 — Search and filters.** Support global search across normalized summaries, values, source names, evidence URLs, and safe raw evidence.
- Search is debounced, case-insensitive, and combines with category/source/status filters.
- The result count and active filters remain visible, and Clear all restores the unfiltered job.
- No-results copy distinguishes 'no findings in the job' from 'no findings match these filters.'

**UX-09 — History and diff.** Allow any past job to be reopened and two comparable jobs on the same canonical target to be diffed.
- History shows target, target type, completion state, time, selected sources, warning count, and scope note preview.
- Diff labels evidence as added, removed, changed, or unchanged using stable finding fingerprints.
- If a source did not complete in both jobs, its potential removals are labeled indeterminate, never removed.
- Jobs with different canonical targets cannot be compared.

**UX-10 — Deliberate interface states.** Design explicit initial, loading, empty, partial-success, fatal-error, offline, and provider-rate-limit states.
- Every state explains what happened and the next safe action.
- Retry actions operate at the collector level when possible and preserve completed evidence.
- No state relies on indefinite animation; elapsed time and last update are visible for long-running work.

**UX-11 — Theme, responsiveness, and accessibility.** Meet WCAG 2.2 AA for core flows and support light/dark themes down to a 768-pixel tablet viewport.
- All interactive elements are keyboard reachable with visible focus, logical order, and descriptive accessible names.
- Contrast, status semantics, error association, table headers, dialogs, and disclosure controls pass automated and manual review.
- Theme honors `prefers-color-scheme` on first visit and persists an explicit choice.
- Reduced-motion preferences disable non-essential transitions.

**UX-12 — No client-originated target traffic.** The dashboard must never cause the user browser to contact the assessed target. The passive-only promise covers the whole product, not only the API.
- Original-target URLs from archive or certificate evidence render as inert, copyable text; the only clickable link is the archive replay or provider evidence URL.
- No favicon, image, iframe, media, link preview, prefetch, preconnect, or DNS-prefetch may reference a target host.
- External links open with `rel="noopener noreferrer"` under a document-level no-referrer policy, so provider requests never leak the assessed target in a Referer header.
- A Playwright test asserts that no request issued by the client resolves to the assessed target or its recorded addresses.

## 6. Functional and data requirements

**FR-01 — Job creation and orchestration.** Create a persistent job only after input, source selection, and authorization validation succeeds.
- `POST /api/jobs` returns 202 with a job identifier and initial per-collector states.
- A durable SQLite queue claims queued work transactionally and prevents duplicate execution.
- On restart, abandoned running collector records become interrupted and the job is safely resumed or completed with warnings according to idempotency rules.
- Global and per-source concurrency limits prevent accidental provider overload.

**FR-02 — Collector plug-in contract.** Each data source is an isolated module implementing the same typed contract.
- Required metadata: name, display name, supported target types, categories, required credentials, provider hosts, key-help URL, rate policy, timeout, and cache policy.
- `run(context)` returns normalized Finding records and provider-call metadata or raises a typed collector error.
- Adding a collector requires registration through discovery/configuration, not modifications to orchestration logic.
- Collectors receive the centralized outbound client and cannot instantiate unrestricted network clients.

**FR-03 — Outbound client policy.** Route all network activity through one policy-enforcing httpx transport.
- The transport allows HTTPS requests only to collector-declared provider hosts or validated RDAP registry hosts from an approved bootstrap list.
- Redirects are disabled by default; any allowed provider redirect is revalidated hop by hop.
- Resolved destination IPs in loopback, private, link-local, multicast, or metadata ranges are blocked unless they belong to a fixed local test transport.
- The assessed target and its resolved addresses are always denied as destinations.
- The target deny-list is populated before any collector is claimed. A pre-job resolution step resolves the target through the approved DoH resolver, records the addresses on the job, and seeds the deny-list; addresses discovered later in the job are added immediately. No collector runs while the deny-list is unpopulated.
- Every outbound request carries an identifying User-Agent naming the application, version, and repository URL, as expected by the free community providers this product depends on.

**FR-04 — Rate limiting and retry.** Apply independent source policies with bounded exponential backoff and full jitter.
- 429 responses honor a valid Retry-After value within the collector time budget.
- Only safe idempotent reads retry; authentication, validation, and most 4xx failures do not.
- The default is three attempts, 0.5-second base delay, 8-second cap, and a configurable per-collector total budget.
- Rate-limit decisions are visible in collector diagnostics without exposing secrets.

**FR-05 — Response cache.** Cache provider responses and normalized results by collector, collector schema version, normalized target, request variant, and credential scope where relevant.
- Fresh cache entries eliminate outbound calls and produce a done-cached state.
- TTL defaults are provider-aware: DNS follows bounded record TTL; RDAP/RIPEstat/CT 24 hours; Wayback 12 hours; Common Crawl 7 days; keyed sources configurable.
- Negative empty results may be cached briefly; authentication failures and malformed responses are not cached as success.
- The user may force refresh, but the action still obeys provider rate limits.

**FR-06 — Finding normalization and provenance.** Store each observation as a typed Finding with stable identity and evidence provenance.
- Required fields: id, job_id, collector, category, kind, title, summary, normalized_value, raw_evidence, source_url, provider_observed_at when available, retrieved_at, confidence, and fingerprint.
- `fingerprint` is generated from collector, kind, and a canonical identity key; mutable attributes remain outside the identity key so they can be marked changed.
- Secrets, authorization headers, cookies, and unrelated provider metadata are removed before raw evidence is persisted.
- All timestamps are stored as UTC ISO 8601 and displayed in the user's local time with UTC available.

**FR-07 — DNS and mail posture.** Collect explicit record types through a public DNS-over-HTTPS resolver and create informational mail-posture notes.
- Query A, AAAA, CNAME, MX, NS, SOA, TXT, and `_dmarc` TXT separately; do not use ANY as a substitute.
- Parse SPF mechanisms/modifiers and DMARC tags, retaining the original record and warnings for malformed or multiple policy records.
- Parse DKIM only for selectors observed in already collected passive evidence.
- Notes use cautious language such as "policy not observed through this resolver" and never claim a vulnerability or guaranteed deliverability outcome.
- The resolver is configurable. A primary and a secondary allowlisted DoH provider are supported so a provider outage does not fail the collector; when both are queried, agreement or disagreement between resolvers is itself recorded as evidence.

**FR-08 — Certificate Transparency.** Query crt.sh for matching certificates and derive in-scope names without contacting certificate endpoints.
- Normalize case, trailing dots, wildcard prefixes, IDNA, and newline-separated name values before deduplication.
- Exclude names outside the canonical registrable domain and flag wildcard evidence separately.
- Retain certificate identifier, issuer, not-before, not-after, and crt.sh evidence URL where present.
- crt.sh schema/availability failures produce a provider warning and do not fail the job.

**FR-09 — Archive collection and parameter extraction.** Use Wayback and Common Crawl indexes to identify historical URLs and bounded archived evidence.
- Normalize URLs, remove fragments, preserve meaningful query keys, deduplicate by canonical URL, and identify endpoint/file extension patterns.
- Default collection caps are 5,000 index rows per provider, 20 representative archived documents, and 5 MB total archived content per job.
- Archived content fetches target only archive/CDN hosts, never the original URL, and never follow a redirect to the live target.
- Stored snippets are size-limited and treated as untrusted text.
- Common Crawl exposes many separate crawl collections rather than one index. The collector queries a configured number of the most recent collections, defaulting to three, and stores the collection identifier with every finding.

**FR-10 — Technology inference.** Infer possible technologies only from normalized passive evidence.
- Allowed signals include archived response headers/HTML/meta tags, URL paths/extensions, certificate-name patterns, DNS/MX/NS provider patterns, and public indexed banners in release 1.1.
- Each inference includes rule identifier, technology label, confidence (low/medium/high), supporting finding IDs, and an explanation.
- No inference rule triggers a live verification request.
- The UI distinguishes observed facts from inferred technologies.

**FR-11 — Exports.** Generate deterministic Markdown, JSON, and subdomain CSV exports from persisted job evidence.
- Markdown includes target/scope, attestation time, methodology and limitations, source status, findings by category, evidence links, and generation time.
- JSON includes a documented schema version and all safe normalized/raw evidence.
- CSV uses UTF-8, a header row, normalized subdomains, and protection against spreadsheet formula injection.
- Exports are regenerated from the database and do not require provider calls.
- Markdown supports a summary and a full mode. Summary mode caps rows per category and points to the JSON export for the complete record, so a job holding thousands of findings still produces a readable report.

**FR-12 — History, deletion, and retention.** Persist jobs locally with user-controlled deletion and configurable retention.
- Default retention is 90 days for jobs/findings and provider-specific TTL for cache entries.
- Delete job requires confirmation and removes dependent collector runs/findings transactionally; shared cache entries remain until expiry or cache purge.
- A Clear cache action reports what will be deleted before confirmation.
- The README explains that email, personnel, and breach data may be sensitive even when publicly sourced.
- Retention and cache expiry are enforced by a sweep that runs at application startup and after every job reaches a terminal state. Retention is not left to a manual action.

### 6.1 Finding schema

| Field | Type | Purpose |
|---|---|---|
| id / job_id | UUID / UUID | Local evidence identity and parent job |
| collector | string | Stable source plug-in name |
| category | enum | network_footprint, technology_stack, human_layer, leaked_data |
| kind | string | Machine-readable finding subtype such as dns.mx or ct.subdomain |
| title / summary | string | Human-readable evidence statement |
| normalized_value | JSON | Typed canonical data used by filters, tables, exports, and diff |
| raw_evidence | JSON or text | Sanitized provider evidence fragment displayed inertly |
| source_url | HTTPS URL | Citable provider or capture reference |
| provider_observed_at | datetime? | Provider's observation time when supplied |
| retrieved_at | datetime | UTC time ReconLedger retrieved the evidence |
| confidence | enum? | Required for inferred results; absent for direct observations |
| fingerprint | SHA-256 | Stable identity key for deduplication and diff |

## 7. Technical architecture

### 7.1 Architecture summary

React with TypeScript is justified by the dashboard's live progress, compound filtering, evidence disclosure, and diff interactions. FastAPI, Pydantic, and httpx keep request, response, and collector contracts typed while making parallel provider calls natural with async I/O. SQLite is sufficient for a local single-user portfolio application and can safely own job state, evidence, and cache data when writes are short and serialized. A small SQLite-backed worker avoids the operational weight of Redis while preserving queued work and restart recovery. Server-Sent Events are simpler than WebSockets for one-way progress and retain a normal status endpoint as fallback. The collector interface isolates provider changes; the centralized outbound transport enforces host allowlists, retries, rate policies, and secret-safe evidence capture. This boundary is the key safety decision because individual collectors never receive unrestricted networking.

*Figure 1. Local-first architecture and passive-only network boundary.*

### 7.2 Component responsibilities

| Component | Responsibility |
|---|---|
| React client | Target validation preview, source selection/readiness, authorization form, SSE/polling, evidence UI, search, tables, history, diff, and download actions |
| FastAPI service | Typed API, validation, source catalog, report/export generation, origin controls, errors, and coordination with the job runner |
| SQLite + SQLAlchemy | Jobs, collector runs, findings, cache, attestations, migrations, indexes, and transactional state changes |
| Job runner | Claim queued jobs, resolve the target and seed the deny-list before dispatch, schedule applicable collectors, apply bounded concurrency, resume interrupted jobs, publish status events, and run the retention and cache-expiry sweep |
| Outbound gateway | HTTPS-only host/IP allowlist, redirect validation, timeouts, retry, rate limiting, response caps, and credential injection |
| Collectors | Provider-specific request formation, response validation, normalization, and typed errors |
| Inference engine | Pure local rules over stored findings; never performs network I/O |

### 7.3 Job and collector state model

| Level | States | Rule |
|---|---|---|
| Job | queued, running, completed, completed_with_warnings, failed, canceled | failed only when orchestration cannot run or no selected collector produces a valid terminal result |
| Collector | queued, running, done, failed, skipped_no_key, not_applicable, interrupted | done stores finding_count and cache_hit; every other terminal state stores a safe reason |
| Progress | event sequence + updated_at | SSE is advisory; GET status is authoritative and supports reconnect with last event ID |

### 7.4 Core API contract

| Method and route | Purpose | Key response |
|---|---|---|
| GET /api/sources | Source catalog and readiness | Target support, state, key-help URL, release |
| POST /api/jobs | Validate and queue authorized job | 202 JobRead with collector states |
| GET /api/jobs | Paginated/filterable history | JobSummary list |
| GET /api/jobs/{id} | Authoritative job status | JobDetail and collector runs |
| GET /api/jobs/{id}/events | Live one-way progress | SSE events with sequence IDs |
| GET /api/jobs/{id}/findings | Search/filter/sort findings | Paginated FindingRead |
| GET /api/jobs/{id}/subdomains | Subdomain workspace | Normalized rows and facets |
| GET /api/jobs/{id}/export?format={md\|json}&mode={summary\|full} | Evidence report/tool export | Download generated from DB |
| GET /api/jobs/{id}/subdomains.csv | Phase 2 handoff | Formula-safe UTF-8 CSV |
| GET /api/jobs/{id}/diff?against={job_id} | Evidence-aware comparison | Added/changed/removed/indeterminate groups |
| POST /api/jobs/{id}/collectors/{name}/retry | Retry one eligible failure | Updated collector state |
| POST /api/jobs/{id}/cancel | Cancel a queued or running job | Updated job and collector states |
| GET /api/cache | Cache inventory before purge | Entry counts, size, and expiry summary |
| DELETE /api/cache | Purge cached provider responses | 204 after confirmed deletion |
| DELETE /api/jobs/{id} | Delete a local job | 204 after dependent evidence removal |

### 7.5 Persistence model

| Table | Key fields and notes |
|---|---|
| jobs | id, target_input, target_normalized, target_type, status, scope_note, attestation_text/version/time, selected_sources_json, created/started/finished timestamps |
| collector_runs | id, job_id, collector, status, attempt_count, cache_hit, finding_count, safe_error_code/message, started/finished timestamps |
| findings | Finding schema fields; indexes on job/category/collector/kind/fingerprint and an FTS5 projection for global search. FTS5 virtual tables and their sync triggers cannot be autogenerated and are created through explicit migration operations. |
| cache_entries | cache_key, collector, schema_version, credential_scope_hash, status, response_json, normalized_findings_json, retrieved_at, expires_at, ETag/Last-Modified where useful |
| job_events | monotonic sequence, job_id, collector, event_type, payload_json, created_at; retained for reconnect and diagnostics |
| schema_version | Alembic migration state; database changes never rely on create_all in normal startup. Alembic runs with batch mode enabled because SQLite cannot alter or drop columns in place. |

### 7.6 Collector interface contract

```
Collector metadata
  name: stable machine identifier
  display_name: user-facing source name
  supported_targets: set[domain | ip | cidr | organization]
  categories: set[network | technology | human | leaked]
  required_credentials: list[credential name]
  provider_hosts: immutable allowlist
  key_help_url: official setup page or null
  rate_policy: requests/period, burst, concurrency
  cache_policy: positive TTL, negative TTL, schema version

run(context: CollectorContext) -> list[Finding]
  context includes normalized target, target type, scope, safe HTTP gateway,
  cache access, cancellation signal, job time budget, and UTC clock.
```

**Design advice:** Do not expose `httpx.AsyncClient` directly if it lets collectors change base hosts or redirect policy. Expose a narrow gateway method that validates the declared provider and destination before every request.

### 7.7 Recommended repository structure

```
reconledger/
  README.md
  LICENSE
  .env.example
  .gitignore
  .github/workflows/ci.yml
  docker-compose.yml
  backend/
    pyproject.toml
    alembic.ini
    app/
      main.py
      config.py
      api/{jobs,sources,exports,diffs}.py
      models/{api,domain,db}.py
      db/{session,tables}.py
      jobs/{runner,service,events}.py
      collectors/
        base.py
        registry.py
        rdap.py
        dns_doh.py
        crtsh.py
        ripestat.py
        wayback.py
        commoncrawl.py
        technology.py
      services/{outbound,cache,rate_limit,retry,diff,search,reports,retention}.py
      security/{targets,redaction,origins,exports}.py
    alembic/versions/
    tests/{unit,integration,fixtures}/
  frontend/
    package.json
    vite.config.ts
    src/
      api/
        generated/   (TypeScript client from OpenAPI)
      components/
      features/{launch,progress,findings,subdomains,history,diff}/
      pages/
      styles/
      test/
    e2e/
  docs/screenshots/
  docs/PRD.md   (Markdown copy of this document)
```

## 8. Safety, security, and privacy requirements

### 8.1 Passive-only enforcement

- All network-capable code lives behind the outbound gateway; a repository test fails if collectors import or construct unrestricted HTTP, DNS, socket, or subprocess clients.
- Provider hostnames are code-defined per collector. The user cannot supply a provider URL, callback URL, proxy URL, DNS server, or redirect destination.
- RDAP redirects/bootstrap results are accepted only when the destination is HTTPS, matches an approved registry service entry, and resolves outside prohibited address ranges.
- DNS queries go to a configured allowlisted public DoH resolver, never directly to NS records returned in evidence. Failover between allowlisted resolvers is permitted; a user-supplied resolver is not.
- Archive replay requests stay on approved Internet Archive/Common Crawl delivery hosts and stop before any live-target redirect.
- Shodan/Censys integrations call search/read endpoints only. Scan submission, on-demand probe, and monitoring activation endpoints are prohibited by tests and code review.
- CIDR input is passed only to provider-supported prefix queries; the application never loops through addresses to test reachability or perform reverse enumeration.
- The test suite blocks sockets process-wide, so any code path that opens a connection outside the gateway fails the build rather than merely bypassing an allowlist check.

### 8.2 Input, content, and export safety

- Reject URL schemes, paths, ports, control characters, overlong input, and wildcard targets at the primary input boundary.
- Parse untrusted JSON with Pydantic limits and reject unexpectedly large or structurally invalid responses with typed errors.
- Cap response bytes, decompressed bytes, record counts, archived document count, and evidence snippet size.
- Render raw evidence with textContent/preformatted text only; never inject provider HTML into the DOM.
- Sanitize Markdown fences and link text so evidence cannot break report structure or create active HTML.
- Protect CSV cells that begin with `=`, `+`, `-`, `@`, tab, or carriage return to prevent formula execution.
- Use exact local frontend origins, JSON content types, and state-changing request origin checks to reduce localhost cross-site request risks.
- Render original-target URLs as inert text. Only archive replay and provider evidence URLs are clickable, and the interface states why.
- Disable favicons, image loading, previews, iframes, and speculative connections for any host derived from the assessed target.
- Set a no-referrer policy document-wide so an outbound provider request cannot disclose the assessed target through a Referer header.

### 8.3 Secrets and logging

- Load secrets from environment variables or a developer-local .env file excluded from source control. Commit .env.example with names and setup links only.
- Never place credentials in query strings when the provider supports headers; never persist authorization headers or cookies.
- Redact configured secret values and sensitive headers from structured logs and collector error messages.
- The source-readiness endpoint reports only configured/not configured/invalid-entitlement states, never a key prefix or length.
- Bind to 127.0.0.1 by default; a non-loopback bind requires an explicit insecure-development acknowledgement in configuration.

### 8.4 Privacy and responsible evidence handling

- Collect only professional identity/contact information already present in public sources and required for the authorized assessment.
- Do not infer protected characteristics, personal vulnerability, or trustworthiness from personnel evidence.
- HIBP domain collection requires the subscriber's verified-domain entitlement. Default UI/report output is aggregate; individual aliases require an explicit reveal action and remain local.
- Show source, collection time, retention setting, and Delete job action wherever human or breach evidence is displayed.
- Documentation must explain provider terms, lawful authorization, data minimization, and the user's responsibility for exported evidence.

### 8.5 Future active-scanning requests

**Required response:** If a future request asks to add active scanning, the maintainer or implementation AI must refuse the change because it violates the product's approved threat model and user promise. Recommend a separate, clearly labeled lab tool with its own authorization controls and review rather than weakening ReconLedger's boundary.

## 9. Non-functional requirements

| Area | Requirement |
|---|---|
| Compatibility | Python 3.11+; current evergreen Chromium/Firefox; tablet viewport from 768 px; Windows, macOS, and Linux developer setup documented |
| Performance | Local API p95 under 200 ms for stored-job reads with 10,000 findings; search/filter feedback under 300 ms; provider work remains asynchronous |
| Concurrency | Default one job at a time, up to five collectors concurrently, and source-specific limits below provider policy; configurable without code changes |
| Process model | The durable worker runs in-process, so the API is served by a single worker process. A multi-process launch would let two workers claim the same queued job, and is rejected at startup unless an external worker is configured. |
| Timeouts | 10-second connect, 30-second default provider request, 90-second collector budget, and 5-minute default job budget. Documented per-provider overrides are required where a provider is reliably slower; crt.sh defaults to 60 seconds. |
| Reliability | No successful findings are lost because another collector fails; state transitions are transactional and idempotent |
| Observability | Structured logs include job/collector/request correlation IDs, latency, attempt, cache outcome, and safe error code; no raw secrets |
| Provider etiquette | Every request identifies the application and repository in the User-Agent, honors Retry-After, and stays within documented provider limits; free community providers are treated as a shared resource |
| Maintainability | Strict type checking, formatting/linting, migrations, documented collector contract, and fixture-based provider schemas |
| Accessibility | WCAG 2.2 AA core-flow target with keyboard, screen-reader, contrast, focus, reduced-motion, and semantic-table review |
| Data portability | Versioned JSON export and deterministic Markdown/CSV generated entirely from persisted evidence |
| Licensing | Repository includes an OSI-compatible license selected by the owner and notices for bundled dependencies/assets |

## 10. Testing and definition of done

### 10.1 Automated test strategy

- Collector unit tests use respx or httpx MockTransport. Required first set: RDAP registration parsing, DoH record/mail-policy parsing, and crt.sh name normalization/deduplication.
- Additional unit tests cover RIPEstat, archive pagination/caps, technology rule confidence, input normalization, raw-evidence redaction, CSV/Markdown injection, and stable fingerprints.
- Orchestration tests cover cache hits, negative cache, Retry-After, timeout/backoff, missing/invalid keys, partial completion, cancellation, restart recovery, and duplicate-job claims.
- Safety tests inspect every attempted outbound hostname and IP, reject redirects to the target/private ranges, and fail if target sockets or provider scan-submission routes are used.
- Diff tests prove that failed/skipped sources create indeterminate differences instead of false removals.
- FastAPI integration tests use a temporary SQLite database and dependency-injected mock providers; normal CI performs no live network calls.
- React component tests cover validation, readiness, progress semantics, empty/error states, filters, copy feedback, and raw-evidence disclosure.
- Playwright exercises the happy path, partial-provider failure, cached rerun, history reopen, diff, keyboard navigation, theme, and three downloads.
- Automated accessibility checks are supplemented by manual keyboard and screen-reader smoke tests on launch, progress, results, subdomains, and history.
- A process-wide socket block is enabled for the whole test suite so no test can reach a real network, and any unexpected connection attempt is reported as the offending call site.
- A client network test asserts that loading a completed job issues no browser request to the assessed target, including favicons, images, and speculative connections.
- A contract check regenerates the TypeScript client from the OpenAPI schema and fails when the committed client has drifted.

### 10.2 Required collector test cases

| Collector | Mock cases | Pass condition |
|---|---|---|
| RDAP | Full record, redacted registrant, missing dates, redirect, 429, malformed JSON | Normalized evidence is stable; redaction/missing fields do not crash; unsafe redirect blocked |
| DNS DoH | A/AAAA/MX/TXT, split TXT strings, NXDOMAIN, SERVFAIL, multiple SPF, DMARC tags, observed DKIM | Records and posture notes are cautious, typed, and fully attributable |
| crt.sh | Duplicates, wildcard/newline names, IDNA, unrelated SAN, expired cert, HTML error | Only in-scope names survive; evidence and failure states are correct |

### 10.3 Definition of done

- Every MVP requirement and acceptance criterion is implemented or explicitly removed through an approved PRD revision.
- Fresh install succeeds from README instructions without undocumented global dependencies.
- The repository contains .env.example and no committed secrets; secret scan passes.
- Database migrations create and upgrade a clean SQLite database.
- All automated tests, type checks, linters, and production builds pass in CI without live provider access.
- A recorded authorized-domain walkthrough demonstrates success, partial failure, cache hit, history/diff, and all exports.
- README contains the legal notice, architecture overview, provider/key setup, limitations, real screenshots, and active-scan refusal policy.
- Manual checks confirm no target traffic, no unsafe archive redirects, no HTML execution, and no CSV formula execution.
- Core flows pass keyboard and WCAG AA review in both themes at desktop and tablet widths.
- The committed TypeScript client matches the OpenAPI schema, verified in CI.
- A recorded browser network trace shows no request from the client to the assessed target.
- The retention and cache-expiry sweep is demonstrated on a database containing expired records.

### 10.4 Verification walkthrough acceptance

1. Start the API and client locally with no optional keys. Confirm every MVP source is ready, release 1.1 sources show needs-key or not-installed, and an organization input is refused with the release 1.1 explanation rather than a validation error.
2. Enter the user's authorized domain, add a scope note, select all MVP sources, check the authorization statement, and launch.
3. Observe independent collector states. A provider failure may produce completed_with_warnings, but successful findings remain available.
4. Confirm Network Footprint contains RDAP/DNS/CT/RIPE evidence; Technology Stack contains only evidence-backed inferences; unavailable Human Layer and Leaked Data sources explain the later release/key requirement.
5. Filter and copy the subdomain table, expand safe raw evidence, and use global search for a nameserver, URL parameter, or ASN.
6. Run the same target again within TTL and confirm cached collectors make no provider calls and show done-cached.
7. After a later forced refresh, compare runs. Confirm additions/changes are traceable and incomplete sources are not reported as removals.
8. Download Markdown, JSON, and CSV. Confirm the scope note and methodology appear in the report, JSON validates, and CSV opens without formulas.
9. Review outbound test and log evidence showing that only approved provider domains were contacted, and confirm in the browser network panel that the dashboard itself issued no request to the assessed target.

## 11. Risks and mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Provider instability or undocumented schema | Collector breaks or returns inconsistent evidence | Per-collector validation, fixtures, versioned parsers, cache, typed failure, visible warning |
| crt.sh latency and availability | Certificate Transparency evidence times out on busy domains | Extended per-provider timeout, cache, typed failure that never fails the job, documented fallback CT source for release 1.1 |
| Passive-only boundary erodes during feature work | Target traffic violates user promise | Central gateway, import rules, deny-by-default destinations, safety tests, refusal policy |
| Archive result volume | Slow jobs and oversized database/reports | Pagination, caps, canonical dedupe, representative sampling, byte limits |
| False certainty from empty results | Analyst interprets no data as no exposure | Explicit empty/failed/skipped states and cautious language |
| Technology false positives | Misleading stack claims | Evidence links, confidence, multi-signal rules, observed vs inferred distinction |
| Sensitive personnel/breach data | Privacy or inappropriate reuse | Release 1.1 gating, minimal collection, local retention, aggregate defaults, deletion |
| SQLite write contention | Progress delays under concurrency | Short transactions, WAL mode, one writer path, modest default concurrency |
| Duplicate job execution under a multi-process launch | Two workers claim the same job; doubled provider calls | Single-process default, transactional claim, startup rejection of an unsupported process model |
| Client-side contact with the target | The browser reaches the target even though the API never does | Inert target URLs, disabled previews and speculative connections, no-referrer policy, Playwright network assertions |
| Frontend/backend contract drift | Broken dashboard during changes | Generated TypeScript types from OpenAPI and contract tests |
| API cost/rate exhaustion | Keyed sources fail or incur charges | Source readiness, default off, configurable budgets, cache, visible usage errors |

## 12. Ranked roadmap and engineering advice

### 12.1 What to build next

| Rank | Milestone | Why this order |
|---|---|---|
| 1 | Ship the no-key vertical slice | Complete target validation, authorization, one durable job, RDAP/DNS/CT, evidence UI, and exports before broadening collectors. |
| 2 | Complete archives and inference | Add bounded Wayback/Common Crawl evidence, URL/parameter extraction, and transparent technology rules. |
| 3 | Add history and evidence-aware diff | Use stable fingerprints and indeterminate states; this is the feature that makes repeated recon meaningfully better than one-off tools. |
| 4 | Add keyed search integrations and organization targets | Implement GitHub, then one of Shodan/Censys, then the second; organization input becomes assessable once these organization-capable sources exist. Validate current plans and API contracts before each. |
| 5 | Add privacy-sensitive human/breach sources | Only after retention, deletion, aggregate views, and verified-domain HIBP behavior are proven. |

### 12.2 Senior engineering advice

- Define the Finding schema and error taxonomy before polishing the dashboard. The UI, diff, cache, and exports all depend on evidence being stable.
- Build a vertical slice with three collectors before adding more sources. Provider count is less valuable than proving safety, persistence, progress, and citation end to end.
- Keep the worker in-process but durable for the portfolio release. Redis/Celery would add deployment surface without solving a current multi-user requirement.
- Treat source absence as a first-class state in both UI and diff logic. This prevents the most dangerous analytical mistake: claiming something disappeared when the app simply failed to observe it.
- Make the outbound gateway independently testable. It is the product's security boundary and should be reviewed like authentication code.
- Treat the browser as part of the network boundary. A backend allowlist proves the API is clean; it says nothing about a link the dashboard renders, and a reviewer with a network panel open will notice the difference.
- Keep a Markdown copy of this document in the repository. It is what an implementation assistant can actually read, and it makes requirement changes reviewable in version control.

## 13. References

These sources establish the methodology context and current provider assumptions. Provider terms, pricing, authentication, and endpoint versions must be rechecked immediately before implementation because they can change.

- R1. NIST SP 800-115, Technical Guide to Information Security Testing and Assessment. https://csrc.nist.gov/pubs/sp/800/115/final
- R2. ICANN Registration Data Access Protocol (RDAP). https://www.icann.org/en/contracted-parties/registry-operators/resources/registration-data-access-protocol
- R3. Google Public DNS - DNS-over-HTTPS JSON API. https://developers.google.com/speed/public-dns/docs/doh/json
- R4. RIPEstat Data API. https://stat.ripe.net/docs/data-api/ripestat-data-api
- R5. Internet Archive Wayback CDX Server API. https://github.com/internetarchive/wayback/tree/master/wayback-cdx-server
- R6. Common Crawl Index Server. https://index.commoncrawl.org/
- R7. crt.sh Certificate Transparency search. https://crt.sh/
- R8. GitHub REST API - Search code. https://docs.github.com/en/rest/search/search?apiVersion=2022-11-28#search-code
- R9. Shodan Developer API. https://developer.shodan.io/api
- R10. Censys Platform API documentation. https://docs.censys.com/docs/platform-api
- R11. Have I Been Pwned API v3 - Domain Search. https://haveibeenpwned.com/API/v3#DomainSearch
- R12. W3C Web Content Accessibility Guidelines (WCAG) 2.2. https://www.w3.org/TR/WCAG22/
- R13. MITRE ATT&CK T1596 - Search Open Technical Databases. https://attack.mitre.org/techniques/T1596/
- R14. Sender Policy Framework (SPF), RFC 7208. https://www.rfc-editor.org/rfc/rfc7208
- R15. Domain-based Message Authentication, Reporting, and Conformance (DMARC), RFC 7489. https://www.rfc-editor.org/rfc/rfc7489
- R16. DomainKeys Identified Mail (DKIM) Signatures, RFC 6376. https://www.rfc-editor.org/rfc/rfc6376
- R17. Cloudflare 1.1.1.1 DNS over HTTPS - JSON API. https://developers.cloudflare.com/1.1.1.1/encryption/dns-over-https/make-api-requests/dns-json/
- R18. Alembic - Running batch (move and copy) migrations for SQLite. https://alembic.sqlalchemy.org/en/latest/batch.html
- R19. SQLite FTS5 full-text search extension. https://www.sqlite.org/fts5.html

## Appendix A. Requirements discovery record

The PRD was created only after the following clarifying decisions were answered. These answers are incorporated as requirements rather than left as open questions.

| Question | Answer | Effect on PRD |
|---|---|---|
| Should every source be required in the first release? | Phased MVP | No-key sources define MVP; keyed and privacy-sensitive sources move to release 1.1 |
| What application shape should be specified? | React + local app | React/TypeScript client, async FastAPI, SQLite, and localhost single-user deployment |
| How should the result be packaged? | PRD + AI handoff | This Word PRD is accompanied by a separate ready-to-paste implementation prompt |

## Appendix B. Implementation AI handoff protocol

The exact ready-to-paste prompt is delivered as `ReconLedger_AI_Implementation_Handoff.md`, and a Markdown copy of this document is delivered as `ReconLedger_PRD.md` (this file) so the implementation assistant can read the requirements without opening a Word file. Its required sequence is:

1. Read this entire PRD and treat it as the source of truth. Where the prompt and the PRD disagree, the PRD wins.
2. Summarize the approved product, identify contradictions or risks, and give implementation advice.
3. Review the pre-answered project questions in the prompt, then ask up to five consequential questions that neither the PRD nor those answers resolve.
4. Wait for all answers and continue short follow-up cycles until the requirements are implementable.
5. Propose a milestone plan and wait for approval before creating code or files.
6. Build in reviewable checkpoints rather than one delivery, because a repository of this size does not fit in a single response and an assistant compressing it will quietly thin the code.
7. Re-check each provider's current documentation immediately before implementing that collector.
8. State plainly which verification steps could not be executed, and never describe an unexecuted step as passing.

**Handoff guardrail:** The implementation AI is explicitly instructed to refuse any later request for active-scanning capability and recommend a separate authorized lab project instead.

## Appendix C. Revision history (version 1.1)

Version 1.1 applies an implementation-readiness review of the 1.0 baseline. No approved product decision was reversed. The changes close internal contradictions, extend the passive-only boundary to the browser client, correct provider assumptions, and record build-time constraints that would otherwise be discovered during implementation.

| Change | Sections affected | Reason |
|---|---|---|
| Organization target had no MVP collector | 2.2, 4.1, 4.3, 4.4, 5 (UX-02), 10.4, 12.1 | The input was accepted but every collector would report not-applicable. Organization support is now explicitly deferred to release 1.1 and the interface says so. |
| No cancel endpoint | 7.4 | The state model and the test plan both required cancellation that the API did not expose. |
| No cache purge endpoint or retention owner | 6 (FR-12), 7.2, 7.4, 10.3 | Retention and the Clear cache action were promised with nothing scheduled to perform them. |
| Target deny-list could be empty at dispatch | 6 (FR-03), 7.2 | Resolved target addresses arrive from a collector, so the strongest safety rule had a startup window. Resolution now precedes dispatch. |
| Client could contact the target | 1.5, 1.6, 2.3, 5 (UX-12), 8.2, 10.1, 10.3, 10.4, 11 | Every control was server-side. A clickable original-target URL or a favicon would reach the target from the analyst browser during an assessment. |
| Common Crawl treated as a single index | 4.3, 6 (FR-09) | The index server exposes many crawl collections; the collector now queries a configured recent subset and records the collection identifier. |
| crt.sh inherited the default timeout | 4.3, 9, 11 | Wildcard queries regularly exceed 30 seconds, which would have produced spurious failures. A 60-second override and a documented fallback source were added. |
| Single DNS resolver | 4.3, 6 (FR-07), 8.1 | One provider meant one cache view and no failover. A secondary allowlisted resolver is now supported, and resolver disagreement is treated as evidence. |
| No provider identification | 6 (FR-03), 9 | The product depends on free community infrastructure; requests now identify the application and repository. |
| Alembic and FTS5 assumptions | 7.5 | SQLite requires Alembic batch mode, and FTS5 tables and triggers cannot be autogenerated. |
| Process model unstated | 9, 11 | The in-process durable worker is duplicated by a multi-process launch, letting two workers claim one job. |
| Markdown export unbounded | 6 (FR-11), 7.4 | The performance target assumes 10,000 findings, which produces an unreadable report. Summary and full modes were added. |
| Route shapes | 7.4 | A dotted path extension and a positional diff route were replaced with query parameters. |
| Allowlist tests proved policy, not isolation | 1.5, 8.1, 10.1 | A process-wide socket block now fails the build for any connection opened outside the gateway. |
| Generated client absent from structure and CI | 7.7, 10.1, 10.3 | Contract drift was listed as a risk with no mechanism to detect it. |
| Usability measure was not executable | 1.5 | A five-person moderated study is not realistic for a solo portfolio project; the measure is now two unmoderated testers with logged failures. |
| Markdown copy of the PRD | 7.7, 12.2, Appendix B | The handoff instructs an assistant to read a Word file it may not be able to open. |
| Handoff sequence | Appendix B | Checkpointed delivery, pre-answered questions, per-collector provider recheck, and an honest-verification clause were added. |
