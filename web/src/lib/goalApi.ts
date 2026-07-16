import { authenticatedFetch } from "./identity";
import { ApiError } from "./sessionsApi";

interface GoalWire {
  goal_id: string;
  objective: string;
  status: string;
  token_budget?: number | null;
  tokens_used: number;
  time_used_seconds: number;
  created_at?: number | null;
  updated_at?: number | null;
}

interface GoalResponseWire {
  goal: GoalWire | null;
}

/** Browser-facing goal state shared by goal-capable session backends. */
export interface Goal {
  goalId: string;
  objective: string;
  status: string;
  tokenBudget: number | null;
  tokensUsed: number;
  timeUsedSeconds: number;
  createdAt: number | null;
  updatedAt: number | null;
}

export interface GoalResponse {
  goal: Goal | null;
}

export interface SetGoalInput {
  objective: string;
  tokenBudget?: number | null;
  status?: GoalStatusUpdate | null;
}

export type GoalStatusUpdate = "active" | "paused";

async function goalApiErrorFromResponse(res: Response): Promise<ApiError> {
  let message = `${res.status} ${res.statusText}`;
  let code: string | null = null;
  try {
    const body = (await res.json()) as {
      detail?: string;
      error?: string | { code?: string; message?: string };
    };
    if (typeof body.error === "string") {
      code = body.error;
      if (typeof body.detail === "string") message = body.detail;
    } else {
      if (body.error?.message) message = body.error.message;
      if (body.error?.code) code = body.error.code;
    }
  } catch {
    // Non-JSON / empty body - keep the status-line fallback.
  }
  return new ApiError(message, res.status, code);
}

async function readJsonOrThrow<T>(res: Response): Promise<T> {
  if (!res.ok) throw await goalApiErrorFromResponse(res);
  return (await res.json()) as T;
}

function goalFromWire(wire: GoalWire): Goal {
  return {
    goalId: wire.goal_id,
    objective: wire.objective,
    status: wire.status,
    tokenBudget: wire.token_budget ?? null,
    tokensUsed: wire.tokens_used,
    timeUsedSeconds: wire.time_used_seconds,
    createdAt: wire.created_at ?? null,
    updatedAt: wire.updated_at ?? null,
  };
}

function goalResponseFromWire(wire: GoalResponseWire): GoalResponse {
  return { goal: wire.goal == null ? null : goalFromWire(wire.goal) };
}

export async function getGoal(sessionId: string): Promise<GoalResponse> {
  const res = await authenticatedFetch(`/v1/sessions/${encodeURIComponent(sessionId)}/goal`);
  return goalResponseFromWire(await readJsonOrThrow<GoalResponseWire>(res));
}

export async function setGoal(sessionId: string, goal: SetGoalInput): Promise<GoalResponse> {
  const body: Record<string, string | number | null> = { objective: goal.objective };
  if (goal.tokenBudget !== undefined) body.token_budget = goal.tokenBudget;
  if (goal.status !== undefined) body.status = goal.status;
  const res = await authenticatedFetch(`/v1/sessions/${encodeURIComponent(sessionId)}/goal`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return goalResponseFromWire(await readJsonOrThrow<GoalResponseWire>(res));
}

export async function updateGoalStatus(
  sessionId: string,
  status: GoalStatusUpdate,
): Promise<GoalResponse> {
  const res = await authenticatedFetch(
    `/v1/sessions/${encodeURIComponent(sessionId)}/goal/status`,
    {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ status }),
    },
  );
  return goalResponseFromWire(await readJsonOrThrow<GoalResponseWire>(res));
}

export async function clearGoal(sessionId: string): Promise<{ cleared: boolean }> {
  const res = await authenticatedFetch(`/v1/sessions/${encodeURIComponent(sessionId)}/goal`, {
    method: "DELETE",
  });
  return readJsonOrThrow<{ cleared: boolean }>(res);
}
