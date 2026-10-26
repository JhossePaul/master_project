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
export const MAX_REASON = 500;
export const MAX_TICKET = 100;

export interface ConfirmWithReasonProps {
  title: string;
  description: string;
  confirmLabel: string;
  /** Palabra que hay que escribir para los cambios grandes. */
  requireWord?: string;
  /** Agrega un campo opcional de ticket y lo entrega como segundo argumento. */
  withTicket?: boolean;
  onConfirm: (reason: string, ticket?: string) => void;
  trigger: ReactNode;
}

export function ConfirmWithReason({
  title,
  description,
  confirmLabel,
  requireWord,
  withTicket = false,
  onConfirm,
  trigger,
}: ConfirmWithReasonProps) {
  const [open, setOpen] = useState(false);
  const [reason, setReason] = useState("");
  const [word, setWord] = useState("");
  const [ticket, setTicket] = useState("");
  const valid =
    reason.trim().length >= MIN_REASON &&
    (!requireWord || word === requireWord);

  function submit() {
    if (withTicket) onConfirm(reason.trim(), ticket.trim());
    else onConfirm(reason.trim());
    setOpen(false);
    setReason("");
    setWord("");
    setTicket("");
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
            maxLength={MAX_REASON}
            onChange={(e) => setReason(e.target.value)}
          />
        </div>
        {withTicket ? (
          <div className="grid gap-2">
            <Label htmlFor="confirm-ticket">Ticket (opcional)</Label>
            <Input
              id="confirm-ticket"
              value={ticket}
              maxLength={MAX_TICKET}
              onChange={(e) => setTicket(e.target.value)}
              autoComplete="off"
            />
          </div>
        ) : null}
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
