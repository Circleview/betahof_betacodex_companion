import { test } from 'node:test';
import assert from 'node:assert/strict';
import { buildBlocks, conversationColor, pageBlocks, shortId } from '../static/question-log-blocks.js';

const e = (id, ts, cid, types = ['first_question']) => ({
  id, timestamp: ts, conversation_id: cid, event_types: types,
});
const ALL = new Set(['first_question', 'follow_up', 'no_answer', 'feedback', 'creative', 'mcp']);
const A = 'aaaaaaaa-0000-4000-8000-000000000000';
const B = 'bbbbbbbb-0000-4000-8000-000000000000';

test('parallele Chats: zwei Blöcke, neuester Start oben, Einträge aufsteigend, k/n', () => {
  const entries = [
    e('a3', '2026-10-01T10:12:00Z', A, ['follow_up']),
    e('b1', '2026-10-01T10:03:00Z', B),
    e('a1', '2026-10-01T10:00:00Z', A),
    e('a2', '2026-10-01T10:05:00Z', A, ['follow_up']),
  ];
  const blocks = buildBlocks(entries, ALL, null);
  assert.deepEqual(blocks.map((b) => b.conversationId), [B, A]);
  assert.deepEqual(blocks[1].items.map((i) => [i.entry.id, i.k, i.n]), [['a1', 1, 3], ['a2', 2, 3], ['a3', 3, 3]]);
  assert.equal(blocks[0].start, Date.parse('2026-10-01T10:03:00Z'));
});

test('Einträge ohne ID sind Einzelblöcke ohne Farbe', () => {
  const blocks = buildBlocks([e('x', '2026-10-01T10:00:00Z', null), e('y', '2026-10-01T11:00:00Z', undefined)], ALL, null);
  assert.equal(blocks.length, 2);
  assert.ok(blocks.every((b) => b.conversationId === null && b.color === null && b.items[0].n === 1));
  assert.equal(blocks[0].items[0].entry.id, 'y');
});

test('Blockstart bleibt der Chatstart trotz Filter; k/n zählt über den ganzen Chat', () => {
  const entries = [
    e('a1', '2026-10-01T10:00:00Z', A),
    e('a2', '2026-10-02T09:00:00Z', A, ['follow_up']),
    e('b1', '2026-10-01T12:00:00Z', B),
  ];
  const blocks = buildBlocks(entries, new Set(['follow_up']), null);
  assert.equal(blocks.length, 1);
  assert.equal(blocks[0].start, Date.parse('2026-10-01T10:00:00Z'));
  assert.deepEqual(blocks[0].items.map((i) => [i.entry.id, i.k, i.n]), [['a2', 2, 2]]);
});

test('Typ-Filter: leerer Block verschwindet', () => {
  const entries = [e('a1', '2026-10-01T10:00:00Z', A), e('b1', '2026-10-01T10:01:00Z', B, ['follow_up'])];
  const blocks = buildBlocks(entries, new Set(['first_question']), null);
  assert.deepEqual(blocks.map((b) => b.conversationId), [A]);
});

test('Chat-Filter zeigt nur diesen Chat', () => {
  const entries = [e('a1', '2026-10-01T10:00:00Z', A), e('b1', '2026-10-01T10:01:00Z', B)];
  assert.deepEqual(buildBlocks(entries, ALL, A).map((b) => b.conversationId), [A]);
});

test('Farbe: stabil, hsl mit Farbton in 30er-Schritten', () => {
  const c = conversationColor(A);
  assert.equal(c, conversationColor(A));
  const m = /^hsl\((\d+) 65% 45%\)$/.exec(c);
  assert.ok(m && Number(m[1]) % 30 === 0 && Number(m[1]) < 360);
});

test('Paging zählt Blöcke', () => {
  const entries = [];
  for (let i = 0; i < 35; i += 1) {
    const cid = `c${String(i).padStart(7, '0')}-0000-4000-8000-000000000000`;
    entries.push(e(`${i}a`, `2026-10-01T10:${String(i).padStart(2, '0')}:00Z`, cid));
    entries.push(e(`${i}b`, `2026-10-01T11:${String(i).padStart(2, '0')}:00Z`, cid, ['follow_up']));
  }
  const blocks = buildBlocks(entries, ALL, null);
  const page = pageBlocks(blocks, 30);
  assert.equal(page.length, 30);
  assert.ok(page.every((b) => b.items.length === 2));
});

test('shortId: erste 4 Zeichen', () => {
  assert.equal(shortId('3f2a1b4c-0000-4000-8000-000000000000'), '3f2a');
});
