import {
  useCallback, useEffect, useMemo, useRef, useState,
  type KeyboardEvent as ReactKeyboardEvent, type ReactNode,
} from 'react';
import { ChevronDown, ChevronUp, ChevronsUpDown } from 'lucide-react';
import { SkeletonBar } from './primitives';

/* ============================================================================
   DATA GRID

   Implemented from context/UI_SPEC.md §3. Dense enterprise table: 28px rows,
   a 30px sticky header, hairline rules and no card chrome.

   THE FOUR RULES THIS FILE EXISTS TO ENFORCE

   1. `table-layout: fixed` with every column width declared. Auto layout
      means any data update can reflow every column, and a column that
      reflows on an SSE frame reads as instability on video.
   2. Row height comes from an explicit height, never from padding. Padding-
      driven heights change with content and are the root cause of most
      layout shift.
   3. Loading RESERVES space. A skeleton is a geometric clone of the loaded
      state — same row height, same count, same column x-positions — so the
      transition to data moves nothing. A skeleton whose shape differs from
      the content merely relocates the shift.
   4. Numbers are right-aligned, tabular, and monospaced. Text is
      left-aligned. Nothing is ever centred in a table.

   Sorting is client-side because every collection in Interdict fits
   comfortably in memory.
   ============================================================================ */

export type Density = 'dense' | 'compact' | 'comfortable';

const ROW_H: Record<Density, number> = { dense: 24, compact: 28, comfortable: 32 };
const ROW_FONT: Record<Density, string> = {
  dense: 'text-mini',
  compact: 'text-mini',
  comfortable: 'text-xs',
};

/** Varied so a skeleton block does not read as a barcode. */
const SKELETON_WIDTHS = [68, 84, 56, 76, 62, 88];

export interface Column<T> {
  key: string;
  header: string;
  width?: string;
  align?: 'left' | 'right';
  /** Right-aligns AND applies the mono/tabular treatment. Prefer this to `align`. */
  numeric?: boolean;
  sortable?: boolean;
  /** Sort value. A column without one is not sortable in practice. */
  value?: (row: T) => string | number;
  /** Full text for the cell's `title`, since cells truncate. */
  title?: (row: T) => string;
  /** Tooltip on the column header — e.g. the timezone, stated once. */
  headerTitle?: string;
  render: (row: T) => ReactNode;
}

interface Props<T> {
  columns: Column<T>[];
  rows: T[];
  rowKey: (row: T) => string;
  /** Also bound to Enter / Space on a focused row. */
  onSelect?: (row: T) => void;
  selectedKey?: string | null;
  empty?: ReactNode;
  defaultSort?: { key: string; dir: 'asc' | 'desc' };
  density?: Density;
  loading?: boolean;
  /** How many skeleton rows to reserve. Should match a typical page. */
  skeletonRows?: number;
  /** Accessible name for the grid. Required when there is no visible caption. */
  label?: string;
  /** Optional per-row left rail, e.g. severity. Drawn INSIDE the row. */
  rowRail?: (row: T) => string | undefined;
}

export function DataGrid<T>({
  columns, rows, rowKey, onSelect, selectedKey, empty, defaultSort,
  density, loading = false, skeletonRows = 12, label, rowRail,
}: Props<T>) {
  const [sort, setSort] = useState(defaultSort ?? null);
  const [focusKey, setFocusKey] = useState<string | null>(null);
  const bodyRef = useRef<HTMLTableSectionElement>(null);

  const d: Density = density ?? 'compact';
  const rowH = ROW_H[d];

  const sorted = useMemo(() => {
    if (!sort) return rows;
    const col = columns.find((c) => c.key === sort.key);
    if (!col?.value) return rows;
    const read = col.value;
    return [...rows].sort((a, b) => {
      const av = read(a);
      const bv = read(b);
      const cmp = typeof av === 'number' && typeof bv === 'number'
        ? av - bv
        : String(av).localeCompare(String(bv));
      return sort.dir === 'asc' ? cmp : -cmp;
    });
  }, [rows, sort, columns]);

  const keys = useMemo(() => sorted.map(rowKey), [sorted, rowKey]);

  // Exactly one row is tabbable at all times. Rows are keyed by id, so the
  // roving stop survives a data refresh — a selection that jumps when a new
  // case arrives destroys trust instantly.
  const tabKey = useMemo(() => {
    if (focusKey && keys.includes(focusKey)) return focusKey;
    if (selectedKey && keys.includes(selectedKey)) return selectedKey;
    return keys[0] ?? null;
  }, [focusKey, selectedKey, keys]);

  useEffect(() => {
    if (focusKey && !keys.includes(focusKey)) setFocusKey(null);
  }, [keys, focusKey]);

  const focusRowAt = useCallback((index: number) => {
    const clamped = Math.max(0, Math.min(keys.length - 1, index));
    const key = keys[clamped];
    if (!key) return;
    setFocusKey(key);
    const el = bodyRef.current?.querySelector<HTMLTableRowElement>(
      `[data-rowkey="${CSS.escape(key)}"]`,
    );
    el?.focus();
    el?.scrollIntoView({ block: 'nearest' });
  }, [keys]);

  const toggle = (key: string) =>
    setSort((prev) =>
      prev?.key === key
        ? { key, dir: prev.dir === 'asc' ? 'desc' : 'asc' }
        : { key, dir: 'desc' },
    );

  const onRowKeyDown = (e: ReactKeyboardEvent<HTMLTableRowElement>, row: T, index: number) => {
    switch (e.key) {
      case 'ArrowDown': case 'j': e.preventDefault(); focusRowAt(index + 1); break;
      case 'ArrowUp': case 'k': e.preventDefault(); focusRowAt(index - 1); break;
      case 'Home': e.preventDefault(); focusRowAt(0); break;
      case 'End': e.preventDefault(); focusRowAt(keys.length - 1); break;
      case 'PageDown': e.preventDefault(); focusRowAt(index + 10); break;
      case 'PageUp': e.preventDefault(); focusRowAt(index - 10); break;
      case 'Enter': case ' ':
        e.preventDefault();
        onSelect?.(row);
        break;
      default: break;
    }
  };

  const colgroup = (
    <colgroup>
      {columns.map((c) => (
        <col key={c.key} style={c.width ? { width: c.width } : undefined} />
      ))}
    </colgroup>
  );

  const header = (
    <thead className="sticky top-0 z-[2] bg-[var(--color-surface)]">
      <tr className="rule-b">
        {columns.map((c) => {
          const right = c.numeric || c.align === 'right';
          const sortable = !!c.sortable && !!c.value;
          const dir = sort?.key === c.key ? sort.dir : null;
          return (
            <th
              key={c.key}
              scope="col"
              title={c.headerTitle}
              // Present on EVERY sortable column, "none" when unsorted.
              aria-sort={
                sortable
                  ? dir === 'asc' ? 'ascending' : dir === 'desc' ? 'descending' : 'none'
                  : undefined
              }
              className={`label-micro h-[30px] px-2 first:pl-3 last:pr-3 align-middle font-semibold
                ${right ? 'text-right' : 'text-left'}
                ${sortable ? 'cursor-pointer select-none hover:text-[var(--color-brass-text)]' : ''}`}
              onClick={sortable ? () => toggle(c.key) : undefined}
            >
              {sortable ? (
                // Focusable: a grid whose only sort affordance is a mouse is
                // not sortable at all for a keyboard. Enter/Space activate the
                // button natively; stopPropagation keeps the <th> handler from
                // firing a second toggle on the same click.
                <button
                  type="button"
                  aria-label={`Sort by ${c.header}`}
                  onClick={(e) => { e.stopPropagation(); toggle(c.key); }}
                  className={`group inline-flex items-center gap-1
                    ${right ? 'flex-row-reverse' : ''}`}
                >
                  {c.header}
                  {dir === 'asc'
                    ? <ChevronUp aria-hidden size={10} strokeWidth={2.5} />
                    : dir === 'desc'
                      ? <ChevronDown aria-hidden size={10} strokeWidth={2.5} />
                      : <ChevronsUpDown aria-hidden size={10} strokeWidth={2}
                          className="opacity-0 transition-opacity duration-100
                            group-hover:opacity-60 group-focus-visible:opacity-60" />}
                </button>
              ) : (
                <span className={`inline-flex items-center ${right ? 'flex-row-reverse' : ''}`}>
                  {c.header}
                </span>
              )}
            </th>
          );
        })}
      </tr>
    </thead>
  );

  /* --- loading: a geometric clone, never a spinner, never a collapse ------ */
  if (loading) {
    return (
      <table
        aria-label={label}
        aria-busy="true"
        className={`w-full table-fixed border-collapse ${ROW_FONT[d]}`}
      >
        {colgroup}
        {header}
        {/* Static. A skeleton RESERVES space; it does not shimmer. A pulsing
            skeleton is a second infinite animation competing with the one
            sanctioned live indicator in the chrome (§10). */}
        <tbody>
          {Array.from({ length: skeletonRows }, (_, i) => (
            <tr key={i} style={{ height: rowH }} className="rule-b-muted">
              {columns.map((c, ci) => (
                <td key={c.key} className="px-2 first:pl-3 last:pr-3">
                  {/* Varied widths so it does not read as a barcode. */}
                  <SkeletonBar
                    width={`${SKELETON_WIDTHS[(i + ci) % SKELETON_WIDTHS.length] ?? 72}%`}
                  />
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    );
  }

  return (
    <table
      aria-label={label}
      aria-rowcount={sorted.length}
      className={`w-full table-fixed border-collapse ${ROW_FONT[d]}`}
    >
      {colgroup}
      {header}
      {/* An empty result keeps its column structure. Replacing the whole table
          with a centred message drops the headers, so the columns appear to
          move when the first row lands. */}
      {sorted.length === 0 && empty ? (
        <tbody>
          <tr>
            <td colSpan={columns.length} className="px-3 align-top">{empty}</td>
          </tr>
        </tbody>
      ) : (
      <tbody ref={bodyRef}>
        {sorted.map((row, index) => {
          const key = keys[index] ?? rowKey(row);
          const selected = key === selectedKey;
          const rail = rowRail?.(row);
          const interactive = !!onSelect;
          return (
            <tr
              key={key}
              data-rowkey={key}
              aria-selected={interactive ? selected : undefined}
              aria-rowindex={index + 1}
              style={{ height: rowH }}
              tabIndex={interactive ? (key === tabKey ? 0 : -1) : undefined}
              onFocus={interactive ? () => setFocusKey(key) : undefined}
              onClick={onSelect ? () => onSelect(row) : undefined}
              onKeyDown={interactive ? (e) => onRowKeyDown(e, row, index) : undefined}
              className={`rule-b-muted outline-none transition-colors duration-100 ease-[var(--ease-ui)]
                ${interactive ? 'cursor-pointer' : ''}
                ${selected
                  ? 'bg-[var(--color-overlay)] shadow-[inset_2px_0_0_0_var(--color-brass)]'
                  : rail
                    ? `${rail} hover:bg-[var(--color-raised)]`
                    : 'hover:bg-[var(--color-raised)]'}
                focus-visible:shadow-[var(--shadow-focus-inset)]`}
            >
              {columns.map((c) => {
                const right = c.numeric || c.align === 'right';
                return (
                  <td
                    key={c.key}
                    title={c.title?.(row)}
                    className={`truncate px-2 first:pl-3 last:pr-3 align-middle
                      ${right ? 'text-right' : 'text-left'}
                      ${c.numeric ? 'font-mono tabular' : ''}`}
                  >
                    {c.render(row)}
                  </td>
                );
              })}
            </tr>
          );
        })}
      </tbody>
      )}
    </table>
  );
}
