/**
 * Keep generated lexers small enough for LLVM's WebAssembly control-flow passes.
 * Each helper executes one original state. The dispatcher preserves the lexer,
 * current state and last accepted token, so ADVANCE/SKIP/ACCEPT retain their semantics.
 */
export function splitTreeSitterLexer(source: string): string {
	const statesPerHelper = 128;
	const signature = 'static bool ts_lex(TSLexer *lexer, TSStateId state) {';
	const start = source.indexOf(signature);
	if (start < 0) return source;
	const stop = source.indexOf('\n}\n', start);
	if (stop < 0) throw new Error('Missing generated lexer terminator');
	const end = stop + 3;
	const original = source.slice(start, end);
	const matches = [...original.matchAll(/^    case (\d+):\n([\s\S]*?)(?=^    case \d+:|^    default:)/gm)];
	if (matches.length < 2048) return source;
	if (!original.includes('START_LEXER();') || !original.includes('eof = lexer->eof(lexer);') || matches.some((match, index) => Number(match[1]) !== index)) throw new Error('Unsupported generated lexer layout');
	const macros = `
struct AshLexerState { TSStateId state; bool result; };
#define ASH_ADVANCE(value) { context->state = value; lexer->advance(lexer, false); return true; }
#define ASH_SKIP(value) { context->state = value; lexer->advance(lexer, true); return true; }
#define ASH_ACCEPT_TOKEN(symbol) { context->result = true; lexer->result_symbol = symbol; lexer->mark_end(lexer); }
#define ASH_END_STATE() return false
#define ASH_ADVANCE_MAP(...) { \\
  static const uint16_t map[] = { __VA_ARGS__ }; \\
  for (uint32_t i = 0; i < sizeof(map) / sizeof(map[0]); i += 2) { \\
    if (map[i] == lookahead) { ASH_ADVANCE(map[i + 1]); } \\
  } \\
}
`;
	const helpers: string[] = [];
	const calls: string[] = [];
	for (let offset = 0; offset < matches.length; offset += statesPerHelper) {
		const index = helpers.length;
		const cases = matches.slice(offset, offset + statesPerHelper).map(match => `    case ${match[1]}:\n${match[2]}`).join('');
		const body = cases.replace(/\b(ADVANCE_MAP|ADVANCE|SKIP|ACCEPT_TOKEN|END_STATE)\(/g, 'ASH_$1(');
		helpers.push(`static bool ash_lex_${index}(TSLexer *lexer, struct AshLexerState *context) {\n  UNUSED bool eof = lexer->eof(lexer);\n  UNUSED int32_t lookahead = lexer->lookahead;\n  switch (context->state) {\n${body}    default: return false;\n  }\n}\n`);
		calls.push(`      case ${index}: more = ash_lex_${index}(lexer, &context); break;`);
	}
	const dispatcher = `${signature}
  struct AshLexerState context = {state, false};
  bool more;
  do {
    switch (context.state / ${statesPerHelper}) {
${calls.join('\n')}
      default: return context.result;
    }
  } while (more);
  return context.result;
}
#undef ASH_ADVANCE
#undef ASH_SKIP
#undef ASH_ACCEPT_TOKEN
#undef ASH_END_STATE
#undef ASH_ADVANCE_MAP
`;
	return source.slice(0, start) + macros + helpers.join('\n') + dispatcher + source.slice(end);
}

if (import.meta.main) {
	const { readFile, writeFile } = await import('node:fs/promises');
	const file = process.argv[2];
	if (!file || process.argv.length !== 3) throw new Error('Usage: node scripts/treeSitterLexer.ts <parser.c>');
	await writeFile(file, splitTreeSitterLexer(await readFile(file, 'utf8')));
}
