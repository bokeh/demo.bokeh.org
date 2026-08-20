# Public monitor data source and privacy boundary

`/monitor` has two views. The whole-service section combines sanitized reports
from every fresh demo task. The serving-task section shows faster local samples
from the ECS task handling the browser session.

## Measurement scopes

| Measurement | Whole-service scope | Serving-task scope |
| --- | --- | --- |
| CPU | Sum in vCPUs and capacity-weighted percentage | Current task percentage |
| Memory | Sum of bytes and task capacities | Current task bytes and percentage |
| Network | Sum of current task receive/send rates | Current task receive/send rate |
| Open sessions | Sum of open Bokeh documents | Current Python process |
| Page entries | Sum of demo page entries per minute | Current Python process |
| Callback timing | Merged 60-second task histograms | Current Python process |
| Event-loop lag | Merged 60-second task histograms | Current Python process |

An open session is a Bokeh document, not a unique person. Page entries count
gallery and demo page visits. They exclude static assets, health checks, and the
monitor itself. Cloudflare may serve static assets without contacting the demo
service.

## Production sources

Each process samples its ECS task from the injected, link-local metadata v4
`/task/stats` endpoint. The adapter ignores response keys and all string fields.
It retains CPU counters, memory usage, network byte counters or rates, and the
numeric task limits supplied by the task definition. It never calls `/task` or
`/taskWithTags`.

Once every 30 seconds, each process writes one sanitized heartbeat to the
dedicated DynamoDB table named by `DEMO_MONITOR_TABLE`. It then scans the same
table for reports no more than 75 seconds old. The process caches the resulting
service sample, so opening or refreshing `/monitor` does not make an AWS call.
The application starts this exchange loop with the ASGI lifespan and stops it
during shutdown.

Heartbeat rows expire after three minutes. The reader checks timestamps itself
because DynamoDB TTL deletion is asynchronous. A row contains a random
publisher key, timestamps, numeric aggregates, public catalog routes, and
allowlisted callback names. The publisher key stays in DynamoDB and is excluded
from the scan projection and browser model.

## Timing aggregation

The callback and event-loop collectors keep bounded 60-second process windows.
They convert durations into fixed millisecond buckets before publication. The
service view sums matching buckets and calculates an approximate global p95.
This avoids the incorrect practice of averaging each task's p95.

The service tables contain no more than eight app rows and twelve named callback
rows. Routes must exist in the public catalog. Callback names must also appear
in the source-code allowlist. The decoder rejects an entire heartbeat if either
kind of label fails validation.

## Browser contract

The Bokeh document may contain only timestamps, numeric measurements, generic
status text, public catalog routes, and allowlisted callback names. It must not
contain AWS account IDs, ARNs, resource names, endpoint URIs, credentials,
task or container identifiers, raw logs, source IPs, user agents, referrers,
request headers, or query strings.

The DynamoDB payload follows the same boundary. It is compressed to keep each
write below 1 KiB under the configured row limits, but compression is not a
privacy control. Validation before writing and again after reading is the
privacy control.

## Update and cost controls

Serving-task plots poll the process cache every two seconds and retain 90 points
with `ColumnDataSource.stream`. System sampling is coalesced across viewers.
The service publisher and reader run once per process every 30 seconds, even
when no monitor page is open.

At the four-task maximum, the service performs about 346,000 heartbeat writes
per month. Compact on-demand DynamoDB writes and coalesced scans are expected to
cost well below one US dollar per month. The design has no Lambda function,
scheduled job, custom metric, Logs Insights query, public CloudWatch access, or
new network path.

## Local and deterministic modes

Without ECS metadata or `DEMO_MONITOR_TABLE`, automatic mode uses real process
CPU, resident memory, activity, and timing measurements with an in-memory
heartbeat store. Local Linux containers also expose network counters when
available. This mode needs no AWS credentials.

Set `DEMO_MONITOR_SOURCE=deterministic` to generate repeatable serving-task data
and three simulated service reports. The page labels both sections as simulated.
`DEMO_MONITOR_GLOBAL_SOURCE=local` forces the in-memory store, while
`DEMO_MONITOR_GLOBAL_SOURCE=dynamodb` requires `DEMO_MONITOR_TABLE`.

If the live task adapter fails, the serving-task section uses a labeled
deterministic fallback. A fallback sample is not published to the live service
aggregate. If the heartbeat exchange fails or all rows are stale, the service
section reports a degraded state with a generic reason and leaves local task
measurements available.

## Deployment order

The Infra change creates the table and task role and grants the GitHub deployment
role permission to pass that task role. Apply that reviewed change before merging
an application release containing `taskRoleArn` and `DEMO_MONITOR_TABLE`.
