"use client";

import { AlertCircle, Eye, EyeOff, ShieldCheck } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

export interface ProtectState {
  password: string;
  repeat: string;
}

export function createProtectState(): ProtectState {
  return { password: "", repeat: "" };
}

/** The CTA gate, shared by the panel's hint text and ToolShell's `canSubmit`. */
export function protectReady(state: ProtectState): boolean {
  return state.password.length > 0 && state.password === state.repeat;
}

interface ProtectOptionsProps {
  state: ProtectState;
  onChange: (next: ProtectState) => void;
}

export function ProtectOptions({ state, onChange }: ProtectOptionsProps) {
  const [visible, setVisible] = useState(false);

  // Only complain once there is something to compare against, so the panel does not greet
  // the user with an error the moment they start typing the first field.
  const mismatch = state.repeat.length > 0 && state.password !== state.repeat;

  const set = (patch: Partial<ProtectState>) => onChange({ ...state, ...patch });

  return (
    <div className="space-y-6">
      <section className="space-y-4">
        <h2 className="text-sm font-medium">Set a password</h2>

        <div className="space-y-2">
          <Label htmlFor="protect-password">Password</Label>
          <div className="relative">
            <Input
              id="protect-password"
              type={visible ? "text" : "password"}
              value={state.password}
              autoComplete="new-password"
              placeholder="Enter a password"
              className="h-10 pr-10"
              onChange={(event) => set({ password: event.target.value })}
            />
            <Button
              type="button"
              variant="ghost"
              size="icon-sm"
              className="absolute top-1 right-1"
              aria-label={visible ? "Hide password" : "Show password"}
              onClick={() => setVisible((current) => !current)}
            >
              {visible ? <EyeOff aria-hidden /> : <Eye aria-hidden />}
            </Button>
          </div>
        </div>

        <div className="space-y-2">
          <Label htmlFor="protect-repeat">Repeat password</Label>
          <Input
            id="protect-repeat"
            type={visible ? "text" : "password"}
            value={state.repeat}
            autoComplete="new-password"
            placeholder="Type it again"
            aria-invalid={mismatch || undefined}
            aria-describedby={mismatch ? "protect-mismatch" : undefined}
            className="h-10"
            onChange={(event) => set({ repeat: event.target.value })}
          />
          {mismatch && (
            <p id="protect-mismatch" className="flex items-center gap-1.5 text-sm text-destructive">
              <AlertCircle className="size-3.5 shrink-0" aria-hidden />
              The two passwords do not match.
            </p>
          )}
        </div>
      </section>

      <div className="flex gap-2.5 rounded-lg border border-amber-500/40 bg-amber-500/10 p-3.5 text-sm leading-relaxed">
        <ShieldCheck
          className="mt-0.5 size-4 shrink-0 text-amber-700 dark:text-amber-300"
          aria-hidden
        />
        <p>
          There is no way to recover this password. Nothing is stored here, so if you forget
          it the document cannot be opened again.
        </p>
      </div>
    </div>
  );
}
