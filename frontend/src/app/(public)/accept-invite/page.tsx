import type { Metadata } from "next";
import { Suspense } from "react";

import { AcceptInvite } from "./AcceptInvite";

export const metadata: Metadata = { title: "Accept invitation" };

export default function AcceptInvitePage() {
  return (
    <Suspense>
      <AcceptInvite />
    </Suspense>
  );
}
