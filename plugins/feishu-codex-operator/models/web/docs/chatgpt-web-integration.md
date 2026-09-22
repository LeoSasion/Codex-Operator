# ChatGPT Web integration

The saved Web service uses a Python Responses boundary, a dedicated Electron browser and a fixed MCP connection. Native tools are returned to Codex Desktop for execution with their original identities and approvals. A browser answer or MCP delivery alone is not evidence of successful execution.

First setup: follow [fixed connection and login](web-fixed-tunnel.md), then [the quick start](../../../QUICKSTART.md). Existing login and app bindings are reused. The service exposes bounded local status; explicit assistance opens the helper when required. No account credentials or runtime state are included in releases.

The independent provider has HTTP and stream retries disabled. Web-owned terminal failures use a non-retrying HTTP 400 envelope that retains the original cause and partial-tool facts. Authentication and capacity boundaries remain distinct. Input is not truncated or summarized to fit limits. Failed and uncertain requests are not replayed.

Known limitations: cold-page timeout, context/task-selection failures in long histories, and missing main-window global integration. Registering a provider does not create or bind a new native task. Current source supports the explicit setup components; their presence is not a claim of automatic end-to-end onboarding or production stability.

For architecture and attribution see [implementation sources](web-background-sources.md), [model routing](../../common/docs/model-router.md) and [native experience](native-web-experience.md). Private diagnostic histories are retained by the owner and excluded from this source package.
