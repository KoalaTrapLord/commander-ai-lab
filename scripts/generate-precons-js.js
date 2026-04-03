#!/usr/bin/env node
/**
 * Generate lan-client/precons.js from precon-decks/precon-index.json
 * Usage: node scripts/generate-precons-js.js
 */
const fs = require('fs');
const path = require('path');

const indexPath = path.join(__dirname, '..', 'precon-decks', 'precon-index.json');
const outputPath = path.join(__dirname, '..', 'lan-client', 'precons.js');

const index = JSON.parse(fs.readFileSync(indexPath, 'utf8'));

let js = '// Auto-generated from precon-decks/precon-index.json\n';
js += '// Run: node scripts/generate-precons-js.js to regenerate\n';
js += 'var PRECON_DATA = [\n';

index.forEach(function(p, i) {
  const entry = {
    id: (p.fileName || p.name || '').replace('.dck', ''),
    name: p.name || '',
    commander: p.commander || (p.commanders && p.commanders[0]) || '',
    set: p.set || '',
    fileName: p.fileName || '',
    colors: p.colors || [],
    year: p.year || 0,
  };
  js += '  ' + JSON.stringify(entry);
  js += (i < index.length - 1) ? ',\n' : '\n';
});

js += '];\n';

fs.writeFileSync(outputPath, js);
console.log(`Generated ${outputPath} with ${index.length} precon entries`);
