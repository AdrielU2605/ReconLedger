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

- **CP1 (this checkpoint):** repository bootstrap and the outbound safety gateway - the single
  policy-enforcing transport every future network call must go through. No product features
  exist yet.

## License

MIT - see [LICENSE](LICENSE).
