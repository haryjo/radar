"use client";

import { Eye, EyeOff, KeyRound, ShieldCheck, Trash2 } from "lucide-react";
import { useState } from "react";
import { api, type SecretInfo } from "@/lib/api";
import { useToast } from "./toast";
import { Button } from "./ui";

/** Saisie d'une clé API : écriture seule. La valeur n'est jamais relue depuis le serveur,
 *  on n'affiche que sa provenance et ses 4 derniers caractères. */
export function KeyField({ secret, onChange, placeholder }: {
  secret: SecretInfo;
  onChange: (next: SecretInfo) => void;
  placeholder?: string;
}) {
  const toast = useToast();
  const [value, setValue] = useState("");
  const [visible, setVisible] = useState(false);
  const [saving, setSaving] = useState(false);
  const [editing, setEditing] = useState(!secret.set);

  async function save() {
    setSaving(true);
    try {
      const next = await api<SecretInfo>(`/api/secrets/${secret.name}`, { method: "PUT", body: JSON.stringify({ value }) });
      onChange(next);
      setValue("");
      setEditing(false);
      toast(`Clé ${secret.label} enregistrée (chiffrée).`);
    } catch (e) {
      toast((e as Error).message, "error");
    } finally {
      setSaving(false);
    }
  }

  async function remove() {
    try {
      const next = await api<SecretInfo>(`/api/secrets/${secret.name}`, { method: "DELETE" });
      onChange(next);
      setEditing(!next.set);
      toast(next.set ? `Clé de l'app supprimée : celle de .env (${next.env}) reprend le relais.` : "Clé supprimée.");
    } catch (e) {
      toast((e as Error).message, "error");
    }
  }

  if (!editing && secret.set) {
    return (
      <div className="flex flex-wrap items-center gap-2 text-[12px]">
        <span className="inline-flex items-center gap-1.5 rounded-lg bg-success/10 px-2 py-1 text-success">
          <ShieldCheck className="size-3.5" />
          Clé {secret.hint} · {secret.source === "app" ? "enregistrée dans l'app (chiffrée)" : `fichier .env (${secret.env})`}
        </span>
        <button onClick={() => setEditing(true)} className="text-muted hover:text-ink">Remplacer</button>
        {secret.source === "app" && (
          <button onClick={remove} className="inline-flex items-center gap-1 text-muted hover:text-danger">
            <Trash2 className="size-3" />Supprimer
          </button>
        )}
      </div>
    );
  }

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        if (value.trim()) save();
      }}
      className="flex gap-1.5"
    >
      <div className="relative min-w-0 flex-1">
        <KeyRound className="pointer-events-none absolute left-2.5 top-2 size-4 text-muted" />
        <input
          type={visible ? "text" : "password"}
          value={value}
          onChange={(e) => setValue(e.target.value)}
          placeholder={placeholder ?? `Colle ta clé ${secret.label}`}
          autoComplete="off"
          spellCheck={false}
          className="h-8 w-full rounded-lg border border-line bg-surface pl-8 pr-8 font-mono text-[12px] outline-none focus:border-accent"
        />
        <button type="button" onClick={() => setVisible((v) => !v)} className="absolute right-2 top-2 text-muted hover:text-ink" aria-label={visible ? "Masquer" : "Afficher"}>
          {visible ? <EyeOff className="size-4" /> : <Eye className="size-4" />}
        </button>
      </div>
      <Button size="sm" variant="primary" type="submit" disabled={!value.trim()} loading={saving}>Enregistrer la clé</Button>
      {secret.set && <Button size="sm" variant="ghost" type="button" onClick={() => { setEditing(false); setValue(""); }}>Annuler</Button>}
    </form>
  );
}
