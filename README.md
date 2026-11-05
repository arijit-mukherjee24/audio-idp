# Audio IDP

A local audio-to-structured-data workspace built with Python 3.13, Streamlit,
SQLite, local faster-whisper, Amazon Transcribe or Azure Speech, and Amazon Bedrock.

Upload recordings, transcribe locally or with AWS, automatically suggest and assign a class,
review shared field definitions, and extract values with supporting quotes.
The dashboard lists saved batches; each batch has its own pipeline, JSON preview,
JSON/CSV exports, and processing-job view. Light and dark themes are available.

## Prerequisites

- **Python 3.13, 64-bit**. On Windows, include the Python launcher (`py`) during installation.
- **Git** and Internet access for installing dependencies and the initial model download.
- **Windows PowerShell 5.1 or PowerShell 7** for the included start/stop scripts.
- **AWS CLI v2** and an AWS account/role allowed to invoke the configured Bedrock model.
  AWS credentials are needed for Amazon Transcribe, class/field suggestions, and
  extraction, not for local Whisper transcription or offline tests. AWS calls can incur charges.

Windows is the supported start/stop-script environment. A manual foreground command
for macOS/Linux is provided below; those platforms do not use the PowerShell lifecycle scripts.

## Clone and install

Replace the example repository URL with this repository's actual GitHub URL:

```powershell
git clone https://github.com/YOUR_ORG/audio-idp.git
cd audio-idp
py -3.13 --version
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Calling the virtual environment's interpreter directly avoids an activation step.
Alternatively, `start.ps1` creates `.venv` with Python 3.13 and installs missing
application dependencies automatically. An existing `.venv` must also use Python 3.13.

Before making commits or pushing, install the local security scanner and enable the hooks:

```powershell
.\.venv\Scripts\python.exe scripts/security_check.py --install
git config core.hooksPath .githooks
```

The first command downloads a pinned, checksum-verified Gitleaks release into
ignored `.run/tools` and scans publishable files. Later checks use that cached archive.
Every clone must enable the hooks separately; Git does not install repository hooks automatically.
The commit hook checks staged content; the push hook checks tracked content and Git history.
On macOS/Linux, ensure both hook files are executable with `chmod +x .githooks/pre-*`.

## Configure your own AWS login

The app uses `boto3.Session(profile_name='default')`, the **`us-east-1`** Bedrock
Runtime endpoint, and the **`us.anthropic.claude-sonnet-4-6`** inference profile.
These non-secret defaults live in `audio_idp/config.py`. A differently named profile
or setting `AWS_PROFILE` alone does not change the explicit `default` profile used by this app.

Each developer must authenticate on their own computer. Do not copy another
person's AWS files into this checkout or enter credentials into application source code.

For organizations using IAM Identity Center, configure SSO and choose **default**
as the CLI profile name when prompted:

```powershell
aws configure sso --profile default
aws sso login --profile default
aws sts get-caller-identity --profile default
```

Use the start URL, SSO region, account, and role provided by your organization.
The SSO directory region can differ from the Bedrock endpoint region. See the
[AWS SSO setup guide](https://docs.aws.amazon.com/cli/latest/userguide/cli-configure-sso.html).

If your organization instead provides access keys, use its approved credential
process and configure the local default profile with `aws configure --profile default`.
Temporary credentials also need their matching session token. Prefer temporary
credentials/SSO; refresh expired sessions with your organization's login procedure.
`get-caller-identity` confirms the login, but does not prove Bedrock permissions.
Do not paste its account details or any credentials into public issues.

AWS configuration belongs in your user-level AWS directory, outside this project:
`%USERPROFILE%/.aws/` on Windows or `~/.aws/` on macOS/Linux. The app does not ask
for credentials through its UI. Keep them on each developer's own computer.

The role needs `bedrock:InvokeModel` for the configured inference profile and its
underlying destination-region foundation models. An administrator must also ensure
model access and organization/SCP rules permit this inference route. The `us.`
profile can route requests to supported US regions. See the official
[Converse permissions](https://docs.aws.amazon.com/cli/latest/reference/bedrock-runtime/converse.html)
and [inference-profile prerequisites](https://docs.aws.amazon.com/bedrock/latest/userguide/inference-profiles-prereq.html).
Do not grant administrator access just to run this app.

## Start and stop on Windows

From the project directory, after AWS login:

```powershell
.\start.ps1
```

Open the printed URL, normally **http://127.0.0.1:8501/**. Startup runs Streamlit as a
hidden background process bound to localhost, checks port availability, and records
its process identity in `.run/`. Logs are `.run/stdout.log` and `.run/stderr.log`.
Run from a normal PowerShell session that can read your user-level AWS profile.

```powershell
.\stop.ps1
```

Stop verifies the recorded process identity and terminates only that application
process tree. Saved batches survive restarts. Let active jobs finish before stopping;
interrupted jobs can be retried after restarting. Downloaded models are retained.

Additional startup options:

```powershell
.\start.ps1 -Port 8502
.\start.ps1 -InstallDependencies
```

Stop the current instance before starting with different options. If PowerShell
blocks a downloaded script, review it and follow your organization's script policy;
for a trusted clone, `Unblock-File .\start.ps1` and `Unblock-File .\stop.ps1` may
remove the downloaded-file mark. Do not disable machine-wide execution protections.

The first Whisper transcription downloads the public **small** model into `.models/`.
That download needs Internet access; subsequent transcriptions reuse it locally.
CPU inference uses int8. Speaker diarization is disabled and needs no Hugging Face token.
The normal install is `requirements.txt`; `requirements-speakers.txt` is optional
backend development support and is not needed for this UI.

### Choose a transcription engine

In **Upload & transcribe → Add recordings**, select **Transcription engine**:

- **Whisper (local)** is the default, including for existing batches. It runs on
  your CPU and reuses the downloaded model.
- **Amazon Transcribe** uploads validated, mono 16 kHz WAV audio to S3, submits a
  standard batch transcription job, and retrieves its timestamped transcript.
  It uses the same user-level AWS `default` profile as Bedrock. No separate
  data-access role or `iam:PassRole` is used.
- **Azure Speech** sends validated, mono 16 kHz WAV audio directly to Azure's
  Fast Transcription API (Standard S0). It returns a
  timestamped transcript without requiring a Blob Storage account. Configure the resource and
  authentication as described below.

Click **Upload & transcribe** to save the choice and process pending recordings.
The choice is saved per batch. It cannot change while transcription is active;
completed transcripts are kept and show the engine that produced them.

Amazon Transcribe defaults to bucket `am-sc-test-bucket`, region `us-east-1`.
Override these non-secret values before starting if needed:

```powershell
$env:AUDIO_IDP_TRANSCRIBE_BUCKET = 'your-private-bucket'
$env:AUDIO_IDP_TRANSCRIBE_REGION = 'us-east-1'
.\start.ps1
```

The bucket must be in the selected region. The role needs
`transcribe:StartTranscriptionJob`, `transcribe:GetTranscriptionJob`, and
`transcribe:DeleteTranscriptionJob` (for retrying failed AWS jobs), along with
`s3:GetBucketLocation`, `s3:PutObject`, and `s3:GetObject` for the configured bucket
and `audio-idp/` object prefix. Bucket policies and encryption-key permissions
must also allow access.

English maps to `en-US`, Spanish to `es-ES`, and French to `fr-FR`. Auto-detection
selects among those three variants. Speaker labels remain disabled for both engines.
The existing 50 MB / 10-minute limits apply before an AWS upload.

The AWS path stores WAV inputs under `audio-idp/input/` and transcript JSON under
`audio-idp/output/`. These objects and AWS job records are retained for recovery.
Deleting local batches, transcripts, or workspace data does **not** delete cloud
copies. Configure bucket lifecycle retention separately if required.

Stable names derived from the audio and settings let retries reuse completed AWS
jobs or reconnect to running jobs, including after an app restart. Retry an
interrupted stage with **Upload & transcribe**; jobs are not automatically
resubmitted at startup. A poll timeout after 30 minutes leaves the AWS job intact
so retry can reconnect. Retrying a failed AWS job recreates it and may incur charges.
Cancelling a local job discards its local result; it does not stop AWS processing.

See the AWS [batch API](https://docs.aws.amazon.com/transcribe/latest/APIReference/API_StartTranscriptionJob.html)
and [pricing](https://aws.amazon.com/transcribe/pricing/) for service details and costs.

### Azure Speech setup

The app loads the root `.env` automatically. Copy `.env.example` to `.env` if it
does not exist, then edit only `.env` with your resource's local credentials.
Existing shell environment variables take precedence; restart the app after edits.

Use a **Standard S0** Speech resource in a region supporting Fast Transcription.
Free F0 resources do not support this API. Change the resource's pricing tier to
S0 in Azure portal, or create an S0 resource. This is a paid usage-based service;
the app does not change your Azure resource or pricing tier automatically.

Configure these values in the ignored root `.env`:

```dotenv
AZURE_SPEECH_MODE=fast
AZURE_SPEECH_AUTH=key
AZURE_SPEECH_KEY=
AZURE_SPEECH_ENDPOINT=https://your-speech-resource.cognitiveservices.azure.com
```

Set the key (Key 1 or Key 2) and actual resource base endpoint from **Keys and Endpoint**
in Azure portal. Do not include an API path or query string. No separate region
variable is required: the endpoint determines the Azure resource/region.
Fast mode supports the app's normal 10-minute limit and automatic language detection.
It uses API version `2025-10-15` and can incur transcription charges.

Start/restart from PowerShell after saving `.env`:

```powershell
.\stop.ps1
.\start.ps1
```

The key belongs only in ignored `.env` or your local shell environment, never in
source, batch metadata, chat, or `.env.example`. `.env` stays outside Git.
Azure only changes transcription; class/field suggestions and extraction still
use AWS Bedrock and need the AWS default profile described above.

Optional Microsoft Entra authentication uses `AZURE_SPEECH_AUTH=entra` instead of
a key. It requires the optional `requirements-azure.txt` dependencies, a custom
resource subdomain, and an identity with the **Cognitive Services Speech User**
role at the Speech resource scope. Authentication uses `DefaultAzureCredential`,
which supports configured application identities or an existing Azure CLI login.
No interactive login is started by the app.

Create a **new batch**, select **Azure Speech** under **Transcription engine**,
choose the audio language, and click **Upload & transcribe**. English, Spanish,
and French map to `en-US`, `es-ES`, and `fr-FR`. Completed transcripts are preserved
when switching engines, so an existing completed file will not be transcribed again.
Credentials are checked only when Azure is selected; other engines need no Azure setup.

Azure Fast Transcription does not create Blob objects or resumable batch jobs. Completed transcripts
are stored locally. A request interrupted by timeout or app restart cannot be
reattached; retrying can consume more quota/usage. Requests are not automatically
retried. Speaker labels remain disabled.

Cloud transcription requests originate from the Python backend, so Azure HTTP calls
do not appear directly in browser Network tools. **Batch jobs** shows the actual
provider and response source. New Azure jobs record HTTP 200, the endpoint, API
version, request time, and Azure's request ID when returned. Expand **Job details
and actions** to inspect these fields. Credentials and transcript content are not
copied into job execution metadata. Older jobs show **Not recorded** instead of
inferring a historical provider from the current dropdown/transcript. The current
saved transcript provider remains available for reference. Cached/Fresh labels
describe Bedrock response caching; Azure transcription is not response-cached.

See Microsoft's [Fast Transcription guide](https://learn.microsoft.com/en-us/azure/ai-services/speech-service/fast-transcription-create),
[quotas](https://learn.microsoft.com/en-us/azure/ai-services/speech-service/speech-services-quotas-and-limits),
and [Speech permissions](https://learn.microsoft.com/en-us/azure/ai-services/speech-service/role-based-access-control)
for region availability and resource authentication requirements.

### Optional application settings

Set these before starting, either in the ignored root `.env` or as shell variables.
The app reads `.env` automatically; shell variables take precedence.

```powershell
$env:AUDIO_IDP_DATA = '.data'
$env:AUDIO_IDP_WORKERS = '2'
.\start.ps1
```

`AUDIO_IDP_DATA` selects local storage (default `.data`). Keep custom storage outside
version control or inside an ignored directory. `AUDIO_IDP_WORKERS` controls concurrent
transcription workers, from 1 to 4 (default 2). Bedrock workers run up to three AI jobs
concurrently. More transcription workers use more memory.

### Manual foreground startup

On Windows, use `.\.venv\Scripts\python.exe -m streamlit run app.py` and stop with
**Ctrl+C**. The lifecycle scripts do not track a manually started instance.

On macOS/Linux with Python 3.13 installed:

```bash
python3.13 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m streamlit run app.py --server.address 127.0.0.1
```

Stop with **Ctrl+C**. The same local AWS `default` profile is required for AI features.

## Pipeline

1. **Upload & transcribe:** Up to 10 recordings per batch, each at most 50 MB and
   10 minutes. Supported formats: MP3, WAV, M4A, FLAC, OGG, WEBM. Select a file to
   review/edit its transcript and status while other files continue processing.
2. **Classes & assignment:** Each completed transcript gets one suggested primary
   class and is assigned immediately. Class names allow 80 characters; descriptions
   allow 400. Refresh only the selected file's suggestion, choose an existing class,
   or create/assign a custom class. Newer manual choices override stale AI responses.
3. **Fields:** Files assigned to the same class share up to 10 suggested field
   definitions. Review and accept fields individually or as a class-wide set.
4. **Results:** Extract accepted fields for each file independently, showing values
   and source evidence. Download JSON/CSV or preview the full batch JSON in a dialog.

Use **Back to dashboard** at the top left to leave a batch without losing saved
progress. The workspace has Dashboard and Settings; an opened batch has Pipeline
and Batch jobs. Search and a separate class library are not exposed in the UI.
Settings manages the AI response cache and provides confirmed deletion of all data.
Entity/batch actions support deletion; deleting a batch preserves shared accepted classes.

## Data, privacy, and cache

| Local path | Contents | Commit to Git? |
| --- | --- | --- |
| `.data/` | SQLite workspace, uploaded audio, batch JSON snapshots, AI response cache | No |
| `.models/`, `.local/` | Downloaded/generated model artifacts | No |
| `.run/` | Process state, logs, scanner binaries and temporary scan artifacts | No |
| `.env*`, `.aws/`, `.streamlit/secrets.toml` | Local environment or credential material | No |
| `.env.example`, `.streamlit/config.toml` | Non-secret examples and shared UI settings | Yes |

Each batch is automatically mirrored to `.data/batches/<batch-id>.json`. SQLite is
the live store; snapshots are atomically replaced. Snapshots contain transcripts,
class/field definitions, assignments, results, job metadata, and local file references.
Exports and logs can contain private data even when they contain no API keys.

Bedrock Converse receives transcript text and class/field definitions, not raw audio.
Selecting Amazon Transcribe also uploads normalized audio to your configured S3
bucket for cloud transcription; Whisper keeps transcription local.
Selecting Azure Speech sends normalized audio directly to the configured Azure
Speech endpoint. It does not use the AWS bucket or create an Azure storage container.
Validated successful AI responses are cached locally using SHA-256 over the complete
request: transcript, prompts, definitions, model, region, and inference settings.
Identical requests reuse responses across restarts; explicit suggestion refresh bypasses
the cache. Changes to content or settings produce a different key. This is a local
response cache, separate from Bedrock prompt caching. Clear it in Settings if needed.

The app has no multiuser authentication. Keep it on localhost and review extracted
values; supporting quotes alone do not guarantee a correct interpretation.

## Tests and repository security

```powershell
.\.venv\Scripts\python.exe -m unittest discover -v
.\.venv\Scripts\python.exe scripts/security_check.py
.\.venv\Scripts\python.exe scripts/security_check.py --staged
.\.venv\Scripts\python.exe scripts/security_check.py --tracked --history
```

Tests use synthetic data and mocked AI/model operations; they need neither AWS
credentials nor model downloads. The security check runs Gitleaks plus a private-file
policy and checks for literal active environment-secret values. Staged mode inspects
Git's index, not just the current file on disk. Tracked mode also catches force-added
ignored files. Findings show locations/rule names with values hidden.

This temporary development repository has no GitHub Actions workflows or Dependabot
version-update configuration. Run tests and secret checks locally; the enabled local
commit/push hooks still protect Git operations without using GitHub-hosted runners.
Gitleaks is pinned and checksum verified. Enable GitHub secret scanning/push protection
where available. Hooks and scanners reduce risk; they cannot guarantee that all
secrets or personal data are detected. See [SECURITY.md](SECURITY.md) and
[CONTRIBUTING.md](CONTRIBUTING.md).

### First upload to a new GitHub repository

Create an empty repository in GitHub, then use its actual URL below. If this folder
is not already a Git repository, initialize it first:

```powershell
git init -b main
git config core.hooksPath .githooks
.\.venv\Scripts\python.exe scripts/security_check.py --install
git add .
git add --chmod=+x .githooks/pre-commit .githooks/pre-push
git diff --cached --stat
.\.venv\Scripts\python.exe scripts/security_check.py --staged
git commit -m "Initial project setup"
git remote add origin https://github.com/YOUR_ORG/audio-idp.git
git push -u origin main
```

Review the staged file list before committing. Use Git-based upload so ignore rules
and hooks apply; dragging the entire local folder into a browser can bypass them.
If any credential was previously committed, rotate it before publication and review
history cleanup with the repository owner. No license has been selected in this
project; the owner should choose one before offering it for third-party reuse.

## Troubleshooting

| Symptom | What to check |
| --- | --- |
| `ProfileNotFound` | Configure your own AWS **default** profile outside the checkout; run from your normal shell. |
| `ExpiredTokenException` | Refresh SSO/temporary credentials and retry the file or class job. |
| `AccessDeniedException` | Ask your AWS administrator to verify model access, inference-profile permissions, and destination-region/SCP restrictions. |
| Model is unavailable | Allow the initial public model download and retry transcription. |
| Amazon Transcribe fails | Check the AWS default profile, Transcribe and S3 permissions, and matching bucket/service regions. Retry reconnects to an existing AWS job when possible. |
| Port 8501 is occupied | Stop this app with `stop.ps1`, stop a manually launched instance with Ctrl+C, or choose another port. |
| JSON snapshot needs attention | Check local disk access/free space and use the dashboard retry control; SQLite data is preserved. |
| Security hook cannot run | Use Python 3.13, run `scripts/security_check.py --install`, and enable `.githooks` in this clone. |

## Project layout

```text
app.py                      Streamlit entry point
start.ps1 / stop.ps1         Windows process lifecycle
scripts/security_check.py   Local pre-commit/pre-upload security checks
.githooks/                   Opt-in local commit and push guards
audio_idp/
  domain/                   Definitions and storage contracts
  providers/                Whisper, Bedrock, and response-cache boundaries
  services/                 Individual processing operations and batch snapshots
  persistence/migrations/   SQLite storage and schema migrations
  workflow/                 Concurrent jobs, revision guards, orchestration
  ui/                       Dashboard, pipeline, job history, JSON dialog, Settings
test_*.py                   Offline unit and Streamlit UI tests
```

`core.py` keeps compatibility imports for processing callers. Backend modules do
not import Streamlit. Prompts are independent text files in `audio_idp/prompts/`.
