# Public monitor data source and privacy boundary

`/monitor` is an intentionally small teaching view of the server currently
serving its Bokeh session. It is not an operations dashboard and does not claim
to describe the whole ECS service.

## Measurement scopes

| Measurement | Production scope | Local scope |
| --- | --- | --- |
| CPU and memory | Current serving ECS task | Current Python process |
| Network receive/send rate | Current serving ECS task | Local container when available |
| Callback rate and p95 duration | Current Python process | Current Python process |
| Callback latency by app and slowest named callbacks | Current Python process | Current Python process |
| Event-loop lag p95 and app breakdown | Current Python process | Current Python process |

Another ECS task may serve another visitor. Service-wide task count, request
rate, errors, and load-balancer measurements remain private operational data and
are not inferred or shown.

## Production source

The application reads the automatically injected, link-local ECS task metadata
v4 `/task/stats` endpoint. It does not use AWS credentials or make an AWS API
request. The adapter ignores response keys and identity-bearing fields and
allowlists only these numeric inputs:

- cumulative CPU usage, system CPU usage, and online CPU count;
- current memory usage;
- cumulative or precomputed network receive/send byte rates; and
- the numeric task CPU and memory limits supplied by the task definition.

The application never calls `/task`, `/taskWithTags`, CloudWatch, Logs Insights,
or a public AWS endpoint. In particular, `/taskWithTags` is excluded because it
requires IAM permission and can make ECS API calls.

The numeric task limits are duplicated in the deployment template so the app
can normalize measurements without reading the identity-rich task metadata
response. Keep them aligned with the task definition's `cpu` and `memory`
values when changing task size.

## Browser contract

The Bokeh document contains timestamps, numeric measurements, fixed generic
source labels, public routes already listed in the site catalog, and callback
identifiers from an explicit allowlist of functions in this public repository.
An unknown route or callback label is discarded before it can enter a public
snapshot. The document contains no AWS account IDs, ARNs, resource names,
endpoint URI, credentials, task/container IDs, raw logs, source IPs, user
agents, referrers, request headers, or query strings.

Existing callback-duration and event-loop-lag instrumentation feeds bounded
60-second process aggregates. Sessions and log identity are always discarded.
Only catalog routes and explicitly allowlisted code-level callback names can be
retained for the three performance tables. Event-loop observations are
coalesced to at most one per process-wide one-second bucket for the headline
metric and one per public route per second for the route breakdown.

## Update and cost controls

Every monitor session asks for a point every two seconds. A process-wide sampler
performs at most one source read in that interval and shares the same generation
with all viewers. Sessions skip duplicate generations and append one numeric row
with `ColumnDataSource.stream`; browser history rolls over after 90 points. The
small table snapshots are capped at eight app rows and twelve callback rows;
their underlying in-memory samples also have fixed upper bounds.

The link-local metadata endpoint is provided with the running Fargate task. The
monitor adds no custom metrics, scheduled compute, log queries, storage pipeline,
or public CloudWatch access, so it has no meaningful recurring AWS cost. It does
add the small bounded CPU and WebSocket traffic needed to render the public app.

## Local and deterministic modes

Without `ECS_CONTAINER_METADATA_URI_V4`, `auto` mode uses real process CPU and
resident-memory measurements. Container network counters are used on local
Linux containers when available; an unavailable network series remains empty.
No AWS credentials are needed.

Set `DEMO_MONITOR_SOURCE=deterministic` for repeatable presentation data. The UI
labels that mode as simulated. If a selected live adapter fails, the monitor also
uses a generic, clearly labeled deterministic fallback rather than exposing an
exception or endpoint detail to the browser.
