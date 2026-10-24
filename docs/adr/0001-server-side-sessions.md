# ADR 0001: Server-side sessions instead of JWT in localStorage

- Status: accepted
- Date: 2026-10-20

## Context
The SPA and the API are served from the same origin (Vite proxy in development, a reverse proxy
in production). We need authentication that can be revoked and that limits the damage of an XSS bug.

## Decision
- Random 256-bit session token in an `HttpOnly`, `SameSite=Lax` cookie (`Secure` when behind HTTPS).
- Only the SHA-256 of the token is stored (`sessions.id`).
- CSRF: synchronizer token. Each session has a `csrf_token`, returned by `/auth/register`,
  `/auth/login` and `/auth/me`, and required in the `X-CSRF-Token` header on every non-GET request.
- Passwords: Argon2id (argon2-cffi defaults).

## Alternatives considered
- **JWT in localStorage:** readable by any injected script, and not revocable before expiry
  without adding a server-side denylist, which is a session store with extra steps.
- **JWT in an HttpOnly cookie:** fixes the XSS exposure but keeps the revocation problem and still
  needs CSRF protection.

## Consequences
- Every authenticated request costs one indexed primary-key lookup.
- Logout and "revoke all sessions" are real.
- Horizontal scaling works because state is in PostgreSQL, not in process memory.
- Not done yet: login rate limiting and account lockout (see Known Limitations).
