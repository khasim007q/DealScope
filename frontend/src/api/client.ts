import type {
  CaseListItem,
  CaseView,
  CreateCaseRequest,
  CreateCaseResponse,
  EvidenceSummary,
  FaultOption,
  FeaturedCase,
  IdentityResult,
  Scenario,
  StatusResponse,
} from "./types";

export class ApiError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

const USE_MOCKS = import.meta.env.VITE_USE_MOCKS === "true";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(path, {
      ...init,
      headers: {
        Accept: "application/json",
        ...(init?.body ? { "Content-Type": "application/json" } : {}),
        ...(init?.headers ?? {}),
      },
    });
  } catch {
    throw new ApiError(
      "Could not reach the DealScope server. Check that it is running and try again.",
      0,
    );
  }
  if (!res.ok) {
    let detail = `Request failed (HTTP ${res.status}).`;
    try {
      const body: unknown = await res.json();
      if (body && typeof body === "object" && "detail" in body) {
        const d = (body as { detail: unknown }).detail;
        if (typeof d === "string" && d.length > 0) detail = d;
        else if (Array.isArray(d) && d.length > 0) {
          detail = d
            .map((item: unknown) =>
              item && typeof item === "object" && "msg" in item
                ? String((item as { msg: unknown }).msg)
                : String(item),
            )
            .join("; ");
        }
      }
    } catch {
      /* non-JSON error body: keep the generic message */
    }
    throw new ApiError(detail, res.status);
  }
  try {
    return (await res.json()) as T;
  } catch {
    throw new ApiError("The server returned an unreadable response.", res.status);
  }
}

function post<T>(path: string, body?: unknown): Promise<T> {
  return request<T>(path, {
    method: "POST",
    body: body === undefined ? undefined : JSON.stringify(body),
  });
}

// Mocks are loaded lazily and only when VITE_USE_MOCKS is "true"; the condition is a
// build-time constant so production bundles drop the mock code entirely.
const loadMocks = () => import("../mocks/mockApi");

export const api = {
  status: async (): Promise<StatusResponse> =>
    USE_MOCKS ? (await loadMocks()).status() : request<StatusResponse>("/api/status"),
  scenarios: async (): Promise<Scenario[]> =>
    USE_MOCKS ? (await loadMocks()).scenarios() : request<Scenario[]>("/api/scenarios"),
  faults: async (): Promise<FaultOption[]> =>
    USE_MOCKS ? (await loadMocks()).faults() : request<FaultOption[]>("/api/faults"),
  identityCheck: async (domains: string[]): Promise<IdentityResult[]> =>
    USE_MOCKS
      ? (await loadMocks()).identityCheck(domains)
      : post<IdentityResult[]>("/api/identity-check", { domains }),
  createCase: async (req: CreateCaseRequest): Promise<CreateCaseResponse> =>
    USE_MOCKS ? (await loadMocks()).createCase() : post<CreateCaseResponse>("/api/cases", req),
  resumeCase: async (id: string): Promise<CreateCaseResponse> =>
    USE_MOCKS
      ? (await loadMocks()).createCase()
      : post<CreateCaseResponse>(`/api/cases/${encodeURIComponent(id)}/resume`),
  listCases: async (): Promise<CaseListItem[]> =>
    USE_MOCKS ? (await loadMocks()).listCases() : request<CaseListItem[]>("/api/cases"),
  getCase: async (id: string): Promise<CaseView> =>
    USE_MOCKS
      ? (await loadMocks()).getCase(id)
      : request<CaseView>(`/api/cases/${encodeURIComponent(id)}`),
  cancelCase: async (id: string): Promise<CreateCaseResponse> =>
    USE_MOCKS
      ? (await loadMocks()).cancelCase(id)
      : post<CreateCaseResponse>(`/api/cases/${encodeURIComponent(id)}/cancel`),
  featured: async (): Promise<FeaturedCase[]> =>
    USE_MOCKS ? (await loadMocks()).featured() : request<FeaturedCase[]>("/api/featured"),
  evidenceSummary: async (): Promise<EvidenceSummary> =>
    USE_MOCKS
      ? (await loadMocks()).evidenceSummary()
      : request<EvidenceSummary>("/api/evidence-summary"),
  reportUrl: (id: string): string => `/api/cases/${encodeURIComponent(id)}/report.md`,
  bundleUrl: (id: string): string => `/api/cases/${encodeURIComponent(id)}/bundle.json`,
};

export function errorMessage(e: unknown): string {
  if (e instanceof Error) return e.message;
  return "Something went wrong.";
}
