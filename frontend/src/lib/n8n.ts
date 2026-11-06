/**
 * Links from an automation run back into n8n.
 *
 * n8n addresses an execution under its workflow - `/workflow/<workflowId>/executions/<id>` -
 * so the link needs to know which workflow ran. The workflow ids are fixed at import
 * (`n8n/build_workflows.py`), and the run's name says which one called back:
 * replenishment only comes from the event router, reconciliation only from the nightly
 * sweeps. An aging sweep can come from either, so it opens n8n's executions list.
 */

const WORKFLOW_FOR_RUN: Record<string, string> = {
  "low-stock-replenishment": "PGAInventoryRouter",
  "daily-reconciliation": "PGAInventorySweeps",
};

export function n8nExecutionUrl(base: string, workflowName: string, executionId: string): string {
  const root = base.replace(/\/$/, "");
  const workflowId = WORKFLOW_FOR_RUN[workflowName];
  return workflowId ? `${root}/workflow/${workflowId}/executions/${executionId}` : `${root}/home/executions`;
}
