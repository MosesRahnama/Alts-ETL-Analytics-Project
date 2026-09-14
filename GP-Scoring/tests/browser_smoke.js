async (page) => {
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.reload();
  const data = await page.locator('#report-data').textContent();
  const packets = JSON.parse(data).packets;
  const defaultManagers = packets.filter(p => p.strategy === 'buyout' && p.status === 'RANKED_DEMO');
  await page.getByRole('combobox', {name: 'Scored manager (fictional)', exact: true}).selectOption(defaultManagers[1].key);
  if (!(await page.locator('#track').evaluate(node => node.classList.contains('active')))) throw Error('Manager selection did not open the track record');
  if (!(await page.locator('#track-content h2').textContent()).includes(defaultManagers[1].manager_name)) throw Error('Selected manager did not render');
  const views = ['Screener', 'Manager Comparison', 'Track Record & Peers', 'Realization & Stress', 'Holdings & Terms', 'Team / Governance', 'Evidence & Diligence', 'RAG: Document Insights'];
  for (const name of views) {
    await page.getByRole('button', {name, exact: true}).click();
    if (!(await page.locator('.view.active').textContent()).trim()) throw Error('Empty view: ' + name);
  }
  let selections = 0;
  for (const strategy of [...new Set(packets.map(p => p.strategy))]) {
    await page.getByRole('combobox', {name: 'Strategy', exact: true}).selectOption(strategy);
    for (const status of ['RANKED_DEMO', 'PARTIAL_TRACK_RECORD', 'INSUFFICIENT_DATA', 'ALL']) {
      await page.getByRole('combobox', {name: 'Status', exact: true}).selectOption(status);
      const expected = packets.filter(p => p.strategy === strategy && (status === 'ALL' || p.status === status)).length;
      const actual = await page.locator('#manager option').count();
      if (expected !== actual) throw Error('Selection count differs');
      selections++;
    }
  }
  let cases = 0;
  const urls = new Set();
  for (const packet of packets.filter(p => p.case?.status === 'AVAILABLE')) {
    await page.getByRole('combobox', {name: 'Strategy', exact: true}).selectOption(packet.strategy);
    await page.getByRole('combobox', {name: 'Status', exact: true}).selectOption('RANKED_DEMO');
    await page.getByRole('combobox', {name: 'Scored manager (fictional)', exact: true}).selectOption(packet.key);
    await page.getByRole('button', {name: 'Holdings & Terms', exact: true}).click();
    const heading = page.getByRole('heading', {name: 'Company operating downside', exact: true});
    if (await heading.count() !== 1) throw Error('Operating analysis missing');
    await heading.scrollIntoViewIfNeeded();
    if (!cases) await page.screenshot({path: 'gp-operating-analysis.png'});
    for (const link of await page.locator('main a[href]').evaluateAll(nodes => nodes.map(n => n.href))) urls.add(link);
    cases++;
  }
  for (const url of urls) {
    const response = await page.request.get(url.split('#')[0]);
    if (!response.ok()) throw Error('Broken report link: ' + url);
  }
  await page.getByRole('combobox', {name: 'Strategy', exact: true}).selectOption('buyout');
  await page.getByRole('button', {name: 'Manager Comparison', exact: true}).click();
  const controls = page.locator('#comparison-controls select');
  if (await controls.count() !== 3) throw Error('Comparison controls missing');
  await controls.nth(1).selectOption(packets.filter(p => p.strategy === 'buyout' && p.status === 'RANKED_DEMO')[4].key);
  await page.getByRole('heading', {name: 'Manager comparison', exact: true}).scrollIntoViewIfNeeded();
  await page.screenshot({path: 'gp-manager-comparison.png'});
  await page.setViewportSize({width: 390, height: 844});
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth > innerWidth);
  if (overflow) throw Error('Mobile page has horizontal overflow');
  await page.screenshot({path: 'gp-mobile.png'});
  await page.setViewportSize({width: 1440, height: 1000});
  if (errors.length) throw Error(errors.join('; '));
  return {views: views.length, selections, cases, links: urls.size, comparison: 'PASS', mobile: 'PASS', pageErrors: errors.length};
}
