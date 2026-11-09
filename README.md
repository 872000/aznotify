# aznotify

A serverless notification API on Azure Functions (Python). Send one HTTP
request and a notification — email, SMS, or push — is validated, queued,
and delivered asynchronously by a queue-triggered worker.

```
POST /api/notify  ──validate──▶  notifications queue  ──▶  queue trigger ──▶ sender
                                                                     │
                                                              console (default)
                                                              smtp / twilio / firebase (stubs)
```

## What it does

- **HTTP trigger** (`POST /api/notify`): accepts `{recipient, channel,
  message, subject?}`, validates it, and enqueues it. Returns `202
  Accepted` with the notification id, or `400` with every validation
  problem found.
- **Queue trigger**: picks each queued notification up and delivers it
  through a pluggable sender. Transient failures are retried (up to 5
  attempts); after that — or on a permanent failure — the message is
  moved to the `notifications-poison` dead-letter queue instead of being
  retried forever. Unparseable or invalid messages are dropped (logged),
  never retried.
- **Pluggable senders** (`aznotify/senders.py`): the default `ConsoleSender`
  just logs the notification, so the app runs anywhere with no credentials
  and no cloud spend. SMTP, Twilio, and Firebase senders exist as
  clearly-marked stubs that raise `NotImplementedError` with the exact
  configuration they need — implement one and select it with
  `AZNOTIFY_SENDER`.

### Channels and validation

| Channel | Recipient format |
| ------- | ---------------- |
| `email` | valid email address, e.g. `parth@example.com` |
| `sms`   | E.164 phone number, e.g. `+14165551234` |
| `push`  | device token, at least 8 characters |

`message` is required (1–1000 characters); `subject` is optional
(max 200 characters).

### Example request

```bash
curl -X POST http://localhost:7071/api/notify \
  -H "Content-Type: application/json" \
  -d '{"recipient": "parth@example.com", "channel": "email",
       "subject": "Hello", "message": "Your order shipped!"}'
```

```json
{"id": "3f2a…", "status": "queued", "queue": "notifications",
 "channel": "email", "recipient": "parth@example.com"}
```

## Project layout

```
function_app.py            Azure Functions entry points (HTTP + queue triggers)
aznotify/
  models.py                Notification model + payload validation (pure Python)
  senders.py               Sender protocol, ConsoleSender, provider stubs
  queue.py                 Queue names, JSON serialisation, retry rules
  processing.py            Queue-trigger decision logic (send / retry / dead-letter)
host.json                  Functions host config (queue batch size, maxDequeueCount 5)
local.settings.json        Local dev settings — placeholder values only, no secrets
requirements.txt           azure-functions, azure-storage-queue
infra/
  main.bicep               Function App (Consumption) + Storage queues + App Insights
  main.parameters.json     Deploy parameters (canadacentral, dev)
tests/                     Offline pytest suite (fakes only, no Azure)
```

## Run locally

Prerequisites: Python 3.12, [Azure Functions Core Tools](https://learn.microsoft.com/azure/azure-functions/functions-run-local)
and [Azurite](https://learn.microsoft.com/azure/storage/common/storage-use-azurite)
(or any local storage emulator) for the queue.

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
pip install pytest            # test-only dependency

# Start Azurite (the storage emulator) in another terminal:
azurite --silent --location /tmp/azurite --debug /tmp/azurite/debug.log

func start
```

Then POST to `http://localhost:7071/api/notify`. The console sender logs
each delivery to the terminal — no real email/SMS is ever sent.

> `local.settings.json` ships with placeholder values only
> (`AzureWebJobsStorage: UseDevelopmentStorage=true`). Never put a real
> connection string or provider credential in it; set real settings with
> `az functionapp config appsettings set` after deploying (see below).

## Test

```bash
python -m pytest -q
```

The suite is fully offline: HTTP validation, queue processing, the sender
interface, and retry/dead-letter handling are all exercised with fakes
and mocks. No Azure credentials, no network, no cloud spend.

## Deploy to Azure

Prerequisites: [Azure CLI](https://learn.microsoft.com/cli/azure/install-azure-cli)
logged in (`az login`) with a subscription selected.

```bash
# 1. Create the resource group (canadacentral shown; pick your region)
az group create --name aznotify-rg --location canadacentral

# 2. Provision the Function App, Storage queues, and Application Insights
az deployment group create \
  --resource-group aznotify-rg \
  --template-file infra/main.bicep \
  --parameters infra/main.parameters.json

# 3. Publish the function code (from the repo root)
func azure functionapp publish aznotify-dev-func --python
```

The Bicep template wires the storage connection string and Application
Insights keys into the Function App's settings automatically, and sets
`AZNOTIFY_SENDER=console` by default. To use a real provider, implement
its stub in `aznotify/senders.py` first, then update the app setting:

```bash
az functionapp config appsettings set \
  --resource-group aznotify-rg --name aznotify-dev-func \
  --settings AZNOTIFY_SENDER=smtp SMTP_HOST=… SMTP_USER=…
```

Check the poison queue for failed deliveries:

```bash
az storage message peek --queue-name notifications-poison \
  --account-name aznotifydevsa --auth-mode login
```

To tear everything down: `az group delete --name aznotify-rg`.

## Caveats

- The SMTP, Twilio, and Firebase senders are **stubs**: selecting one
  before implementing it raises `NotImplementedError`. The console sender
  is the only working sender out of the box.
- The Bicep template provisions a Consumption (`Y1`) plan, so the app
  scales to zero and you pay only per execution — but the Storage account
  and Application Insights still exist as billable resources while the
  resource group lives.
- No authentication is configured on the HTTP trigger (`ANONYMOUS`):
  add Easy Auth or a function key before exposing it publicly.

## License

MIT — see [LICENSE](LICENSE).
