"use client";

import { AlertCircle, Eye, EyeOff, Lock } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import type { PasswordPrompt } from "@/lib/api";

interface PromptState {
  filename: string;
  /** A password was already tried on this file and rejected. */
  retry: boolean;
  /** A password has been handed back and is being tried; the dialog waits rather than closing. */
  pending: boolean;
}

export interface PasswordPromptApi {
  /** Hand this to `uploadWithPassword`. */
  requestPassword: PasswordPrompt;
  /** Close the dialog once the run is over, however it ended. */
  dismissPrompt: () => void;
  /** Render this somewhere inside the workspace. */
  passwordDialog: React.ReactNode;
}

/**
 * The per-file password prompt behind Unlock.
 *
 * The dialog stays mounted between attempts on purpose: a rejected password re-enters
 * `requestPassword` with `retry: true`, and keeping the same dialog open lets that show as
 * an inline error under the field instead of a toast and a fresh, contextless prompt.
 */
export function usePasswordPrompt(): PasswordPromptApi {
  const [prompt, setPrompt] = useState<PromptState | null>(null);
  // The resolver is a side channel rather than part of the state: it must be callable from
  // an event handler without going through a state updater, which React may run twice.
  const resolveRef = useRef<((password: string | null) => void) | null>(null);

  const requestPassword = useCallback<PasswordPrompt>(
    (request) =>
      new Promise<string | null>((resolve) => {
        resolveRef.current = resolve;
        setPrompt({ filename: request.filename, retry: request.retry, pending: false });
      }),
    [],
  );

  const submit = useCallback((password: string) => {
    resolveRef.current?.(password);
    resolveRef.current = null;
    setPrompt((current) => (current ? { ...current, pending: true } : current));
  }, []);

  const close = useCallback(() => {
    // A no-op once a password has been submitted, which is what makes this safe to call
    // unconditionally when the run ends.
    resolveRef.current?.(null);
    resolveRef.current = null;
    setPrompt(null);
  }, []);

  return {
    requestPassword,
    dismissPrompt: close,
    passwordDialog: <PasswordDialog prompt={prompt} onSubmit={submit} onCancel={close} />,
  };
}

interface PasswordDialogProps {
  prompt: PromptState | null;
  onSubmit: (password: string) => void;
  onCancel: () => void;
}

function PasswordDialog({ prompt, onSubmit, onCancel }: PasswordDialogProps) {
  return (
    <Dialog open={prompt !== null} onOpenChange={(open) => !open && onCancel()}>
      <DialogContent showCloseButton={false}>
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Lock className="size-4 text-brand" aria-hidden />
            Password needed
          </DialogTitle>
          <DialogDescription>
            <span className="font-medium text-foreground">{prompt?.filename}</span> is protected.
            Enter the password you use to open it — it is sent once, for this file, and never
            stored.
          </DialogDescription>
        </DialogHeader>

        {prompt && (
          // Keyed on the file, so moving to the next document starts from an empty field
          // rather than offering the previous file's password.
          <PasswordForm
            key={prompt.filename}
            retry={prompt.retry}
            pending={prompt.pending}
            onSubmit={onSubmit}
            onCancel={onCancel}
          />
        )}
      </DialogContent>
    </Dialog>
  );
}

interface PasswordFormProps {
  retry: boolean;
  pending: boolean;
  onSubmit: (password: string) => void;
  onCancel: () => void;
}

function PasswordForm({ retry, pending, onSubmit, onCancel }: PasswordFormProps) {
  const [password, setPassword] = useState("");
  const [visible, setVisible] = useState(false);
  const field = useRef<HTMLInputElement>(null);

  // A rejected password is left in the field — it is usually a typo away from right, and
  // retyping a long one from scratch is worse — but selected, so replacing it is one
  // keystroke either way.
  useEffect(() => {
    if (retry) field.current?.select();
  }, [retry]);

  return (
    <form
      className="space-y-2"
      onSubmit={(event) => {
        event.preventDefault();
        if (password) onSubmit(password);
      }}
    >
      <Label htmlFor="pdf-password">Password</Label>
      <div className="relative">
        <Input
          id="pdf-password"
          ref={field}
          type={visible ? "text" : "password"}
          value={password}
          autoFocus
          autoComplete="off"
          disabled={pending}
          aria-invalid={retry || undefined}
          aria-describedby={retry ? "pdf-password-error" : undefined}
          className="h-10 pr-10"
          onChange={(event) => setPassword(event.target.value)}
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

      {retry && (
        <p id="pdf-password-error" className="flex items-center gap-1.5 text-sm text-destructive">
          <AlertCircle className="size-3.5 shrink-0" aria-hidden />
          That password did not open the file. Try again.
        </p>
      )}

      <DialogFooter className="mt-4">
        <Button type="button" variant="ghost" onClick={onCancel}>
          Cancel
        </Button>
        <Button type="submit" disabled={!password || pending}>
          {pending ? "Checking" : "Unlock"}
        </Button>
      </DialogFooter>
    </form>
  );
}
