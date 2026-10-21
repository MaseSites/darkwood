#!/usr/bin/env node

import fs from "node:fs";
import path from "node:path";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";

const vault = path.dirname(fileURLToPath(import.meta.url));
const skipped = new Set([".obsidian", ".git", "node_modules"]);
const archive = "90 Archiv — Migration 2026-10-18";
const instructionFiles = new Set(["AGENTS.md", "CLAUDE.md"]);

function walk(directory, output = [], includeArchive = false) {
  for (const entry of fs.readdirSync(directory, { withFileTypes: true })) {
    if (entry.isDirectory() && skipped.has(entry.name)) continue;
    if (entry.isDirectory() && entry.name === archive && !includeArchive) continue;
    const absolute = path.join(directory, entry.name);
    if (entry.isDirectory()) walk(absolute, output, includeArchive);
    else if (entry.name.endsWith(".md")) output.push(absolute);
  }
  return output;
}

function readText(file) {
  try {
    return fs.readFileSync(file, "utf8");
  } catch (error) {
    if (process.platform !== "win32") throw error;
    const result = spawnSync(process.env.ComSpec || "cmd.exe", ["/d", "/s", "/c", "type", file], {
      encoding: "utf8",
      windowsHide: true,
      maxBuffer: 10 * 1024 * 1024,
    });
    if (result.status !== 0 || result.error) throw error;
    return result.stdout;
  }
}

function frontmatter(text) {
  const block = text.match(/^---\r?\n([\s\S]*?)\r?\n---(?:\r?\n|$)/)?.[1];
  if (!block) return {};
  const result = {};
  for (const line of block.split(/\r?\n/)) {
    const match = line.match(/^([A-Za-z_][\w-]*):\s*(.*)$/);
    if (match) result[match[1]] = match[2].trim();
  }
  return result;
}

const files = walk(vault);
const allFiles = walk(vault, [], true);
const byStem = new Map();
for (const file of allFiles) {
  byStem.set(path.basename(file, ".md"), file);
}

const errors = [];
let projectFiles = 0;
for (const file of files) {
  const relative = path.relative(vault, file).replace(/\\/g, "/");
  if (instructionFiles.has(relative)) continue;
  const text = readText(file);
  const meta = frontmatter(text);
  if (!meta.typ) errors.push(`${relative}: Frontmatter-Feld typ fehlt`);
  if (!/^\d{4}-\d{2}-\d{2}$/.test(meta.aktualisiert || "")) {
    errors.push(`${relative}: aktualisiert fehlt oder ist nicht JJJJ-MM-TT`);
  }
  if (meta.typ === "produkt") {
    projectFiles += 1;
    if (!meta.projektordner) errors.push(`${relative}: produkt braucht projektordner`);
    if (!meta.naechster_schritt) errors.push(`${relative}: produkt braucht genau einen naechster_schritt`);
  } else if (meta.projektordner) {
    errors.push(`${relative}: nur die Produkt-Zentrale darf projektordner tragen`);
  }
  for (const match of text.matchAll(/\[\[([^\]|#]+)(?:#[^\]|]+)?(?:\|[^\]]+)?\]\]/g)) {
    const target = match[1].trim();
    if (!byStem.has(target)) errors.push(`${relative}: fehlender Wikilink [[${target}]]`);
  }
}

if (projectFiles !== 1) errors.push(`Erwartet genau eine Produkt-Zentrale, gefunden: ${projectFiles}`);

if (errors.length) {
  console.error(`Vault-Audit fehlgeschlagen (${errors.length}):`);
  for (const error of errors) console.error(`- ${error}`);
  process.exit(1);
}

console.log(`Vault-Audit OK: ${files.length} aktuelle Markdown-Dateien, 1 Produkt-Zentrale, keine defekten aktuellen Wikilinks.`);
