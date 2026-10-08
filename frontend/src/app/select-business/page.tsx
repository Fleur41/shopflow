"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";

import { Button } from "@/components/ui/Button";
import { EmptyState, ErrorAlert, Loading } from "@/components/ui/Feedback";
import { isSignedOutError, useMe, useSwitchOrganization } from "@/lib/auth";

export default function SelectBusinessPage() {
  const router = useRouter();
  const me = useMe();
  const switchOrganization = useSwitchOrganization();

  useEffect(() => {
    if (isSignedOutError(me.error)) router.replace("/login");
  }, [me.error, router]);

  async function choose(organizationId: string) {
    const ok = await switchOrganization.mutateAsync(organizationId).then(() => true, () => false);
    if (ok) router.replace("/");
  }

  return (
    <main id="main" className="mx-auto w-full max-w-md px-4 py-12">
      <h1 className="mb-6 text-2xl font-bold">Choose a business</h1>
      {me.isPending && <Loading />}
      {switchOrganization.error && <ErrorAlert error={switchOrganization.error} />}
      {me.data && me.data.organizations.length === 0 && (
        <EmptyState title="You don’t belong to any business yet">Ask a business owner to add you as staff.</EmptyState>
      )}
      <ul className="flex flex-col gap-3">
        {me.data?.organizations.map((membership) => (
          <li key={membership.organization_id}>
            <Button
              variant="secondary"
              className="w-full justify-between"
              loading={switchOrganization.isPending && switchOrganization.variables === membership.organization_id}
              onClick={() => choose(membership.organization_id)}
            >
              <span>{membership.organization_name}</span>
              <span className="font-normal text-slate-600">{membership.role}</span>
            </Button>
          </li>
        ))}
      </ul>
    </main>
  );
}
