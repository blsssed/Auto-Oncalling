import type { AiopsDiagnosticEvidenceChain } from "@agent-py/api-contracts";

export interface ReplayRecording {
  readonly version: 1;
  readonly provenance: "cls-tool-run";
  readonly title: string;
  readonly injectedFault: boolean;
  readonly chain: AiopsDiagnosticEvidenceChain;
}

export function parseRecording(value: unknown): ReplayRecording {
  if (!value || typeof value !== "object") throw new Error("录制格式无效");
  const item = value as Record<string, unknown>;
  const chain = item.chain as AiopsDiagnosticEvidenceChain | undefined;
  if (item.version !== 1 || item.provenance !== "cls-tool-run" || typeof item.title !== "string"
      || typeof item.injectedFault !== "boolean" || !chain || !chain.task
      || !Array.isArray(chain.steps) || !Array.isArray(chain.evidence) || !Array.isArray(chain.reports)
      || !Array.isArray(chain.toolCalls)) throw new Error("录制缺少真实工具来源或诊断数据");
  return item as unknown as ReplayRecording;
}

export function replayChain(recording: ReplayRecording, step: number): AiopsDiagnosticEvidenceChain {
  const steps = recording.chain.steps.slice(0, Math.max(0, step));
  const visibleIds = new Set(steps.map(item => item.id));
  const evidence = recording.chain.evidence.filter(item => item.stepId === null || visibleIds.has(item.stepId));
  const toolIds = new Set(evidence.map(item => item.toolCallId));
  const complete = step >= recording.chain.steps.length;
  return { ...recording.chain, steps, evidence,
    toolCalls: recording.chain.toolCalls.filter(item => toolIds.has(item.id)),
    reports: complete ? recording.chain.reports : [],
    reportEvidenceLinks: complete ? recording.chain.reportEvidenceLinks : [],
    checkpoints: [] };
}
