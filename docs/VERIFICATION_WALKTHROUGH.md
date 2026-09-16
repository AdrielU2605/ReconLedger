# Verification walkthrough

This records an actual run through PRD [10.4's acceptance walkthrough](PRD.md) and
[10.3's definition of done](PRD.md), against the real backend and the real internet, on the fixed
verification target (`example.com`). Each step below states what was run, what came back, and -
per this project's own rule - is explicit about anything that was *not* independently verified
here rather than describing it as passing.

All commands were run against a throwaway SQLite database (never the developer's own
`reconledger.db`), booted the same way `backend/scripts/run_e2e_server.py` does.

## 1. Fresh start, no optional keys

```
GET /api/sources
```

All 7 MVP sources reported `state: ready`, no key required:

```
rdap            release=mvp    state=ready
dns_doh         release=mvp    state=ready
crtsh           release=mvp    state=ready
ripestat        release=mvp    state=ready
wayback         release=mvp    state=ready
commoncrawl     release=mvp    state=ready
technology      release=mvp    state=ready
```

An organization-name target was submitted and refused with the release 1.1 explanation, not a
generic validation error:

```
POST /api/jobs {"target": "Example Corp", ...}
→ 422 "No MVP collector accepts organization targets. Organization search ships in release 1.1
   alongside the organization-capable keyed sources."
```

*Not applicable in this build:* no release-1.1 (keyed) source exists yet, so a "needs-key" state
could not be exercised - there is nothing to show it on.

## 2-3. Launch and independent collector states

A real job was launched against `example.com` with all 7 sources, a scope note, and the
authorization attestation checked. First run:

```
rdap         done              1 finding
dns_doh      done              8 findings
crtsh        failed            provider_schema_error: crtsh could not parse the provider response
ripestat     not_applicable    (RIPEstat doesn't support a domain target - correct)
wayback      done              5 findings
commoncrawl  done              9 findings
technology   done              2 findings
job status: completed_with_warnings
```

This is a genuine instance of the exact risk [documented in the PRD's risk table](PRD.md) (crt.sh
instability under load) - not a scripted example. The job still completed with every other
source's findings intact, and crt.sh's own failure was legible, not a raw exception.

The collector-level retry endpoint was then exercised against this real failure:

```
POST /api/jobs/{id}/collectors/crtsh/retry → {"status": "retry_queued"}
```

crt.sh succeeded on retry (6 findings), and the job moved to `completed`.

## 4. Category breakdown and evidence-backed technology

```
By category: {'network_footprint': 29, 'technology_stack': 2}
```

Both Technology Stack findings carried a real source link back to the evidence that produced
them, e.g.:

```
Cloudflare (DNS/CDN) | confidence=medium | source_url=https://dns.google/
Cloudflare            | confidence=medium | source_url=https://data.commoncrawl.org/crawl-data/...
```

Human Layer and Leaked Data were empty for every run, as expected - no MVP source targets those
categories; the UI's explanation for their absence (release 1.1 / key requirement) is a frontend
concern, not re-verified independently here beyond the existing component tests.

## 5. Subdomains, raw evidence, and global search

```
GET /api/jobs/{id}/subdomains
```

returned 6 real subdomains recovered from crt.sh's certificate history for example.com
(`dev.`, `m.`, `products.`, `support.`, `www.`, plus a wildcard entry), each with real first/last
seen dates spanning 2014-2033.

Global search was exercised against real finding content, not fixture data:

- `?q=elliott.ns.cloudflare.com` (a real nameserver from this run) matched the RDAP registration
  finding *and* the DNS SOA finding - correctly, since both sources independently reported it.
- `?q=robots` (a URL-path term) matched the four `commoncrawl.url` findings for
  `/robots.txt`.

Filtering, copying, and the raw-evidence disclosure toggle are UI interactions covered by
`SubdomainWorkspace.test.tsx` and `FindingsView.test.tsx` (Vitest component tests) rather than
re-clicked by hand here.

## 6. Cached rerun

The same target was launched again immediately, same sources:

```
rdap         done (cached)
dns_doh      done (cached)
crtsh        done (cached)
wayback      done (cached)
commoncrawl  done (cached)
technology   done              ← correctly NOT cached; it's pure local inference, re-derived
                                  every run rather than fetched, so "cache_hit" doesn't apply to it
```

No `provider_request` log line was emitted for any of the cached collectors on this run.

## 7. Forced refresh and diff

`DELETE /api/cache` was called (the "Clear cache" action) to force a genuine refetch, then the
target was launched a third time. This run hit a second real-world instance of provider
instability - RDAP itself timed out:

```
rdap    failed   collector_timeout: "rdap exceeded its collector time budget."
```

Diffing this run against the first (where RDAP succeeded) produced exactly the PRD's required
behavior: the RDAP finding was reported as **indeterminate**, not removed, because the source
didn't complete in both runs.

```
GET /api/jobs/{new}/diff?against={old}
→ indeterminate: [{"collector": "rdap", "kind": "rdap.registration", ...}]
```

This diff also caught a real bug (now fixed, commit `af522cd`): Technology Stack findings were
showing as "changed" on every rerun even when identical, because their `normalized_value` embedded
each run's own ephemeral Finding-row IDs, which the diff engine compares for equality. Fixed by
moving those IDs to `raw_evidence` only, with a regression test
(`test_identical_evidence_across_two_runs_produces_equal_normalized_value`) guarding it.

## 8. Exports

All three formats were downloaded and inspected directly, not just requested:

- **Markdown** - the scope note and the methodology/limitations paragraph both appear verbatim in
  the rendered report, ahead of the per-source status table and findings.
- **JSON** - parsed cleanly with Python's `json.load`; `job.scope_note` round-tripped correctly.
- **CSV** (subdomains) - parsed cleanly with Python's `csv` module; no cell began with
  `=`, `+`, `-`, or `@` unescaped, confirming the formula-injection guard held on real data (not
  just the unit tests that already cover it directly).

## 9. Outbound evidence

The gateway's own structured log for the full run above shows exactly five hosts contacted, all
on the approved provider list, and nothing else:

```
cloudflare-dns.com, crt.sh, data.iana.org, dns.google, rdap.verisign.com
```

The browser-side half of this claim - that the dashboard itself never issues a request toward the
assessed target (favicons and speculative connections included) - is covered separately by
`frontend/e2e/client-isolation.spec.ts`, which runs against the real gateway and real provider
data (not mocked) specifically so this check has teeth. That suite passed as of this session.

## What this walkthrough does not independently re-verify here

- **Manual keyboard/screen-reader smoke tests.** Automated coverage exists (Playwright keyboard
  navigation, computed-contrast checks against both themes, `outline-style: auto` confirmed
  present with nothing overriding it), but no human ran a screen reader against the app.
- **CI's actual pass/fail status on GitHub.** Every check in this walkthrough, and the full
  backend/frontend/e2e suites, were run locally and passed; the GitHub Actions run for the latest
  push has not been independently confirmed from this environment (no authenticated GitHub access
  available here).
- **A truly clean-machine install** (no dev environment carryover) was not performed as part of
  this specific pass, though the backend/frontend setup commands in the README match what this
  project's own CI does from a bare checkout.
- **The retention/cache-expiry sweep on expired records** was demonstrated in the CP9 session
  (commit `845a81a`): a 200-day-old completed job and an expired cache entry were seeded directly
  into a fresh database, and the real application's startup sweep removed exactly those two rows
  while leaving a 1-day-old job and an unexpired cache entry untouched - not re-run in this pass.
