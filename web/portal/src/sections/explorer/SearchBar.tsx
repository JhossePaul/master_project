import { Search } from "lucide-react";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

const MIN = 3;
const MAX = 300;

/** Búsqueda semántica: la consulta no se guarda ni se pone en la URL. */
export function SearchBar({
  busy,
  onSearch,
}: {
  busy: boolean;
  onSearch: (query: string) => void;
}) {
  const [value, setValue] = useState("");
  const valid = value.trim().length >= MIN;
  return (
    <search aria-label="Búsqueda semántica">
      <form
        className="flex flex-wrap items-center gap-2"
        onSubmit={(event) => {
          event.preventDefault();
          if (valid) onSearch(value.trim());
        }}
      >
        <label htmlFor="busqueda" className="sr-only">
          Describe el problema que buscas
        </label>
        <Input
          id="busqueda"
          className="min-w-80 flex-1"
          placeholder="Describe el problema que buscas (por ejemplo: no llega el código para entrar)"
          value={value}
          maxLength={MAX}
          autoComplete="off"
          onChange={(event) => setValue(event.target.value)}
        />
        <Button type="submit" disabled={!valid || busy}>
          <Search aria-hidden="true" />
          {busy ? "Buscando…" : "Buscar"}
        </Button>
      </form>
    </search>
  );
}
