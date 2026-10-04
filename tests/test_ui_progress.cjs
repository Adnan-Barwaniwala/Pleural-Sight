const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

test('polling keeps the progress panel mounted while advancing stages and time', () => {
  const source = fs.readFileSync(path.join(__dirname, '../static/app.js'), 'utf8');
  const elapsed = {textContent: ''};
  const fill = {style: {}};
  const rows = Array.from({length: 6}, () => {
    const marker = {textContent: ''}, status = {textContent: ''};
    return {className: '', querySelector: selector => selector === '.marker' ? marker : status};
  });
  const agents = [{className: ''}, {className: ''}];
  const panel = {
    querySelector: selector => selector === '.elapsed' ? elapsed : fill,
    querySelectorAll: selector => selector === '.stage' ? rows : agents,
  };
  let replacements = 0;
  const content = {querySelector: () => panel, replaceChildren: () => replacements++};
  const context = {
    state: {cases: [{id: 'case-1', reports: []}]}, selected: 'case-1',
    $: id => {assert.equal(id, 'assessment-content'); return content;},
    Date: {now: () => 15000}, Math, String,
  };
  vm.createContext(context);
  vm.runInContext(source.slice(source.indexOf('const STAGES='), source.indexOf('function showFailure')), context);
  context.run = {created: 10, stage: 'agents_running', progress: {assess_images: 'running'}};
  vm.runInContext('renderProgress(run)', context);
  assert.equal(replacements, 0);
  assert.equal(elapsed.textContent, '00:05');
  assert.equal(rows[2].querySelector('.stage-state').textContent, 'Working');
  assert.equal(rows[3].querySelector('.stage-state').textContent, 'Skipped');
  const originalRows = [...rows];
  context.run = {created: 10, stage: 'comparing', progress: {assess_images: 'complete'}};
  context.Date.now = () => 16000;
  vm.runInContext('renderProgress(run)', context);
  assert.equal(replacements, 0);
  assert.equal(elapsed.textContent, '00:06');
  assert.equal(rows[2].querySelector('.stage-state').textContent, 'Done');
  assert.equal(rows[4].querySelector('.stage-state').textContent, 'Working');
  assert.deepEqual(rows, originalRows);
});
