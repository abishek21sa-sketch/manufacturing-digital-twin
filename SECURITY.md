# Security Policy

## Scope

This repository contains an engineering decision workstation and a production-readiness
foundation. It is not an authorization to connect recommendations directly to plant
execution systems.

## Required production controls

- Run behind an enterprise identity or API gateway with TLS termination, network policy,
  and site/tenant isolation.
- Inject and rotate API keys through an approved secret manager. Never commit `.env`,
  credentials, license files, or production databases.
- Set `MDT_ENV=production`, `MDT_AUTH_MODE=api_key`, `MDT_AUTO_CREATE_SCHEMA=false`,
  and explicit non-wildcard `MDT_ALLOWED_HOSTS`.
- Apply reviewed Alembic migrations before starting application replicas.
- Restrict `/metrics` and operational endpoints at the network gateway when the platform
  exposes them outside a trusted monitoring plane.
- Preserve request IDs, event IDs, idempotency keys, decision records, and human
  dispositions in the enterprise audit system.

## Reporting

Do not publish credentials, plant data, license material, or exploit details in a public
issue. Report suspected vulnerabilities through the deploying organization's approved
security channel and include the affected release, reproduction conditions, and whether
real plant systems or data were reachable.

## Data boundary

The bundled evidence is benchmark, synthetic, simulated, or historical replay evidence.
Plant-specific data handling, retention, access review, incident response, and recovery
objectives must be approved by the deploying organization before production use.
