"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "./api/client";
import { ApiError, unwrap } from "./api/errors";
import type { Me } from "./api/types";

export const ME_KEY = ["me"] as const;

export function useMe() {
  return useQuery({
    queryKey: ME_KEY,
    queryFn: () => unwrap(api.GET("/api/v1/auth/me/")),
    retry: false,
    staleTime: 60_000,
  });
}

export function can(me: Me | undefined, permission: string): boolean {
  return Boolean(me?.access?.permissions.includes(permission));
}

/** Where to send a freshly signed-in user. */
export function landingPath(me: Me, next: string): string {
  return me.organization ? next : "/select-business";
}

export function isSignedOutError(error: unknown): boolean {
  return error instanceof ApiError && error.status === 401;
}

export function useLogin() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (credentials: { email: string; password: string }) => {
      await unwrap(api.POST("/api/v1/auth/login/", { body: { ...credentials, client: "web" } }));
      return queryClient.fetchQuery({
        queryKey: ME_KEY,
        queryFn: () => unwrap(api.GET("/api/v1/auth/me/")),
      });
    },
  });
}

export type SignupInput = {
  full_name: string;
  email: string;
  password: string;
  organization_name: string;
  store_name: string;
  currency: string;
  timezone: string;
};

export function useSignup() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (input: SignupInput) => {
      await unwrap(api.POST("/api/v1/auth/signup/", { body: { ...input, client: "web" } }));
      await queryClient.invalidateQueries({ queryKey: ME_KEY });
    },
  });
}

export function useSwitchOrganization() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (organizationId: string) => {
      await unwrap(
        api.POST("/api/v1/auth/switch-organization/", {
          body: { organization_id: organizationId },
        }),
      );
      queryClient.clear(); // nothing from the previous business may linger
    },
  });
}

export function useLogout() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (everywhere: boolean) => {
      const path = everywhere ? "/api/v1/auth/logout-all/" : "/api/v1/auth/logout/";
      try {
        await unwrap(api.POST(path));
      } catch (error) {
        if (!isSignedOutError(error)) throw error; // already signed out is fine
      }
      queryClient.clear();
    },
  });
}
