import type { PanelRow } from "../types";

interface Props {
  title: string | null;
  subtitle: string;
  rows: PanelRow[];
  loading: boolean;
  error: string | null;
  onClose: () => void;
}

function formatCount(value: number | null): string {
  return value === null ? "—" : value.toLocaleString();
}

function badgeClass(confirmed: boolean | null | undefined): string {
  if (confirmed) return "badge badge--confirmed";
  if (confirmed === false) return "badge badge--faers";
  return "badge badge--unknown";
}

function badgeLabel(confirmed: boolean | null | undefined): string {
  if (confirmed) return "label";
  if (confirmed === false) return "faers-only";
  return "unchecked";
}

export function SidePanel({
  title,
  subtitle,
  rows,
  loading,
  error,
  onClose,
}: Props) {
  if (title === null) return null;

  return (
    <aside className="side-panel">
      <div className="side-panel__header">
        <h2>{title}</h2>
        <button className="side-panel__close" onClick={onClose} aria-label="Close">
          ×
        </button>
      </div>
      <p className="side-panel__subtitle">{subtitle}</p>

      {loading && <p className="side-panel__status">Loading…</p>}
      {error && <p className="side-panel__status side-panel__status--error">{error}</p>}

      {!loading && !error && (
        <ul className="side-panel__list">
          {rows.map((row) => (
            <li className="side-panel__row" key={row.id}>
              <span className="side-panel__count">{formatCount(row.count)}</span>
              <span className="side-panel__name">{row.primary}</span>
              {row.badge !== undefined && (
                <span className={badgeClass(row.badge)}>{badgeLabel(row.badge)}</span>
              )}
            </li>
          ))}
          {rows.length === 0 && (
            <li className="side-panel__status">Nothing recorded.</li>
          )}
        </ul>
      )}
    </aside>
  );
}
