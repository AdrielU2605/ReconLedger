# ReconLedger

A local-first passive reconnaissance workbench for structured, repeatable, and citable OSINT.

**Authorized use only.** ReconLedger is designed only for domains, IP space, and organizations
you own or have written authorization to assess. The application queries approved public or
third-party data providers and never communicates directly with the assessed target. See
[docs/PRD.md](docs/PRD.md) for the complete requirements, safety boundary, and architecture.

## Status

Under active, checkpointed development. This README will gain full setup instructions,
provider key-help links, screenshots, and the active-scan refusal policy at the final
checkpoint (definition of done). Until then:

- **CP1:** repository bootstrap and the outbound safety gateway - the single policy-enforcing
  transport every future network call must go through.
- **CP2:** persistence (SQLAlchemy + Alembic + FTS5), the job runner (claim, dispatch, cancel,
  restart recovery), the collector plug-in contract and registry, server-side target validation,
  the diff and export services, and the core REST + SSE API.
- **CP3 (this checkpoint):** the first three MVP collectors - RDAP, DNS-over-HTTPS (with a
  secondary resolver and resolver-disagreement evidence), and crt.sh Certificate Transparency -
  plus the FR-05 response cache. `GET /api/sources` now lists all three as ready with no keys
  required. CP4 adds the first frontend slice over these three collectors.

### Running it locally (developer preview - full instructions land at the final checkpoint)

```
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev]"
alembic upgrade head
uvicorn app.main:app --reload
```

## License

MIT - see [LICENSE](LICENSE).
