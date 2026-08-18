# Production operations

The application repository owns container releases. The `bokeh/infra`
repository owns the ECS service, load balancer, ECR repository, IAM roles, and
other AWS resources. A routine application release does not require Terraform.

## Automated release

Pull requests run the Python checks, tests, and a local container build. They do
not publish images or change AWS.

Every merge to `main` starts the **Publish and deploy** workflow. It:

1. assumes `demo-bokeh-org-github-deploy` through GitHub OIDC;
2. builds a Linux ARM64 image and pushes the immutable `sha-<commit>` tag to ECR;
3. resolves that tag to an image digest;
4. registers a new `demo-bokeh-org` task-definition revision;
5. updates ECS service `demo-bokeh-org/worker` and waits for stability; and
6. requests `https://demo.bokeh.org/healthz` before reporting success.

Allow several minutes for an uncached ARM64 build and the ECS connection-drain
period. The first end-to-end production rehearsal took about nine minutes; a
previously published commit skips the image build.

The workflow summary records the deployed digest. In AWS, follow the rollout at
**ECS → Clusters → demo-bokeh-org → Services → worker → Deployments**. The
**Events** tab reports task-start, target-registration, and rollback failures.
Application output is in CloudWatch log group `/ecs/demo-bokeh-org`.

After the workflow succeeds, open the landing page and at least one streaming
application. A useful smoke test is `/spectrum-monitor`: let the waterfall run,
change a filter, and confirm that the page continues updating over its WebSocket.

The expected health response is
`{"status":"ok","python_gil":"disabled"}`. The endpoint still returns HTTP 200
when the application can serve traffic but the requested free-threaded mode was
lost. In that case it reports `status` as `degraded`, `reason` as
`python_gil_enabled`, and the active `python_gil` state as `enabled`.

To roll back, revert the change on `main`. For a faster emergency rollback,
rerun a previously successful **Publish and deploy** workflow; its immutable
commit image can be reused without rebuilding.

## Performance telemetry

Every application records Python callback duration and event-loop scheduling
lag per browser session. Summaries are emitted as compact JSON once per minute
and when a session closes. The instrumentation does not send metrics through
the Bokeh document or add anything to the page. Set `DEMO_PERFORMANCE=0` to
disable both callback wrapping and the one-second lag observer locally. Normal
idle lag windows are suppressed; callback-active windows and lag spikes are
retained.

Callback records use event `demo.callback` and include `app`, `callback`,
`count`, `mean_ms`, `p95_ms`, and `max_ms`. Event-loop records use
`demo.event_loop_lag` and the same timing fields. A lag spike means work in the
process kept the session's one-second observer from running on schedule.

The Terraform-managed CloudWatch dashboard `demo-bokeh-org-performance`
summarizes callback p95 and maximum duration, event-loop lag by app, and the
slowest named callbacks over the selected time range. Its Logs Insights queries
run when the dashboard loads or refreshes.

For raw records, open **CloudWatch → Logs Insights**, select
`/ecs/demo-bokeh-org`, and use:

```text
fields @timestamp, app, callback, count, mean_ms, p95_ms, max_ms
| filter event = "demo.callback"
| sort p95_ms desc
| limit 100
```

For scheduling lag:

```text
fields @timestamp, app, count, mean_ms, p95_ms, max_ms
| filter event = "demo.event_loop_lag"
| sort p95_ms desc
| limit 100
```

Compare those session-level measurements with:

- **ECS service metrics** for aggregate CPU and memory;
- **ALB TargetResponseTime** for document and HTTP response latency;
- **ALB HTTPCode_Target_5XX_Count** and ECS service events for failures; and
- task count and capacity provider in the ECS service when autoscaling occurs.

Low aggregate CPU does not rule out a slow callback. A single session can block
on an expensive calculation while the service-wide five-minute average remains
small. Start with callback p95 and maximum duration, then check whether the same
window has event-loop lag or an ALB latency spike.
