import type { Metadata } from "next";

import { SignupForm } from "./SignupForm";

export const metadata: Metadata = { title: "Register your business" };

export default function SignupPage() {
  return <SignupForm />;
}
