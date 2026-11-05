# Security and private data

This is a local development application. It binds to `127.0.0.1` and does not
provide multiuser authentication. Do not expose it publicly without adding
authentication, authorization, transport security, and a deployment review.

## Credentials and data

- Each developer uses their own AWS `default` profile, stored outside the checkout
  in their user-level `.aws` directory. Prefer temporary credentials or SSO.
- Never commit `.env` files, AWS profiles, Streamlit secrets, tokens, private keys,
  recordings, transcripts, batch exports, SQLite databases, logs, or model caches.
- The app transcribes audio locally. Transcript text and class/field definitions
  are sent to the configured Amazon Bedrock endpoint for AI operations. Bedrock
  usage can incur charges. Local JSON exports and response caches contain derived
  user data and must be handled like the original recordings.
- `.env.example` contains non-secret examples and empty credential fields. The app
  loads the root `.env` locally at startup without replacing existing shell variables.
  Keep real values only in ignored `.env` or the local environment. Restart after edits.

## Repository checks

Run `python scripts/security_check.py --install` before your first upload. Install
the commit hook with `git config core.hooksPath .githooks`. The hook checks the
exact staged content, so unstaged edits cannot hide a staged secret.
The pre-push hook additionally checks tracked files and all reachable Git history.
On macOS/Linux, both hook files need executable permission (`chmod +x .githooks/pre-*`).

The check blocks private/runtime paths even if force-added, rejects source files
over 5 MB and symbolic links, checks for literal active environment-secret values,
and runs the default Gitleaks rules. The scanner is pinned; downloaded release
archives are SHA-256 verified. It prints finding locations and rules, never secret
values. Temporary snapshots/reports and scanner binaries stay under ignored
`.run/`; temporary snapshots/reports are removed after each check.

There is no GitHub Actions workflow in this temporary development repository.
Tests and security checks run locally, including through the enabled Git hooks.
Run `python scripts/security_check.py --tracked --history` locally to do the same.

Hooks are opt-in per clone and can be bypassed. Repository owners
should enable GitHub secret scanning and push protection where available.
No scanner detects every secret
or every form of personal data; review staged files before every commit.

If a credential was ever committed, revoke/rotate it first. Deleting a file or
adding `.gitignore` does not remove it from Git history. Coordinate any history
cleanup with the repository owner before publishing or force-pushing.

## Reporting a vulnerability

Contact the repository owner privately. Use GitHub private vulnerability reporting
from the Security tab if it is enabled. Do not include credentials, recordings,
transcripts, or full environment dumps in public issues or pull requests.
