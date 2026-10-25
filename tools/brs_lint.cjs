// Syntax-check BrightScript files: node tools/brs_lint.cjs [files...] (default: all .brs)
const path = require('path');
const fs = require('fs');
const brs = require(path.join(__dirname, 'brightscript/node_modules/@rokucommunity/brs'));
const root = path.join(__dirname, '..');
let files = process.argv.slice(2);
if (files.length === 0) {
  const walk = d => fs.readdirSync(d, { withFileTypes: true }).flatMap(e =>
    e.isDirectory() ? walk(path.join(d, e.name)) : e.name.endsWith('.brs') ? [path.join(d, e.name)] : []);
  files = [...walk(path.join(root, 'components')), ...walk(path.join(root, 'source'))];
}
let bad = 0;
for (const file of files) {
  const lex = brs.lexer.Lexer.scan(fs.readFileSync(file, 'utf8'));
  const parsed = brs.parser.Parser.parse(lex.tokens);
  for (const e of [...lex.errors, ...parsed.errors]) {
    bad++;
    const at = e.location && e.location.start ? `${e.location.start.line}:${e.location.start.column}` : '?';
    console.log(`${path.relative(root, file)}:${at} ${e.message}`);
  }
}
process.exit(bad ? 1 : 0);
