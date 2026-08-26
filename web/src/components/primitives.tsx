import {
  useCallback, useEffect, useRef, useState,
  type CSSProperties, type KeyboardEvent as ReactKeyboardEvent,
  type ReactNode, type RefObject,
} from 'react';
import { Check, Copy } from 'lucide-react';
import type { CaseState, Outcome, Verdict } from '@/lib/types';
import { money, stateLabel } from '@/lib/format';

/* ============================================================================
   PRIMITIVES

   Implemented from context/UI_SPEC.md. If this file and that document
   disagree, the document wins and this file is wrong.

   GEOMETRY. Control ladder 20 / 24 / 30 / 40, chrome 50, pane header 30,
   table row 28. A 4px unit. Nothing here is 32px or 36px tall.

   ELEVATION. Hairlines are inset box-shadows, not borders — a border changes
   layout size and cannot stack with a shadow. Every raised surface is a ring
   plus one or two long-throw drop shadows, and levels 1-4 carry a sub-pixel
   top-edge sheen. That sheen is what makes a dark panel read as lit rather
   than as a flat gray rectangle.

   COLOUR. --oxblood means money is being stopped. It appears on `contradicts`
   findings and on BLOCK, and nowhere else in the interface. Amber is
   held/awaiting/dormant. Verdigris is released/confirmed. Brass is structure
   — labels, rules, active state, focus — and never a terminal status.
   ============================================================================ */

export type Tone = 'neutral' | 'brass' | 'amber' | 'verdigris' | 'oxblood';
export type Elevation = 0 | 1 | 2 | 3 | 4;

export const cx = (...parts: (string | false | null | undefined)[]) =>
  parts.filter(Boolean).join(' ');

/* --- tone tables ---------------------------------------------------------
   The `-text` step is the ONLY value permitted for text on a dark surface;
   it clears 4.5:1 on --color-raised. The base value is for fills, rails,
   dots and 1px edges, never for text. */

export const TONE_TEXT: Record<Tone, string> = {
  neutral: 'text-[var(--color-ink-dim)]',
  brass: 'text-[var(--color-brass-text)]',
  amber: 'text-[var(--color-amber-text)]',
  verdigris: 'text-[var(--color-verdigris-text)]',
  oxblood: 'text-[var(--color-oxblood-text)]',
};

const TONE_EDGE: Record<Tone, string> = {
  neutral: 'border-[var(--color-rule-strong)]',
  brass: 'border-[var(--color-brass-dim)]',
  amber: 'border-[var(--color-amber-dim)]',
  verdigris: 'border-[var(--color-verdigris-dim)]',
  oxblood: 'border-[var(--color-oxblood-dim)]',
};

const TONE_FILL: Record<Tone, string> = {
  neutral: 'bg-[var(--color-fill-neutral)]',
  brass: 'bg-[var(--color-fill-brass)]',
  amber: 'bg-[var(--color-fill-amber)]',
  verdigris: 'bg-[var(--color-fill-verdigris)]',
  oxblood: 'bg-[var(--color-fill-oxblood)]',
};

const TONE_FILL_STRONG: Record<Tone, string> = {
  neutral: 'bg-[var(--color-fill-neutral-strong)]',
  brass: 'bg-[var(--color-fill-brass-strong)]',
  amber: 'bg-[var(--color-fill-amber-strong)]',
  verdigris: 'bg-[var(--color-fill-verdigris-strong)]',
  oxblood: 'bg-[var(--color-fill-oxblood-strong)]',
};

/** Solid base — dots, meters, rails. Never text. */
export const TONE_SOLID: Record<Tone, string> = {
  neutral: 'bg-[var(--color-ink-faint)]',
  brass: 'bg-[var(--color-brass)]',
  amber: 'bg-[var(--color-amber)]',
  verdigris: 'bg-[var(--color-verdigris)]',
  oxblood: 'bg-[var(--color-oxblood)]',
};

/** The raw custom-property name per tone, for a computed inline shadow that
    Tailwind cannot express as a static class. Never used for text. */
export const TONE_VAR: Record<Tone, string> = {
  neutral: '--color-rule-strong',
  brass: '--color-brass',
  amber: '--color-amber',
  verdigris: '--color-verdigris',
  oxblood: '--color-oxblood',
};

/** Drawn INSIDE the row, so selection can never change a row's height. */
export const TONE_RAIL: Record<Tone, string> = {
  neutral: 'shadow-[inset_2px_0_0_0_var(--color-rule-strong)]',
  brass: 'shadow-[inset_2px_0_0_0_var(--color-brass)]',
  amber: 'shadow-[inset_2px_0_0_0_var(--color-amber)]',
  verdigris: 'shadow-[inset_2px_0_0_0_var(--color-verdigris)]',
  oxblood: 'shadow-[inset_2px_0_0_0_var(--color-oxblood)]',
};

const ELEVATION: Record<Elevation, string> = {
  0: 'shadow-[var(--shadow-elev-0)]',
  1: 'shadow-[var(--shadow-elev-1)]',
  2: 'shadow-[var(--shadow-elev-2)]',
  3: 'shadow-[var(--shadow-elev-3)]',
  4: 'shadow-[var(--shadow-elev-4)]',
};

/* --- state maps ----------------------------------------------------------
   The three in-flight states are brass because they are PROCESS, not status:
   the case has no verdict yet. That is the one sanctioned brass-on-a-state
   usage. Every terminal state carries a semantic hue. */

export const STATE_TONE: Record<CaseState, Tone> = {
  opened: 'neutral',
  held: 'amber',
  verifying: 'brass',
  awaiting_callback: 'amber',
  challenging: 'brass',
  adjudicating: 'brass',
  escalated: 'amber',
  released: 'verdigris',
  blocked: 'oxblood',
};

export const VERDICT_TONE: Record<Verdict, Tone> = {
  supports: 'verdigris',
  contradicts: 'oxblood',
  inconclusive: 'neutral',
};

export const OUTCOME_TONE: Record<Outcome, Tone> = {
  RELEASE: 'verdigris',
  BLOCK: 'oxblood',
  ESCALATE: 'amber',
};

/* ==========================================================================
   STRUCTURE
   ========================================================================== */

/** 1px hairline. `vertical` is the 20px navbar divider with 8px margins. */
export function Divider({
  vertical = false, className = '',
}: { vertical?: boolean; className?: string }) {
  return vertical
    ? <span aria-hidden className={cx('mx-2 h-5 w-px shrink-0 bg-[var(--color-rule)]', className)} />
    : <hr className={cx('my-2 h-px w-full border-0 bg-[var(--color-rule)]', className)} />;
}

/**
 * A raised object. Padding 20px, compact 16px, radius 4px.
 * Interactive lifts to elevation 2 on hover — the only place we lift anything.
 */
export function Card({
  children, elevation = 0, compact = false, interactive = false,
  selected = false, className = '', onClick,
}: {
  children: ReactNode;
  elevation?: Elevation;
  compact?: boolean;
  interactive?: boolean;
  selected?: boolean;
  className?: string;
  onClick?: () => void;
}) {
  const base = cx(
    'rounded-[var(--radius-ctl)] bg-[var(--color-raised)]',
    compact ? 'p-4' : 'p-5',
    selected ? ELEVATION[2] : ELEVATION[elevation],
    interactive && 'cursor-pointer transition-shadow duration-100 ease-[var(--ease-ui)] hover:shadow-[var(--shadow-elev-2)]',
    selected && 'bg-[var(--color-overlay)]',
    className,
  );
  if (!interactive) return <div className={base}>{children}</div>;
  return (
    <div role="button" tabIndex={0} onClick={onClick} className={base}
      onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onClick?.(); } }}>
      {children}
    </div>
  );
}

/** A 30px chrome band: micro-label title, optional right slot, 1px bottom rule. */
export function SectionHeader({
  title, actions, tone = 'brass', className = '',
}: { title: ReactNode; actions?: ReactNode; tone?: 'brass' | 'neutral'; className?: string }) {
  return (
    <header
      className={cx(
        'flex h-[30px] shrink-0 items-center justify-between gap-3 rule-b px-3',
        className,
      )}
    >
      <h2 className={cx('truncate', tone === 'brass' ? 'label-brass' : 'label-micro')}>{title}</h2>
      {actions && <div className="flex shrink-0 items-center gap-1">{actions}</div>}
    </header>
  );
}

/**
 * A pane. 30px header, independently scrolling body. The document never
 * scrolls; panes do — which is why the operator's anchors never move, and
 * why nothing shifts on video when an SSE frame lands.
 */
export function Panel({
  title, actions, children, className = '', scroll = true, elevation, footer, label,
}: {
  title?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
  scroll?: boolean;
  elevation?: Elevation;
  footer?: ReactNode;
  label?: string;
}) {
  return (
    <section
      aria-label={label ?? (typeof title === 'string' ? title : undefined)}
      className={cx('flex min-h-0 flex-col', elevation !== undefined && ELEVATION[elevation], className)}
    >
      {title && <SectionHeader title={title} actions={actions} />}
      <div className={cx('min-h-0 flex-1', scroll && 'overflow-y-auto pane-scroll')}>{children}</div>
      {footer && (
        <div className="flex h-[26px] shrink-0 items-center gap-3 rule-t px-3">{footer}</div>
      )}
    </section>
  );
}

/**
 * A 2px band that is ALWAYS in the layout and filled only while a fetch is open.
 * Reserving it is why a tab panel never moves when its data lands (N4).
 */
export function LoadBar({ loading }: { loading: boolean }) {
  return (
    <div className="h-[2px] shrink-0">
      {loading && <ProgressBar indeterminate label="Loading" />}
    </div>
  );
}

/**
 * The scrolling body of a tab panel: focusable, so the keyboard can reach a long
 * region without tabbing through every row inside it, and independently scrolled,
 * because the document never scrolls (N5).
 */
export function Region({
  label, children, className = '',
}: { label: string; children: ReactNode; className?: string }) {
  return (
    <div
      role="region"
      aria-label={label}
      tabIndex={0}
      className={cx(
        'min-h-0 flex-1 overflow-y-auto pane-scroll outline-none',
        'focus-visible:shadow-[var(--shadow-focus-inset)]',
        className,
      )}
    >
      {children}
    </div>
  );
}

/**
 * Callout. 16px padding, 8px compact; with an icon the text inset is 40px and
 * the glyph is absolutely positioned at left 16 / top 18 so multi-line body
 * copy stays flush.
 */
export function Callout({
  title, children, tone = 'neutral', icon, compact = false, className = '',
}: {
  title?: ReactNode;
  children?: ReactNode;
  tone?: Tone;
  icon?: ReactNode;
  compact?: boolean;
  className?: string;
}) {
  return (
    <div
      role={tone === 'oxblood' ? 'alert' : undefined}
      className={cx(
        'relative w-full rounded-[var(--radius-ctl)] text-[var(--text-xs)] leading-[1.5]',
        tone === 'neutral' ? 'bg-[var(--color-fill-neutral)]' : TONE_FILL[tone],
        compact ? 'p-2' : 'p-4',
        compact && icon ? 'pl-8' : icon ? 'pl-10' : '',
        className,
      )}
    >
      {icon && (
        <span
          aria-hidden
          className={cx(
            'absolute',
            compact ? 'left-2 top-[10px]' : 'left-4 top-[18px]',
            TONE_TEXT[tone],
          )}
        >
          {icon}
        </span>
      )}
      {title && (
        <div className={cx('text-sm font-semibold leading-4', TONE_TEXT[tone], children ? 'mb-1' : '')}>
          {title}
        </div>
      )}
      {children && <div className="text-[var(--color-ink-muted)]">{children}</div>}
    </div>
  );
}

/**
 * The empty / error / degraded state. Vertical flex, centred, every child
 * capped at 400px with 20px between. The visual is one ramp step QUIETER than
 * the body text — the icon is deliberately not the loudest thing.
 *
 * Ops tools state a fact and offer the escape hatch. No illustrations, no
 * mascots, no 64px emoji.
 *
 * THE VISUAL IS ALWAYS `size={22} strokeWidth={1.75}`, on every surface. It is
 * a prop rather than a baked-in icon only so each surface can name its own
 * subject; the geometry is not the caller's to choose.
 *
 * An EMPTY state is `tone="neutral"`. A FAILED state is `tone="amber"` and
 * carries an `action` — a retry. "Nothing happened yet" and "the service did
 * not answer" are different facts and must never render identically.
 */
export function NonIdealState({
  visual, title, description, action, tone = 'neutral', className = '',
}: {
  visual?: ReactNode;
  title: ReactNode;
  description?: ReactNode;
  action?: ReactNode;
  tone?: Tone;
  className?: string;
}) {
  return (
    <div
      className={cx(
        'flex h-full w-full flex-col items-center justify-center px-6 py-10 text-center',
        className,
      )}
    >
      {visual && (
        <div className={cx('mb-5 max-w-[400px]', tone === 'neutral' ? 'text-[var(--color-ink-disabled)]' : TONE_TEXT[tone])}>
          {visual}
        </div>
      )}
      <p className={cx('mb-2 max-w-[400px] text-sm leading-5', TONE_TEXT[tone])}>{title}</p>
      {description && (
        <p className="mb-5 max-w-[400px] text-mini leading-4 text-[var(--color-ink-faint)]">
          {description}
        </p>
      )}
      {action && <div className="max-w-[400px]">{action}</div>}
    </div>
  );
}

/* ==========================================================================
   CONTROLS
   ========================================================================== */

export type ButtonSize = 'xs' | 'sm' | 'md' | 'lg';
export type ButtonVariant = 'default' | 'minimal' | 'outlined';

const BTN_SIZE: Record<ButtonSize, string> = {
  xs: 'h-[20px] min-w-[20px] px-2 text-micro',
  sm: 'h-[24px] min-w-[24px] px-2 text-mini',
  md: 'h-[30px] min-w-[30px] px-2 text-xs',
  lg: 'h-[40px] min-w-[40px] px-4 text-base',
};

/**
 * Button.
 *
 *   default  — neutral fill + inset ring + a 1px drop. It announces itself.
 *   minimal  — no fill, no ring at rest; reveals itself as a wash on hover.
 *   outlined — a real 1px border, no fill. The middle option.
 *
 * Toolbars, navbars and dense action strips use `minimal`. Only a commit
 * action uses `default`. This is the density lever.
 */
export function Button({
  children, onClick, tone = 'neutral', disabled, title, size = 'sm',
  variant = 'default', active = false, shortcut, icon, fill = false,
  type = 'button', className = '', ariaLabel,
}: {
  children?: ReactNode;
  onClick?: () => void;
  tone?: Tone;
  disabled?: boolean;
  title?: string;
  size?: ButtonSize;
  variant?: ButtonVariant;
  active?: boolean;
  shortcut?: string;
  icon?: ReactNode;
  fill?: boolean;
  type?: 'button' | 'submit';
  className?: string;
  ariaLabel?: string;
}) {
  const iconOnly = !children && !!icon;

  const skin =
    variant === 'minimal'
      ? cx(
          'bg-transparent',
          active ? cx(TONE_FILL_STRONG[tone], TONE_TEXT[tone]) : TONE_TEXT[tone],
          'hover:bg-[var(--color-fill-neutral-strong)]',
        )
      : variant === 'outlined'
        ? cx('border bg-transparent', TONE_EDGE[tone], TONE_TEXT[tone],
            active && TONE_FILL[tone], 'hover:bg-[var(--color-fill-neutral)]')
        : cx(
            'bg-[var(--color-raised)] shadow-[var(--shadow-control)]',
            active ? cx(TONE_FILL_STRONG[tone], TONE_TEXT[tone]) : TONE_TEXT[tone],
            'hover:bg-[var(--color-overlay)] hover:shadow-[var(--shadow-control-hover)]',
          );

  return (
    <button
      type={type}
      onClick={onClick}
      disabled={disabled}
      title={title}
      aria-label={ariaLabel ?? (iconOnly ? title : undefined)}
      aria-pressed={active || undefined}
      className={cx(
        'inline-flex shrink-0 items-center justify-center gap-2 rounded-[var(--radius-ctl)]',
        'font-medium tracking-[0.02em] whitespace-nowrap',
        'transition-[background-color,box-shadow,color] duration-100 ease-[var(--ease-ui)]',
        BTN_SIZE[size],
        iconOnly && 'px-0',
        fill && 'w-full',
        skin,
        'disabled:cursor-not-allowed disabled:text-[var(--color-ink-disabled)]',
        'disabled:shadow-none disabled:hover:bg-transparent',
        className,
      )}
    >
      {icon && <span aria-hidden className="inline-flex shrink-0 items-center">{icon}</span>}
      {children}
      {shortcut && <Kbd>{shortcut}</Kbd>}
    </button>
  );
}

/**
 * The keyboard model has to be VISIBLE. On a muted recording an invisible
 * keyboard model is an absent one, so every action that has a shortcut wears
 * it as a chip.
 */
export function Kbd({ children }: { children: ReactNode }) {
  return (
    <kbd
      className="inline-flex h-[18px] min-w-[18px] items-center justify-center rounded-[var(--radius-input)]
        border border-[var(--color-rule-strong)] bg-[var(--color-ground)] px-1
        font-mono text-micro leading-none text-[var(--color-ink-faint)]"
    >
      {children}
    </kbd>
  );
}

/**
 * Input. The rest state is a recess CUT INTO the panel — an inset ring plus an
 * inner shadow — not a box drawn on it. Focus swaps the ring to brass rather
 * than adding an outline, because the recess is the affordance.
 */
export function Input({
  value, onChange, placeholder, size = 'md', mono = false, id, type = 'text',
  disabled = false, className = '', ariaLabel, onKeyDown, autoFocus = false, inputRef,
}: {
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  size?: 'sm' | 'md' | 'lg';
  mono?: boolean;
  id?: string;
  type?: 'text' | 'search';
  disabled?: boolean;
  className?: string;
  ariaLabel?: string;
  onKeyDown?: (e: ReactKeyboardEvent<HTMLInputElement>) => void;
  autoFocus?: boolean;
  inputRef?: RefObject<HTMLInputElement>;
}) {
  const h = size === 'sm' ? 'h-[24px] text-mini' : size === 'lg' ? 'h-[40px] text-base' : 'h-[30px] text-xs';
  return (
    <input
      ref={inputRef}
      id={id}
      type={type}
      data-well=""
      value={value}
      disabled={disabled}
      autoFocus={autoFocus}
      aria-label={ariaLabel}
      placeholder={placeholder}
      onKeyDown={onKeyDown}
      onChange={(e) => onChange(e.target.value)}
      className={cx(
        'w-full rounded-[var(--radius-input)] border-0 bg-[var(--color-ground)] px-2',
        'text-[var(--color-ink)] placeholder:text-[var(--color-ink-faint)]',
        'shadow-[var(--shadow-well)] outline-none',
        'transition-shadow duration-100 ease-[var(--ease-ui)]',
        'focus:shadow-[var(--shadow-well-focus)]',
        'disabled:cursor-not-allowed disabled:text-[var(--color-ink-disabled)]',
        mono && 'font-mono tabular',
        h,
        className,
      )}
    />
  );
}

/**
 * Tabs. 30px rows, 20px column gap, roving tabindex, a 2px brass underline on
 * the selected tab. The indicator moves in 200ms; state colour in 100ms.
 */
export function Tabs<T extends string>({
  tabs, value, onChange, className = '', label = 'Sections',
}: {
  tabs: { id: T; label: string; count?: number }[];
  value: T;
  onChange: (id: T) => void;
  className?: string;
  label?: string;
}) {
  const onKeyDown = (e: ReactKeyboardEvent<HTMLDivElement>) => {
    const i = tabs.findIndex((t) => t.id === value);
    if (i < 0) return;
    let next = i;
    if (e.key === 'ArrowRight') next = (i + 1) % tabs.length;
    else if (e.key === 'ArrowLeft') next = (i - 1 + tabs.length) % tabs.length;
    else if (e.key === 'Home') next = 0;
    else if (e.key === 'End') next = tabs.length - 1;
    else return;
    e.preventDefault();
    const target = tabs[next];
    if (target) onChange(target.id);
  };

  return (
    <div
      role="tablist"
      aria-label={label}
      onKeyDown={onKeyDown}
      className={cx('flex h-[30px] shrink-0 items-end gap-5 rule-b px-3', className)}
    >
      {tabs.map((t) => {
        const selected = t.id === value;
        return (
          <button
            key={t.id}
            role="tab"
            type="button"
            id={`tab-${t.id}`}
            aria-selected={selected}
            aria-controls={`panel-${t.id}`}
            tabIndex={selected ? 0 : -1}
            onClick={() => onChange(t.id)}
            className={cx(
              'flex h-[30px] shrink-0 items-center gap-1.5 whitespace-nowrap text-mini font-medium',
              'transition-[color,box-shadow] duration-200 ease-[var(--ease-ui)]',
              selected
                ? 'text-[var(--color-brass-text)] shadow-[inset_0_-2px_0_0_var(--color-brass)]'
                : 'text-[var(--color-ink-dim)] hover:text-[var(--color-ink-muted)]',
            )}
          >
            {t.label}
            {t.count !== undefined && (
              <span className="font-mono tabular text-micro text-[var(--color-ink-faint)]">
                {t.count}
              </span>
            )}
          </button>
        );
      })}
    </div>
  );
}

/**
 * ProgressBar. A 6px track with a meter whose width transitions over 200ms.
 * `indeterminate` is a 2px sweep — never a spinner, and never a bar for an
 * unbounded stream.
 */
export function ProgressBar({
  value, tone = 'brass', indeterminate = false, className = '', label,
}: {
  value?: number;
  tone?: Tone;
  indeterminate?: boolean;
  className?: string;
  label?: string;
}) {
  if (indeterminate) {
    return (
      <div role="progressbar" aria-label={label ?? 'Working'}
        className={cx('h-[2px] w-full overflow-hidden bg-[var(--color-rule)]', className)}>
        <div className={cx('h-full w-1/3 animate-indeterminate', TONE_SOLID[tone])} />
      </div>
    );
  }
  const pctValue = Math.max(0, Math.min(1, value ?? 0));
  return (
    <div
      role="progressbar"
      aria-label={label ?? 'Progress'}
      aria-valuenow={Math.round(pctValue * 100)}
      aria-valuemin={0}
      aria-valuemax={100}
      className={cx('h-[6px] w-full overflow-hidden rounded-full bg-[var(--color-rule)]', className)}
    >
      <div
        className={cx('h-full rounded-full transition-[width] duration-200 ease-[var(--ease-ui)]', TONE_SOLID[tone])}
        style={{ width: `${pctValue * 100}%` }}
      />
    </div>
  );
}

/* ==========================================================================
   STATUS
   ========================================================================== */

/**
 * Pill / Tag. 18px, 10px uppercase, 2px radius. Exactly ONE encoding: either
 * a 14% fill with the `-text` colour, or a dot with neutral text. Never a dot
 * AND a fill AND a coloured text AND an icon for one enum value.
 *
 * `minWidth` keeps a status column from jittering as values change.
 */
export function Pill({
  children, tone = 'neutral', dot = false, minWidth, title, className = '',
}: {
  children: ReactNode;
  tone?: Tone;
  dot?: boolean;
  minWidth?: number;
  title?: string;
  className?: string;
}) {
  const style: CSSProperties | undefined = minWidth ? { minWidth } : undefined;
  return (
    <span
      data-pill=""
      title={title}
      style={style}
      className={cx(
        'inline-flex h-[18px] items-center gap-1.5 rounded-[var(--radius-pill)] px-1.5',
        'text-micro font-semibold uppercase leading-none tracking-[0.08em] whitespace-nowrap',
        // one encoding, not four: a dot means neutral text, no dot means a fill.
        dot ? 'bg-transparent text-[var(--color-ink-muted)]' : cx(TONE_FILL[tone], TONE_TEXT[tone]),
        className,
      )}
    >
      {dot && <Dot tone={tone} />}
      {children}
    </span>
  );
}

/** Alias. `Tag` reads better next to a value; `Pill` next to a state. */
export const Tag = Pill;

export function Dot({ tone = 'neutral', live = false }: { tone?: Tone; live?: boolean }) {
  return (
    <span
      aria-hidden
      className={cx(
        'inline-block h-[5px] w-[5px] shrink-0 rounded-full',
        TONE_SOLID[tone],
        live && 'animate-live',
      )}
    />
  );
}

export function StateChip({ state, minWidth }: { state: CaseState; minWidth?: number }) {
  return <Pill tone={STATE_TONE[state]} dot minWidth={minWidth}>{stateLabel(state)}</Pill>;
}

/**
 * Granted/denied scope chip. Denied is deliberately NOT oxblood — a denial is
 * the system working correctly, not money being stopped.
 */
export function ScopeChip({ scope, denied = false }: { scope: string; denied?: boolean }) {
  return (
    <span
      title={denied ? `${scope} — denied by policy` : scope}
      className={cx(
        'inline-flex h-[18px] items-center rounded-[var(--radius-pill)] border px-1.5',
        'font-mono text-micro leading-none whitespace-nowrap',
        denied
          ? 'border-[var(--color-rule)] text-[var(--color-ink-faint)] line-through decoration-[var(--color-ink-faint)]'
          : 'border-[var(--color-brass-dim)] text-[var(--color-brass-text)]',
      )}
    >
      {scope}
    </span>
  );
}

/**
 * One reserved block of a loading skeleton. ONE implementation, because the
 * first seconds of the recording show skeletons on every surface at once and
 * they were drifting into three fills and two radii. A skeleton RESERVES
 * space: it is static, it is never a shimmer, and its geometry is the line
 * box of the content it stands in for.
 */
export function SkeletonBar({
  width, height = 10, className = '',
}: { width: string; height?: number; className?: string }) {
  return (
    <span
      aria-hidden
      style={{ width, height }}
      className={cx('block shrink-0 rounded-[2px] bg-[var(--color-fill-neutral-strong)]', className)}
    />
  );
}

/**
 * A granted/denied scope set. ONE implementation, because Registry's agent
 * record and Posture's fleet manifest show the same fact about the same
 * agents and were drifting into two vocabularies for it.
 *
 * `framed` is the only difference the two contexts are allowed: the Registry
 * detail pane has room for a carded block with a rail, the Posture manifest
 * is a dense per-agent row. The chips, the count, the label treatment and the
 * empty em-dash are identical in both.
 */
export function ScopeManifest({
  label, scopes, denied = false, framed = false,
}: { label: string; scopes: string[]; denied?: boolean; framed?: boolean }) {
  const body = (
    <>
      <div className={cx('flex items-baseline justify-between gap-2', framed ? 'mb-2' : 'mb-1')}>
        <span className="label-micro">{label}</span>
        <span data-numeric="" className="font-mono tabular text-micro text-[var(--color-ink-dim)]">
          {scopes.length}
        </span>
      </div>
      <div className="flex flex-wrap gap-1">
        {scopes.length
          ? scopes.map((s) => <ScopeChip key={s} scope={s} denied={denied} />)
          : <span className="text-mini leading-[18px] text-[var(--color-ink-dim)]">—</span>}
      </div>
    </>
  );

  if (!framed) return <div className="flex flex-col">{body}</div>;
  return (
    <Card compact elevation={0} className="relative overflow-hidden">
      <span
        aria-hidden
        className={cx(
          'absolute inset-y-0 left-0 w-[2px]',
          // Structure, not status: a denied scope is the system working.
          denied ? 'bg-[var(--color-rule-strong)]' : 'bg-[var(--color-brass)]',
        )}
      />
      {body}
    </Card>
  );
}

/* ==========================================================================
   THE PATH — a staged progress indicator over the CaseState machine.

   Two orthogonal ideas, deliberately separated:
     `current` = where the case actually is.
     `active`  = which stage the operator is inspecting.
   A terminal outcome recolours the WHOLE track, not one stage, so a closed
   case reads as closed at a glance.

   Complete stages carry a check glyph, so the encoding survives grayscale,
   colour-blindness and video compression.
   ========================================================================== */

interface PathStage { id: string; label: string; states: CaseState[] }

const PATH_STAGES: PathStage[] = [
  { id: 'opened', label: 'Opened', states: ['opened'] },
  { id: 'held', label: 'Held', states: ['held'] },
  { id: 'verifying', label: 'Verifying', states: ['verifying', 'awaiting_callback'] },
  { id: 'challenging', label: 'Challenged', states: ['challenging'] },
  { id: 'adjudicating', label: 'Adjudicating', states: ['adjudicating'] },
  { id: 'outcome', label: 'Outcome', states: ['released', 'blocked', 'escalated'] },
];

const TERMINAL_TONE: Partial<Record<CaseState, Tone>> = {
  released: 'verdigris',
  blocked: 'oxblood',
  escalated: 'amber',
};

const NOTCH = 9;
const CLIP_FIRST = `polygon(0 0, calc(100% - ${NOTCH}px) 0, 100% 50%, calc(100% - ${NOTCH}px) 100%, 0 100%)`;
const CLIP_MID = `polygon(0 0, calc(100% - ${NOTCH}px) 0, 100% 50%, calc(100% - ${NOTCH}px) 100%, 0 100%, ${NOTCH}px 50%)`;
const CLIP_LAST = `polygon(0 0, 100% 0, 100% 100%, 0 100%, ${NOTCH}px 50%)`;

export function CasePath({
  state, activeStage, onSelectStage, className = '',
}: {
  state: CaseState;
  activeStage?: string;
  onSelectStage?: (id: string) => void;
  className?: string;
}) {
  const currentIndex = PATH_STAGES.findIndex((s) => s.states.includes(state));
  const terminal = TERMINAL_TONE[state];

  return (
    <div
      role="list"
      aria-label="Case progress"
      className={cx('flex h-[30px] w-full items-stretch gap-[2px]', className)}
    >
      {PATH_STAGES.map((stage, i) => {
        const complete = currentIndex > i;
        const current = currentIndex === i;
        const active = activeStage === stage.id;

        // A terminal outcome recolours the whole track, not one chevron.
        const tone: Tone = terminal && (complete || current)
          ? terminal
          : current ? 'brass' : complete ? 'brass' : 'neutral';

        const fill = current || complete
          ? (active ? TONE_FILL_STRONG[tone] : TONE_FILL[tone])
          : 'bg-[var(--color-surface)]';

        const text = current || complete ? TONE_TEXT[tone] : 'text-[var(--color-ink-faint)]';

        return (
          <div
            key={stage.id}
            role="listitem"
            aria-current={current ? 'step' : undefined}
            className="min-w-[80px] flex-1"
          >
            <button
              type="button"
              disabled={!onSelectStage}
              onClick={onSelectStage ? () => onSelectStage(stage.id) : undefined}
              title={`${stage.label}${current ? ' — current' : complete ? ' — complete' : ''}`}
              style={{
                clipPath: i === 0 ? CLIP_FIRST : i === PATH_STAGES.length - 1 ? CLIP_LAST : CLIP_MID,
              }}
              className={cx(
                'flex h-[30px] w-full items-center justify-center gap-1.5 px-3',
                'text-micro font-semibold uppercase tracking-[0.08em] whitespace-nowrap',
                'transition-colors duration-100 ease-[var(--ease-ui)]',
                fill, text,
                active && 'shadow-[inset_0_-2px_0_0_var(--color-brass)]',
                onSelectStage ? 'cursor-pointer' : 'cursor-default',
              )}
            >
              {complete && <Check aria-hidden size={10} strokeWidth={3} className="shrink-0" />}
              {/* Static. The current stage is already carried by the fill, the
                  brass underline and the dot's presence; a pulse here would be
                  a second infinite animation competing with the StatusBar's
                  one sanctioned live indicator (§10). */}
              {current && <Dot tone={tone} />}
              <span className="truncate">{stage.label}</span>
            </button>
          </div>
        );
      })}
    </div>
  );
}

/* ==========================================================================
   DATA PRIMITIVES

   Identifiers are mono, muted and middle-truncated. Quantities are tabular
   and right-alignable. Times are fixed-width with the zone declared once.
   Never mix formats in a column: one `$1234.5` next to one `$1,234.50` is an
   immediate credibility loss and a reviewer spots it in a single frame.
   ========================================================================== */

const MONEY_SIZE = {
  sm: 'text-sm',
  md: 'text-lg leading-none',
  lg: 'text-xl leading-none',
  figure: 'text-figure leading-none tracking-[-0.02em]',
} as const;

export function Money({
  value, size = 'sm', tone, cents = false, className = '',
}: {
  value: string | number;
  size?: keyof typeof MONEY_SIZE;
  tone?: Tone;
  cents?: boolean;
  className?: string;
}) {
  return (
    <span
      data-numeric=""
      className={cx(
        'font-mono tabular font-medium whitespace-nowrap',
        MONEY_SIZE[size],
        tone ? TONE_TEXT[tone] : 'text-[var(--color-ink)]',
        className,
      )}
    >
      {money(value, cents)}
    </span>
  );
}

/** Middle-truncate: the discriminating characters of an id are at the END. */
export function truncateId(value: string, head = 10, tail = 4): string {
  if (value.length <= head + tail + 1) return value;
  return `${value.slice(0, head)}…${value.slice(-tail)}`;
}

export function MonoId({
  children, dim = false, truncate = false, copyable = false, title,
}: {
  children: ReactNode;
  dim?: boolean;
  truncate?: boolean;
  copyable?: boolean;
  title?: string;
}) {
  const raw = typeof children === 'string' ? children : '';
  const shown = truncate && raw ? truncateId(raw) : children;
  const body = (
    <span
      title={title ?? (raw || undefined)}
      data-numeric=""
      className={cx(
        'font-mono tabular text-mini whitespace-nowrap',
        dim ? 'text-[var(--color-ink-faint)]' : 'text-[var(--color-ink-dim)]',
      )}
    >
      {shown}
    </span>
  );
  if (!copyable || !raw) return body;
  return (
    <span className="inline-flex items-center gap-1">
      {body}
      <CopyButton value={raw} />
    </span>
  );
}

/** Copy confirms with a check glyph for 900ms. Never a toast. */
export function CopyButton({ value }: { value: string }) {
  const [done, setDone] = useState(false);
  const timer = useRef<number | null>(null);

  useEffect(() => () => { if (timer.current !== null) window.clearTimeout(timer.current); }, []);

  const copy = useCallback(() => {
    void navigator.clipboard?.writeText(value).catch(() => undefined);
    setDone(true);
    if (timer.current !== null) window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => setDone(false), 900);
  }, [value]);

  return (
    <button
      type="button"
      onClick={copy}
      title={done ? 'Copied' : `Copy ${value}`}
      aria-label={done ? 'Copied' : `Copy ${value}`}
      className="inline-flex h-[18px] w-[18px] items-center justify-center rounded-[var(--radius-input)]
        text-[var(--color-ink-faint)] transition-colors duration-100 hover:text-[var(--color-ink-muted)]"
    >
      {done
        ? <Check size={11} strokeWidth={2.5} className="text-[var(--color-verdigris-text)]" />
        : <Copy size={11} strokeWidth={1.75} />}
    </button>
  );
}

/** Confidence as a filled bar. Width encodes the number so it reads muted at 1080p. */
export function ConfidenceBar({ value, tone = 'brass' }: { value: number; tone?: Tone }) {
  const clamped = Math.max(0, Math.min(1, value));
  return (
    <div className="flex items-center gap-2">
      <div
        className="h-[3px] w-16 shrink-0 bg-[var(--color-rule)]"
        role="img"
        aria-label={`Confidence ${clamped.toFixed(2)}`}
      >
        <div className={cx('h-full', TONE_SOLID[tone])} style={{ width: `${clamped * 100}%` }} />
      </div>
      <span data-numeric="" className="font-mono tabular text-micro text-[var(--color-ink-faint)]">
        {clamped.toFixed(2)}
      </span>
    </div>
  );
}

/** Integer ms in a fixed 6ch column. No 0.8423s. No six-decimal floats. */
export function Latency({ ms: value }: { ms: number }) {
  const text = value >= 1000 ? `${(value / 1000).toFixed(2)}s` : `${Math.round(value)}ms`;
  return (
    <span data-numeric=""
      className="inline-block min-w-[6ch] text-right font-mono tabular text-mini text-[var(--color-ink-dim)]">
      {text}
    </span>
  );
}

/** Fixed-width. The timezone is stated once in the column header, never per row. */
export function Timestamp({ children, dim = false }: { children: ReactNode; dim?: boolean }) {
  return (
    <span data-numeric=""
      className={cx('font-mono tabular text-mini whitespace-nowrap',
        dim ? 'text-[var(--color-ink-faint)]' : 'text-[var(--color-ink-dim)]')}>
      {children}
    </span>
  );
}

/**
 * Label ABOVE value, label SMALLER than value. Every key/value pair in the
 * system is a 10px uppercase faint label over a 12-13px ink value.
 */
export function KeyValue({
  label, children, className = '',
}: { label: string; children: ReactNode; className?: string }) {
  return (
    <div className={cx('flex min-w-0 flex-col gap-[2px]', className)}>
      <span className="label-micro truncate">{label}</span>
      <span className="min-w-0 truncate text-sm text-[var(--color-ink)]">{children}</span>
    </div>
  );
}

/** Dense definition list: label in a fixed 132px left column. */
export function FieldRow({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="grid grid-cols-[132px_1fr] items-baseline gap-3 py-[6px]">
      <dt className="label-micro">{label}</dt>
      <dd className="min-w-0 text-xs text-[var(--color-ink)]">{children}</dd>
    </div>
  );
}
