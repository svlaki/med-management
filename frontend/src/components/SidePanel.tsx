import type { PanelSection } from "../types";

interface Props {
  title: string | null;
  subtitle: string;
  sections: PanelSection[];
  loading: boolean;
  error: string | null;
  onClose: () => void;
}

function formatCount(value: number | null | undefined): string {
  if (value === null || value === undefined) return "";
  return value.toLocaleString();
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
  sections,
  loading,
  error,
  onClose,
}: Props) {
  if (title === null) return null;

  const isEmpty = sections.every((s) => s.rows.length === 0);

  return (
    <aside className="side-panel">
      <div className="side-panel__header">
        <h2>{title}</h2>
        <button className="side-panel__close" onClick={onClose} aria-label="Close">
          ×
        </button>
      </div>
      {subtitle && <p className="side-panel__subtitle">{subtitle}</p>}

      {loading && <p className="side-panel__status">Loading…</p>}
      {error && <p className="side-panel__status side-panel__status--error">{error}</p>}

      {!loading && !error && (
        <>
          {sections.map((section) => (
            <section className="side-panel__section" key={section.heading}>
              <h3 className="side-panel__heading">{section.heading}</h3>
              <ul className="side-panel__list">
                {section.rows.map((row) =>
                  row.label !== undefined ? (
                    <li className="side-panel__row side-panel__row--kv" key={row.id}>
                      <span className="side-panel__key">{row.label}</span>
                      <span className="side-panel__value">{row.primary}</span>
                    </li>
                  ) : (
                    <li className="side-panel__row" key={row.id}>
                      <span className="side-panel__count">{formatCount(row.count)}</span>
                      <span className="side-panel__name">{row.primary}</span>
                      {row.note && <span className="side-panel__note">{row.note}</span>}
                      {row.badge !== undefined && (
                        <span className={badgeClass(row.badge)}>
                          {badgeLabel(row.badge)}
                        </span>
                      )}
                    </li>
                  ),
                )}
                {section.rows.length === 0 && (
                  <li className="side-panel__status">None recorded.</li>
                )}
              </ul>
            </section>
          ))}
          {isEmpty && sections.length === 0 && (
            <p className="side-panel__status">Nothing recorded.</p>
          )}
        </>
      )}
    </aside>
  );
}
