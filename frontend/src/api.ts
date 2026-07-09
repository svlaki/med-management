import type {
  ConditionInfo,
  GraphPayload,
  MedicationCause,
  SideEffectReport,
} from "./types";

interface ApiResponse<T> {
  success: boolean;
  data: T | null;
  error: string | null;
}

const BASE = "/api";

async function getData<T>(path: string): Promise<T> {
  const response = await fetch(`${BASE}${path}`);
  if (!response.ok) {
    let message = `Request failed (${response.status})`;
    try {
      const body = (await response.json()) as ApiResponse<never>;
      if (body.error) message = body.error;
    } catch {
      // non-JSON error body; keep the status message
    }
    throw new Error(message);
  }
  const body = (await response.json()) as ApiResponse<T>;
  if (!body.success || body.data === null) {
    throw new Error(body.error ?? "Empty response");
  }
  return body.data;
}

export function fetchConditions(): Promise<ConditionInfo[]> {
  return getData<ConditionInfo[]>("/conditions");
}

export function fetchConditionGraph(
  conditionId: string,
  confirmedOnly: boolean,
  perMed: number,
): Promise<GraphPayload> {
  const params = new URLSearchParams({
    confirmed_only: String(confirmedOnly),
    per_med: String(perMed),
  });
  return getData<GraphPayload>(`/conditions/${conditionId}/graph?${params}`);
}

export function fetchSideEffects(
  rxcui: string,
  confirmedOnly: boolean,
): Promise<SideEffectReport[]> {
  const params = new URLSearchParams({
    confirmed_only: String(confirmedOnly),
    limit: "25",
  });
  return getData<SideEffectReport[]>(
    `/medications/${encodeURIComponent(rxcui)}/side-effects?${params}`,
  );
}

export function fetchMedicationsForSideEffect(
  sideEffectId: string,
): Promise<MedicationCause[]> {
  return getData<MedicationCause[]>(
    `/side-effects/${encodeURIComponent(sideEffectId)}/medications`,
  );
}
