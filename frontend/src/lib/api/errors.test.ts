import { describe, expect, it } from "vitest";

import { ApiError, toApiError, unwrap } from "./errors";

describe("ApiError", () => {
  it("maps JSON pointers to form fields, first message wins", () => {
    const error = toApiError(
      {
        status: 400,
        code: "VALIDATION_ERROR",
        detail: "One or more fields are invalid.",
        errors: [
          { pointer: "/email", code: "INVALID", detail: "Enter a valid email address." },
          { pointer: "/store_ids/0", code: "DOES_NOT_EXIST", detail: "Unknown store." },
          { pointer: "/email", code: "TAKEN", detail: "Second message." },
          { pointer: "", code: "INVALID", detail: "Totals do not match." },
        ],
      },
      400,
    );

    expect(error.fieldErrors()).toEqual({
      email: "Enter a valid email address.",
      store_ids: "Unknown store.",
      _form: "Totals do not match.",
    });
  });

  it("never shows raw non-problem bodies (e.g. an HTML error page)", () => {
    const error = toApiError("<html>502 Bad Gateway</html>", 502);

    expect(error.code).toBe("UNEXPECTED_RESPONSE");
    expect(error.message).not.toContain("html");
  });
});

describe("unwrap", () => {
  it("turns network failures into a readable error", async () => {
    await expect(unwrap(Promise.reject(new TypeError("Failed to fetch")))).rejects.toMatchObject({
      code: "NETWORK_ERROR",
    });
  });

  it("returns data on success and throws ApiError on problems", async () => {
    const ok = new Response("{}", { status: 200 });
    await expect(unwrap(Promise.resolve({ data: { a: 1 }, response: ok }))).resolves.toEqual({ a: 1 });

    const denied = new Response("{}", { status: 403 });
    const problem = { status: 403, code: "PERMISSION_DENIED", detail: "No." };
    await expect(unwrap(Promise.resolve({ error: problem, response: denied }))).rejects.toBeInstanceOf(ApiError);
  });
});
