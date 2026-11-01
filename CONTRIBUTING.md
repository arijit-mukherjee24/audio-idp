# Contributing

1. Follow the Python 3.13 and AWS setup in [README.md](README.md). AWS is only
   needed for interactive Bedrock features; automated tests use mocked responses.
2. Run `python scripts/security_check.py --install`, then
   `git config core.hooksPath .githooks` in each clone before committing.
3. Keep processing services independent of Streamlit. Put provider code in
   `audio_idp/providers`, orchestration in `workflow`, and screens in `ui`.
4. Run `python -m unittest discover -v` for relevant behavior changes. Tests must
   not call live AWS, require credentials, or download models.
5. Review `git diff --cached --stat` and `git status --short`. Use synthetic data
   only; never force-add local data, secrets, models, or exports.
6. Run `python scripts/security_check.py --staged` before committing. If the hook
   fails, correct the issue; do not bypass it to publish credentials.

`requirements.txt` contains the normal application dependencies. Speaker diarization
is optional and disabled in the UI; `requirements-speakers.txt` is for developers
working on that optional backend capability.

Describe the user-visible behavior change and the checks you ran in a pull request.
See [SECURITY.md](SECURITY.md) for handling credentials and reporting vulnerabilities.
