import { diffLines } from 'diff';

export type DiffLineKind = 'same' | 'added' | 'removed';

export interface DiffRow {
  kind: DiffLineKind;
  text: string;
  oldNo: number | null;
  newNo: number | null;
}

export interface DiffBlock {
  rows: DiffRow[];
  oldStart: number;
  oldLines: number;
  newStart: number;
  newLines: number;
  skippedBefore: number;
}

export interface LineDiff {
  blocks: DiffBlock[];
  added: number;
  removed: number;
  unchanged: number;
}

const CONTEXT_LINES = 3;

function splitLines(value: string): string[] {
  const lines = value.split('\n');
  if (lines.length > 0 && lines[lines.length - 1] === '') lines.pop();
  return lines;
}

function makeBlock(rows: DiffRow[], skippedBefore: number): DiffBlock {
  const oldNos = rows.filter((row) => row.oldNo !== null).map((row) => row.oldNo as number);
  const newNos = rows.filter((row) => row.newNo !== null).map((row) => row.newNo as number);
  return {
    rows,
    oldStart: oldNos[0] ?? 0,
    oldLines: oldNos.length,
    newStart: newNos[0] ?? 0,
    newLines: newNos.length,
    skippedBefore
  };
}

/**
 * Line diff between the original (base) body and the submitted body, grouped
 * into hunk-style blocks with a few lines of surrounding context. Long
 * unchanged runs between blocks are collapsed (skippedBefore records how many
 * lines were elided ahead of each block).
 */
export function buildLineDiff(before: string, after: string): LineDiff {
  const rows: DiffRow[] = [];
  let oldNo = 1;
  let newNo = 1;
  let added = 0;
  let removed = 0;
  let unchanged = 0;

  for (const change of diffLines(before, after)) {
    for (const text of splitLines(change.value)) {
      if (change.added) {
        rows.push({ kind: 'added', text, oldNo: null, newNo: newNo++ });
        added += 1;
      } else if (change.removed) {
        rows.push({ kind: 'removed', text, oldNo: oldNo++, newNo: null });
        removed += 1;
      } else {
        rows.push({ kind: 'same', text, oldNo: oldNo++, newNo: newNo++ });
        unchanged += 1;
      }
    }
  }

  const keep = new Array<boolean>(rows.length).fill(false);
  rows.forEach((row, index) => {
    if (row.kind === 'same') return;
    const from = Math.max(0, index - CONTEXT_LINES);
    const to = Math.min(rows.length - 1, index + CONTEXT_LINES);
    for (let j = from; j <= to; j += 1) keep[j] = true;
  });

  const blocks: DiffBlock[] = [];
  let current: DiffRow[] = [];
  let skipped = 0;
  rows.forEach((row, index) => {
    if (keep[index]) {
      current.push(row);
    } else {
      if (current.length > 0) {
        blocks.push(makeBlock(current, skipped));
        current = [];
        skipped = 0;
      }
      skipped += 1;
    }
  });
  if (current.length > 0) blocks.push(makeBlock(current, skipped));

  return { blocks, added, removed, unchanged };
}
