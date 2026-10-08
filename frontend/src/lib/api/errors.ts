/** API errors: every failure becomes an ApiError carrying the server's problem details. */

export type ProblemError = {
  pointer: string;
  code: string;
  detail?: string;
  meta?: Record<string, unknown>;
};

export type Problem = {
  status: number;
  code: string;
  title?: string;
  detail: string;
  errors?: ProblemError[];
  request_id?: string | null;
};

export class ApiError extends Error {
  readonly problem: Problem;

  constructor(problem: Problem) {
    super(problem.detail);
    this.name = "ApiError";
    this.problem = problem;
  }

  get code(): string {
    return this.problem.code;
  }

  get status(): number {
    return this.problem.status;
  }

  get requestId(): string | null {
    return this.problem.request_id ?? null;
  }

  /** Field messages keyed by form field name ("/store_ids/0" -> "store_ids"). */
  fieldErrors(): Record<string, string> {
    const fields: Record<string, string> = {};
    for (const error of this.problem.errors ?? []) {
      const field = error.pointer.split("/").filter(Boolean)[0] ?? "_form";
      if (!(field in fields) && error.detail) fields[field] = error.detail;
    }
    return fields;
  }
}

export function isProblem(value: unknown): value is Problem {
  return (
    typeof value === "object" &&
    value !== null &&
    typeof (value as Problem).code === "string" &&
    typeof (value as Problem).detail === "string"
  );
}

export const NETWORK_ERROR: Problem = {
  status: 0,
  code: "NETWORK_ERROR",
  detail: "Can't reach ShopFlow. Check your internet connection and try again.",
};

export function toApiError(body: unknown, status: number): ApiError {
  if (isProblem(body)) return new ApiError({ ...body, status: body.status ?? status });
  return new ApiError({
    status,
    code: "UNEXPECTED_RESPONSE",
    detail: "Something went wrong. Please try again.",
  });
}

type FetchResult<T> = { data?: T; error?: unknown; response: Response };

/** Await an openapi-fetch call and return its data, or throw an ApiError. */
export async function unwrap<T>(call: Promise<FetchResult<T>>): Promise<T> {
  let result: FetchResult<T>;
  try {
    result = await call;
  } catch {
    throw new ApiError(NETWORK_ERROR);
  }
  if (result.error !== undefined || !result.response.ok) {
    throw toApiError(result.error, result.response.status);
  }
  return result.data as T;
}
