import { type ReactNode, useState } from "react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";

export const MIN_REASON = 10;

export interface ConfirmWithReasonProps {
  title: string;
  description: string;
  confirmLabel: string;
  /** Palabra que hay que escribir para los cambios grandes. */
  requireWord?: string;
  onConfirm: (reason: string) => void;
  trigger: ReactNode;
}

export function ConfirmWithReason({
  title,
  description,
  confirmLabel,
  requireWord,
  onConfirm,
  trigger,
}: ConfirmWithReasonProps) {
  const [open, setOpen] = useState(false);
  const [reason, setReason] = useState("");
  const [word, setWord] = useState("");
  const valid =
    reason.trim().length >= MIN_REASON &&
    (!requireWord || word === requireWord);

  function submit() {
    onConfirm(reason.trim());
    setOpen(false);
    setReason("");
    setWord("");
  }

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>{trigger}</DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          <DialogDescription>{description}</DialogDescription>
        </DialogHeader>
        <div className="grid gap-2">
          <Label htmlFor="confirm-reason">
            Motivo (mínimo {MIN_REASON} caracteres)
          </Label>
          <Textarea
            id="confirm-reason"
            value={reason}
            onChange={(e) => setReason(e.target.value)}
          />
        </div>
        {requireWord ? (
          <div className="grid gap-2">
            <Label htmlFor="confirm-word">
              Escribe <strong>{requireWord}</strong> para continuar
            </Label>
            <Input
              id="confirm-word"
              value={word}
              onChange={(e) => setWord(e.target.value)}
              autoComplete="off"
            />
          </div>
        ) : null}
        <DialogFooter>
          <DialogClose asChild>
            <Button variant="secondary">Cancelar</Button>
          </DialogClose>
          <Button disabled={!valid} onClick={submit}>
            {confirmLabel}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
