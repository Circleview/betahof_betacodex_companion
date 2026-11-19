// Gemeinsamer Zustand der Quellenseite (import*.js): nur, was mehr als ein
// Modul schreibt oder liest, ohne sich gegenseitig importieren zu können.
// Variablen, die nur ein Modul schreibt, bleiben dort als `let` (Leser
// importieren sie als Live-Binding).
import { hasRole } from '/auth.js';

export const EDIT_ICON =
  '<svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" ' +
  'stroke-width="2" stroke-linecap="round" stroke-linejoin="round">' +
  '<path d="M12 20h9"></path>' +
  '<path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4Z"></path>' +
  "</svg>";

export const WARNING_ICON =
  '<svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" ' +
  'stroke-width="2" stroke-linecap="round" stroke-linejoin="round">' +
  '<path d="M14 4l1.5-1.5a3.54 3.54 0 1 1 5 5L19 9"></path>' +
  '<path d="M10 15l-1.5 1.5a3.54 3.54 0 1 1-5-5L5 10"></path>' +
  '<line x1="3" y1="3" x2="21" y2="21"></line>' +
  "</svg>";

export const pendingDeletions = new Map();

export const expandedSourceIds = new Set();

export function hasPflegerRole() {
  return hasRole('quellen_pfleger');
}

export const state = {
  activeEditId: null,
  // Fix (2026-09-22, gemeldeter Bug): im Autor:innen-Modus bekommt eine Quelle
  // mit mehreren Autor:innen pro Autor:in eine eigene Zeile (siehe
  // sortSources) - activeEditId allein (nur die Quellen-ID) matchte bisher
  // ALLE davon gleichzeitig, öffnete also mehrere Bearbeiten-Panels derselben
  // Quelle auf einmal (der zuvor behobene ID-Kollisions-Bug war nur ein
  // Symptom davon). __sortAuthor identifiziert zusätzlich, UNTER WELCHER
  // Autor:in-Überschrift die konkrete Zeile steht - außerhalb des Autor:innen-
  // Modus (dort immer null bei allen Zeilen) bleibt das wirkungslos.
  activeEditAuthorKey: null,
  // Backlog #94: kein Popover (auf Mobile unpraktikabel, siehe git-Historie)
  // - stattdessen klappt dieser Bereich unterhalb der Icon-Leiste auf und
  // ersetzt dabei die Alphabet-Sprungleiste (siehe updateAlphabetJumpBar).
  searchBarOpen: false,
  // Das aktuell nach Filter angezeigte Autor:innen-Profil (nur gesetzt, wenn
  // per Namen gefiltert wird) - steuert die zweigeteilte Ansicht neben der
  // gefilterten Quellenliste (buildAuthorInfoView/buildAuthorEditPanel).
  filteredAuthorEntry: null,
  authorPanelEditMode: false,
};
