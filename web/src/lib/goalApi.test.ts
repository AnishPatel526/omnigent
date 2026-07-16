import { beforeEach, describe, expect, it, vi } from "vitest";
import { authenticatedFetch } from "./identity";
import { clearGoal, getGoal, setGoal, updateGoalStatus } from "./goalApi";

vi.mock("./identity", () => ({
  authenticatedFetch: vi.fn(),
}));

const mockAuthenticatedFetch = vi.mocked(authenticatedFetch);

function mockJsonResponse(
  body: unknown,
  init: { ok?: boolean; status?: number; statusText?: string } = {},
): Response {
  return {
    ok: init.ok ?? true,
    status: init.status ?? 200,
    statusText: init.statusText ?? "OK",
    json: async () => body,
  } as unknown as Response;
}

const WIRE_GOAL = {
  goal_id: "thread-1",
  objective: "Ship goal mode",
  status: "budgetLimited",
  token_budget: 40_000,
  tokens_used: 1_200,
  time_used_seconds: 125,
  created_at: 1,
  updated_at: 2,
};

describe("goal API", () => {
  beforeEach(() => {
    mockAuthenticatedFetch.mockReset();
  });

  it("reads the generic route and converts goal_id", async () => {
    mockAuthenticatedFetch.mockResolvedValueOnce(mockJsonResponse({ goal: WIRE_GOAL }));

    await expect(getGoal("conv a/b")).resolves.toEqual({
      goal: {
        goalId: "thread-1",
        objective: "Ship goal mode",
        status: "budgetLimited",
        tokenBudget: 40_000,
        tokensUsed: 1_200,
        timeUsedSeconds: 125,
        createdAt: 1,
        updatedAt: 2,
      },
    });
    expect(mockAuthenticatedFetch).toHaveBeenCalledWith("/v1/sessions/conv%20a%2Fb/goal");
  });

  it("sets, updates, and clears goals with generic wire payloads", async () => {
    mockAuthenticatedFetch
      .mockResolvedValueOnce(mockJsonResponse({ goal: WIRE_GOAL }))
      .mockResolvedValueOnce(mockJsonResponse({ goal: { ...WIRE_GOAL, status: "paused" } }))
      .mockResolvedValueOnce(mockJsonResponse({ cleared: true }));

    await setGoal("conv", { objective: "Do it", tokenBudget: null, status: "active" });
    await updateGoalStatus("conv", "paused");
    await expect(clearGoal("conv")).resolves.toEqual({ cleared: true });

    expect(mockAuthenticatedFetch).toHaveBeenNthCalledWith(
      1,
      "/v1/sessions/conv/goal",
      expect.objectContaining({
        method: "PUT",
        body: JSON.stringify({ objective: "Do it", token_budget: null, status: "active" }),
      }),
    );
    expect(mockAuthenticatedFetch).toHaveBeenNthCalledWith(
      2,
      "/v1/sessions/conv/goal/status",
      expect.objectContaining({ method: "PATCH", body: JSON.stringify({ status: "paused" }) }),
    );
    expect(mockAuthenticatedFetch).toHaveBeenNthCalledWith(
      3,
      "/v1/sessions/conv/goal",
      expect.objectContaining({ method: "DELETE" }),
    );
  });

  it("preserves omitted optional set fields", async () => {
    mockAuthenticatedFetch.mockResolvedValueOnce(mockJsonResponse({ goal: WIRE_GOAL }));

    await setGoal("conv", { objective: "Do it" });

    expect(mockAuthenticatedFetch).toHaveBeenCalledWith(
      "/v1/sessions/conv/goal",
      expect.objectContaining({
        body: JSON.stringify({ objective: "Do it" }),
      }),
    );
  });

  it("surfaces typed generic API errors", async () => {
    mockAuthenticatedFetch.mockResolvedValueOnce(
      mockJsonResponse(
        { error: { code: "goal_not_supported", message: "Goal mode is unavailable" } },
        { ok: false, status: 400, statusText: "Bad Request" },
      ),
    );

    await expect(getGoal("conv")).rejects.toMatchObject({
      status: 400,
      code: "goal_not_supported",
      message: "Goal mode is unavailable",
    });
  });
});
