"use client";

import { useQuery } from "@tanstack/react-query";

import { Badge, ErrorAlert, Loading, PageHeader } from "@/components/ui/Feedback";
import { api } from "@/lib/api/client";
import { unwrap } from "@/lib/api/errors";
import { ROLES_KEY } from "@/lib/query-keys";

export default function RolesPage() {
  const roles = useQuery({ queryKey: ROLES_KEY, queryFn: () => unwrap(api.GET("/api/v1/roles/")) });

  return (
    <>
      <PageHeader title="Roles" description="What each role can do. Owners always have full access." />
      {roles.isPending && <Loading label="Loading roles…" />}
      {roles.error && <ErrorAlert error={roles.error} title="Couldn't load roles" />}
      <ul className="flex flex-col gap-3">
        {roles.data?.results.map((role) => (
          <li key={role.id} className="rounded-lg bg-white p-5 ring-1 ring-slate-200">
            <div className="flex flex-wrap items-center gap-2">
              <h2 className="text-lg font-semibold">{role.name}</h2>
              {role.is_system && <Badge>System role</Badge>}
              <span className="text-sm text-slate-600">{role.permissions.length} permissions</span>
            </div>
            {role.description && <p className="mt-1 text-slate-700">{role.description}</p>}
            <details>
              <summary className="cursor-pointer py-3 text-sm font-medium text-emerald-800">Show permissions</summary>
              <ul className="mt-2 grid gap-1 font-mono text-xs text-slate-700 sm:grid-cols-2 lg:grid-cols-3">
                {role.permissions.map((code) => (
                  <li key={code}>{code}</li>
                ))}
              </ul>
            </details>
          </li>
        ))}
      </ul>
    </>
  );
}
