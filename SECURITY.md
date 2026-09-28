# Security Policy

AI Flow automates interactions with third-party AI provider web interfaces on
the user's behalf. Because of that, security issues in this project can have
outsized consequences (account safety, data exposure), and we take reports
seriously.

## Reporting a Vulnerability

If you discover a security vulnerability, please **do not** open a public
GitHub issue. Instead:

1. Open a private security advisory on GitHub ("Security" tab → "Report a
   vulnerability"), or
2. Use the `security_report.md` issue template and mark it clearly as
   sensitive, redacting any exploit details, and request a private follow-up.

Please include:

- A description of the vulnerability and its impact
- Steps to reproduce (minimal reproduction preferred)
- The extension version / commit hash
- Any relevant browser and OS version information

We aim to acknowledge reports within 5 business days.

## Scope

In scope:

- The extension's service worker, content scripts, and UI surfaces
- The storage, checkpoint, retry, and scheduler subsystems
- Provider adapters (e.g., unsafe DOM injection, credential leakage)
- The import/export and encryption code paths

Out of scope:

- Vulnerabilities in third-party AI provider websites themselves (report
  those to the provider directly)
- Denial-of-service via local resource exhaustion on the user's own machine

## Security Principles Enforced by Design

AI Flow will never (see `docs/security.md` for details):

- Store passwords, raw authentication credentials, or session cookies
- Attempt to bypass CAPTCHAs, rate limits, or authentication controls
- Send user prompts, files, or conversation contents to any server other
  than the provider's own official web application the user is already
  signed into
- Request broad host permissions beyond the providers a user explicitly
  enables

## Disclosure

We follow coordinated disclosure. We will credit reporters (unless they
prefer to remain anonymous) once a fix has shipped.
