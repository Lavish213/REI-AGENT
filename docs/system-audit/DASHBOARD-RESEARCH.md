# Ten-dashboard comparison

Primary-source desk research, not authenticated screenshot or performance benchmarking. Preserve Karpathys domain and governance; adapt patterns only where they solve an operator task.

| Dashboard | Primary source | Applicable pattern |
|---|---|---|
| Linear | https://linear.app/docs/dashboards | Focused shared views and actionable drill-downs. |
| Stripe | https://support.stripe.com/questions/dashboard-home-page-charts-for-business-insights | Real business metrics with explicit periods; no invented history. |
| HubSpot | https://www.hubspot.com/products/reporting-dashboards | Pipeline reporting beside follow-up work. |
| Salesforce | https://trailhead.salesforce.com/content/learn/modules/lex_implementation_reports_dashboards/lex_implementation_reports_dashboards_visualizing_data | Permission-aware summaries connected to underlying reports. |
| Grafana | https://grafana.com/docs/grafana/latest/dashboards/build-dashboards/best-practices/ | Consistent scopes, hierarchy, freshness and error context. |
| Datadog | https://docs.datadoghq.com/dashboards/template_variables/ | Shared filters prevent mixing unrelated calls and periods. |
| Sentry | https://docs.sentry.io/product/dashboards/ | Summary-to-evidence investigation with context preserved. |
| Vercel | https://vercel.com/docs/observability | Operational health with time-scoped drill-downs. |
| Retool | https://retool.com/resources/build-your-first-dashboard-in-retool | UI controls connected to queries and genuine outcomes. |
| Pipedrive | https://support.pipedrive.com/en/article/insights-dashboard | Pipeline/activity views prioritize the next action. |

Proposed design contract: prioritize work needing attention; stable navigation groups calls, lead pipeline, appointments/callbacks and system health. Keep loading/error/empty/stale distinct. Charts state source/period. Unmapped calls expose no other session. Preserve current tokens/components. Colors, contrast, keyboard/focus and responsive layout require actual screenshots and interaction testing before a visual redesign is graded.
