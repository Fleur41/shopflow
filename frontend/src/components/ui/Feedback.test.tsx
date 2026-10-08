import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ApiError } from "@/lib/api/errors";

import { ErrorAlert } from "./Feedback";

describe("ErrorAlert", () => {
  it("shows the server message, a support reference and a fix for missing two-step verification", () => {
    render(
      <ErrorAlert
        error={new ApiError({ status: 403, code: "MFA_ENROLLMENT_REQUIRED", detail: "Turn on two-step verification.", request_id: "req-9" })}
      />,
    );

    expect(screen.getByRole("alert")).toHaveTextContent("Turn on two-step verification.");
    expect(screen.getByText("Reference: req-9")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Set up two-step verification" })).toHaveAttribute("href", "/account");
  });

  it("does not offer the link for other errors", () => {
    render(<ErrorAlert error={new ApiError({ status: 403, code: "PERMISSION_DENIED", detail: "No." })} />);

    expect(screen.queryByRole("link")).not.toBeInTheDocument();
  });
});
