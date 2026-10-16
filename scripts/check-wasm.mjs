import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { Parser, Language } from 'web-tree-sitter';

const lock = JSON.parse(await readFile(new URL('../grammars.lock.json', import.meta.url), 'utf8'));
await Parser.init();
for (const grammar of lock.grammars) {
  const parser = new Parser();
  const language = await Language.load(await readFile(new URL(`../.build/wasm/${grammar.name}.wasm`, import.meta.url)));
  try {
    parser.setLanguage(language);
    const tree = parser.parse('');
    assert.ok(tree, grammar.name);
    tree.delete();
  } finally {
    parser.delete();
  }
  console.log(`Parsed ${grammar.name}`);
}
