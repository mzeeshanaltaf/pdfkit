import type { Metadata } from "next";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { APP_NAME } from "@/lib/constants";

export const metadata: Metadata = {
  title: "Admin login",
  robots: { index: false, follow: false },
};

const ERROR_MESSAGES: Record<string, string> = {
  invalid: "That username or password is not right.",
  throttled: "Too many attempts. Wait a while and try again.",
  not_configured: "Admin login is not configured on this deployment.",
  parse: "Invalid submission. Please try again.",
};

type Props = {
  searchParams: Promise<{ error?: string; next?: string }>;
};

/**
 * A plain, un-hydrated `<form>` — a login screen has nothing to progressively enhance, so
 * there is no client component here at all, nothing that can fail to hydrate.
 */
export default async function AdminLoginPage({ searchParams }: Props) {
  const { error, next } = await searchParams;
  const message = error ? (ERROR_MESSAGES[error] ?? "Something went wrong.") : null;

  return (
    <div className="flex min-h-svh items-center justify-center px-4">
      <Card className="w-full max-w-sm">
        <CardHeader>
          <CardTitle className="text-xl">{APP_NAME} admin</CardTitle>
        </CardHeader>
        <CardContent>
          <form
            action={`/api/admin/login${next ? `?next=${encodeURIComponent(next)}` : ""}`}
            method="post"
            className="space-y-4"
          >
            {message && (
              <p role="alert" className="rounded-md bg-destructive/10 px-3 py-2 text-sm text-destructive">
                {message}
              </p>
            )}
            <div className="space-y-1.5">
              <Label htmlFor="username">Username</Label>
              <Input id="username" name="username" autoComplete="username" required autoFocus />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="password">Password</Label>
              <Input
                id="password"
                name="password"
                type="password"
                autoComplete="current-password"
                required
              />
            </div>
            <Button type="submit" className="w-full">
              Sign in
            </Button>
          </form>
        </CardContent>
      </Card>
    </div>
  );
}
