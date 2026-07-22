import { useMemo, useState } from "react";
import { NODE_LABELS } from "../theme";
import type { SearchEntry } from "../types";

interface Props {
  entries: SearchEntry[];
  onPick: (entry: SearchEntry) => void;
}

const MAX_RESULTS = 8;

export function SearchBar({ entries, onPick }: Props) {
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);

  const results = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (q === "") return [];
    const matches = (e: SearchEntry) =>
      e.label.toLowerCase().includes(q) ||
      (e.aliases ?? []).some((a) => a.toLowerCase().includes(q));
    return entries
      .filter(matches)
      .sort((a, b) => {
        // Label prefix matches first, then alias matches, then shorter labels.
        const ap = a.label.toLowerCase().startsWith(q) ? 0 : 1;
        const bp = b.label.toLowerCase().startsWith(q) ? 0 : 1;
        return ap - bp || a.label.length - b.label.length;
      })
      .slice(0, MAX_RESULTS);
  }, [entries, query]);

  function pick(entry: SearchEntry) {
    onPick(entry);
    setQuery("");
    setOpen(false);
  }

  return (
    <div className="search">
      <input
        className="search__input"
        type="search"
        value={query}
        placeholder="Search a condition, medication, or side effect…"
        onChange={(e) => {
          setQuery(e.target.value);
          setOpen(true);
        }}
        onFocus={() => setOpen(true)}
        // Delay so a result's onClick (which keeps focus via onMouseDown) still
        // fires before the list unmounts; an outside click closes it.
        onBlur={() => setTimeout(() => setOpen(false), 120)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && results.length > 0) pick(results[0]);
          if (e.key === "Escape") setOpen(false);
        }}
      />
      {open && results.length > 0 && (
        <ul className="search__results">
          {results.map((entry) => (
            <li key={entry.nodeId}>
              <button
                type="button"
                className="search__result"
                // preventDefault on mousedown keeps input focus (so the list
                // isn't torn down first); the actual pick happens on click.
                onMouseDown={(e) => e.preventDefault()}
                onClick={() => pick(entry)}
              >
                <span>{entry.label}</span>
                <span className="search__type">{NODE_LABELS[entry.type]}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
