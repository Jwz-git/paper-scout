// 定向浏览器回归：人工会话与来源样例；所有页面资源/API在本地拦截，不启动服务器或访问外部服务。
// 先 npm install --prefix temp/ui-verification --no-save --package-lock=false playwright-core@1.64.1
// 然后前端 npm run build；仓库根目录 node tests/browser_conversation.mjs
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';
import { createRequire } from 'node:module';

const root = process.cwd();
const require = createRequire(path.join(root, 'temp/ui-verification/package.json'));
const { chromium } = require('playwright-core');
const output = path.join(root, 'temp/ui-verification');
await fs.mkdir(output, { recursive: true });
const now = '2026-11-03T00:00:00+00:00';
const task = (id, topic) => ({ id, topic, focus_dimensions: [], created_at: now, updated_at: now });
const taskA = task('offline-a', '离线示例A：通信资料');
const taskB = task('offline-b', '离线示例B：其他问题');
const quote = '原文验证片段';
const source = { id: 'offline-source', paper_id: 'offline-paper', source_type: 'fulltext', source_url: 'https://arxiv.org/pdf/0000.00000', page_number: 2, content: `🙂${quote}，这是人工界面样例，不是真实论文。`, status: 'ok', fetched_at: now };
const paper = { id: 'offline-paper', title: '人工文献样例（非真实论文）', authors: [], year: 2024, source: 'arxiv', source_id: 'offline-fixture', url: 'https://arxiv.org/abs/0000.00000', fetched_at: now, abstract: '这是离线界面验证的人工摘要。' };
const citation = { source_text_id: source.id, paper_id: paper.id, run_id: 'offline-run', source_type: source.source_type, source_url: source.source_url, page_number: 2, quote, location_start: 1, location_end: 1 + Array.from(quote).length };
const run = { id: 'offline-run', task_id: taskA.id, initial_topic: taskA.topic, initial_input: { topic: taskA.topic, focus_dimensions: [] }, current_input: { topic: taskA.topic, focus_dimensions: [] }, status: 'running', stage: 'searching', current_round: 1, max_rounds: 3, max_calls: 20, max_seconds: 900, total_calls: 2, total_execution_seconds: 3.5, model_calls: 1, token_usage: { prompt_tokens: null, completion_tokens: null, total_tokens: null }, gaps: [], created_at: now };
const usage = { model_calls: 1, max_calls: 40, total_execution_seconds: 1.2, max_seconds: 900, token_usage: { prompt_tokens: null, completion_tokens: null, total_tokens: null } };
const message = (id, taskId, role, content, extra = {}) => ({ id, task_id: taskId, role, content, status: 'completed', citations: [], created_at: now, ...extra });
let viewA = { task: taskA, messages: [message('a-user', taskA.id, 'user', '人工会话A的原始问题'), message('a-answer', taskA.id, 'assistant', '这条回答引用已保存的人工来源样例，语义支持仍需复核。', { action: 'answer', run_id: run.id, citations: [citation] })], runs: [run], usage, busy: false, model_configured: true };
const viewB = { task: taskB, messages: [message('b-user', taskB.id, 'user', '人工会话B的原始问题')], runs: [], usage, busy: false, model_configured: true };
const posts = [];
const creationPosts = [];
const controlOnly = process.env.BROWSER_SCENARIO === 'controls';
const settingsOnly = process.env.BROWSER_SCENARIO === 'settings';
const basicsOnly = process.env.BROWSER_SCENARIO === 'basics';
const themeOnly = process.env.BROWSER_SCENARIO === 'theme';
const preferencesOnly = process.env.BROWSER_SCENARIO === 'preferences';
const trashOnly = process.env.BROWSER_SCENARIO === 'trash';
const usageOnly = process.env.BROWSER_SCENARIO === 'usage';
const catalogOnly = process.env.BROWSER_SCENARIO === 'catalog';
const catalogPosts = [];
let rejectCatalog = false;
let holdCatalog = false;
let releaseCatalog, signalCatalog, settleCatalog;
const catalogStarted = new Promise(resolve => { signalCatalog = resolve; });
const catalogReleased = new Promise(resolve => { releaseCatalog = resolve; });
const catalogSettled = new Promise(resolve => { settleCatalog = resolve; });
if (usageOnly) {
  viewA = { ...viewA, usage: { ...usage, model_calls: 3, max_calls: 10, max_seconds: 120, total_execution_seconds: 59.96, token_usage: { total_tokens: 12400, prompt_tokens: 12000, completion_tokens: 400 } }, runs: [
    { ...run, id: 'usage-old', created_at: '2026-11-02T00:00:00Z', status: 'partial', total_calls: 5, max_calls: 5, current_round: 2, max_rounds: 2, total_execution_seconds: 60.06, max_seconds: 60, model_calls: 2, token_usage: { total_tokens: null, prompt_tokens: 500, completion_tokens: null }, stop_reason: '达到调用上限，保留阶段性资料。' },
    { ...run, total_calls: 8, max_calls: 12, total_execution_seconds: 12, max_seconds: 600, current_round: 2, max_rounds: 4, model_calls: 3 },
  ] };
}
let deletedFixtures = trashOnly ? Array.from({ length: 57 }, (_, index) => ({ ...task(`trashed-${index}`, `人工研究方向 ${index}`), title: `已删除的研究 ${String(index).padStart(3, '0')}`, deleted_at: new Date(Date.parse(now) - (57 - index) * 60000).toISOString() })) : [];
const trashPosts = [];
let rejectNextTrashAction = false;
let rejectNextTrashRead = false;
let holdTrashAction = false;
let releaseTrashAction, signalTrashAction;
const trashActionStarted = new Promise(resolve => { signalTrashAction = resolve; });
const trashActionReleased = new Promise(resolve => { releaseTrashAction = resolve; });
let modelSettings = { enabled: false, protocol: 'openai_chat', base_url: '', model: '', api_key_set: false, source: 'environment', busy: false, active_provider_id: null, active_model: null, providers: [], limits: { research: { max_rounds: 3, max_calls: 20, max_seconds: 900 }, conversation: { max_calls: 40, max_seconds: 900 } } };
const settingsPosts = [];
let holdSettingsSave = false;
let rejectNextSettingsSave = false;
let releaseSettingsSave;
let signalSettingsSave;
const settingsSaveStarted = new Promise(resolve => { signalSettingsSave = resolve; });
const settingsSaveReleased = new Promise(resolve => { releaseSettingsSave = resolve; });
function updateActiveModel() {
  const active = modelSettings.providers.find(item => item.id === modelSettings.active_provider_id);
  Object.assign(modelSettings, { protocol: active?.protocol || 'openai_chat', base_url: active?.base_url || '', model: modelSettings.active_model || '', api_key_set: active?.api_key_set || false });
}
const selectionPosts = [];

const taskC = task('offline-create', '离线首轮对话示例');
let viewC = null;
let stopped = false;
let releaseStalePoll;
let signalStalePoll;
const stalePollStarted = new Promise(resolve => { signalStalePoll = resolve; });
const stalePollReleased = new Promise(resolve => { releaseStalePoll = resolve; });
let firstPost = true;
let blockB = false;
let releaseB;
let beginB;
const bStarted = new Promise(resolve => { beginB = resolve; });
const bRelease = new Promise(resolve => { releaseB = resolve; });
const browser = await chromium.launch({ headless: true, executablePath: process.env.CHROME_EXECUTABLE || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome' });
const context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, locale: 'zh-CN', timezoneId: 'Asia/Shanghai', reducedMotion: 'reduce', colorScheme: themeOnly ? 'dark' : 'light' });
const errors = [];
const page = await context.newPage();
page.setDefaultTimeout(8000);
page.on('pageerror', error => errors.push(error.message));
await context.route('**/*', async route => {
  const url = new URL(route.request().url());
  if (url.origin !== 'http://127.0.0.1:5173') return route.abort();
  const json = value => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(value) });
  if (url.pathname === '/api/settings') return json(modelSettings);
  if (url.pathname === '/api/settings/selection') {
    const payload = route.request().postDataJSON(); selectionPosts.push(payload);
    modelSettings.enabled = true; modelSettings.active_provider_id = payload.provider_id; modelSettings.active_model = payload.model;
    updateActiveModel(); return json(modelSettings);
  }
  if (url.pathname === '/api/settings/models') {
    const payload = route.request().postDataJSON(); catalogPosts.push(payload);
    if (rejectCatalog) { rejectCatalog = false; return route.fulfill({ status: 502, contentType: 'application/json', body: JSON.stringify({ detail: '人工列表接口不支持，可手动添加模型 ID。' }) }); }
    if (holdCatalog) { signalCatalog(); await catalogReleased; }
    const models = payload.cursor ? [{ id: 'catalog-c', name: '人工模型 C' }] : [{ id: 'catalog-a', name: '人工模型 A' }, { id: 'catalog-b', name: '人工模型 B' }];
    await json({ models, next_cursor: payload.cursor ? null : 'page-two' });
    if (holdCatalog) settleCatalog();
    return;
  }
  if (url.pathname.startsWith('/api/settings/providers')) {
    const id = url.pathname.split('/')[4];
    if (url.pathname.endsWith('/delete')) {
      modelSettings.providers = modelSettings.providers.filter(item => item.id !== id);
      if (modelSettings.active_provider_id === id) { modelSettings.active_provider_id = null; modelSettings.active_model = null; modelSettings.enabled = false; }
      updateActiveModel(); return json(modelSettings);
    }
    const payload = route.request().postDataJSON(); settingsPosts.push(payload);
    if (rejectNextSettingsSave) { rejectNextSettingsSave = false; return route.fulfill({ status: 500, contentType: 'application/json', body: JSON.stringify({ detail: '人工供应商保存失败，请稍后重试' }) }); }
    if (holdSettingsSave) { signalSettingsSave(); await settingsSaveReleased; }
    const providerId = id || `offline-provider-${settingsPosts.length}`;
    const previous = modelSettings.providers.find(item => item.id === providerId);
    const provider = { id: providerId, name: payload.name || new URL(payload.base_url).hostname, protocol: payload.protocol, base_url: payload.base_url, models: payload.models, api_key_set: payload.clear_api_key ? false : !!payload.api_key || !!previous?.api_key_set };
    modelSettings.providers = previous ? modelSettings.providers.map(item => item.id === id ? provider : item) : [...modelSettings.providers, provider];
    if (modelSettings.active_provider_id === providerId && !provider.models.includes(modelSettings.active_model)) { modelSettings.active_provider_id = null; modelSettings.active_model = null; modelSettings.enabled = false; }
    modelSettings.source = 'local'; updateActiveModel(); return json({ provider_id: providerId, settings: modelSettings });
  }
  const everyTask = () => [...(viewC ? [taskC, taskA, taskB] : [taskA, taskB]), ...deletedFixtures];
  if (url.pathname === '/api/conversations/trash') {
    if (rejectNextTrashRead) { rejectNextTrashRead = false; return route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ detail: '人工读取失败' }) }); }
    const all = everyTask().filter(task => task.deleted_at);
    const query = (url.searchParams.get('query') || '').toLowerCase();
    const sort = url.searchParams.get('sort');
    const filtered = all.filter(task => `${task.title || ''} ${task.topic}`.toLowerCase().includes(query));
    filtered.sort((a, b) => sort === 'title' ? (a.title || a.topic).localeCompare(b.title || b.topic) : sort === 'oldest' ? a.deleted_at.localeCompare(b.deleted_at) : b.deleted_at.localeCompare(a.deleted_at));
    const offset = Number(url.searchParams.get('offset') || 0), limit = Number(url.searchParams.get('limit') || 50);
    return json({ items: filtered.slice(offset, offset + limit), total: all.length, matched: filtered.length });
  }
  if (/^\/api\/conversations\/trash\/(restore|delete)$/.test(url.pathname)) {
    const payload = route.request().postDataJSON(); const operation = url.pathname.split('/').at(-1);
    trashPosts.push({ operation, ...payload });
    if (holdTrashAction) { signalTrashAction(); await trashActionReleased; }
    if (rejectNextTrashAction) { rejectNextTrashAction = false; return route.fulfill({ status: 409, contentType: 'application/json', body: JSON.stringify({ detail: '人工在途请求未结束，请稍后重试' }) }); }
    const targets = everyTask().filter(task => task.deleted_at && (payload.ids === null || payload.ids.includes(task.id)));
    if (operation === 'restore') { for (const item of targets) item.deleted_at = null; return json({ tasks: targets }); }
    deletedFixtures = deletedFixtures.filter(item => !targets.includes(item));
    return json({ ids: targets.map(task => task.id) });
  }
  if (/\/api\/conversations\/[^/]+\/(rename|trash|restore)$/.test(url.pathname)) {
    const [, , , id, operation] = url.pathname.split('/');
    const item = [taskA, taskB, taskC].find(task => task.id === id);
    if (operation === 'rename') item.title = route.request().postDataJSON().title;
    if (operation === 'trash') { item.deleted_at = now; if (id === taskA.id) viewA = { ...viewA, busy: false, runs: viewA.runs.map(item => ({ ...item, status: 'cancelled' })) }; }
    if (operation === 'restore') item.deleted_at = null;
    return json(item);
  }
  if (url.pathname === '/api/health') return json({ status: 'ok', app: 'Paper Scout', version: '0.1.0' });
  if (url.pathname === '/api/conversations') {
    if (route.request().method() !== 'POST') return json(everyTask().filter(task => !!task.deleted_at === (url.searchParams.get('deleted') === 'true')));
    const payload = route.request().postDataJSON();
    creationPosts.push(payload);
    if (!viewC) {
      viewC = { task: taskC, messages: [message('c-user', taskC.id, 'user', payload.content), message('c-answer', taskC.id, 'assistant', '', { status: 'processing' })], runs: [], usage, busy: true, model_configured: true };
      return route.abort('failed');
    }
    return route.fulfill({ status: 202, contentType: 'application/json', body: JSON.stringify(viewC) });
  }
  if (url.pathname === `/api/conversations/${taskC.id}/stop`) {
    stopped = true;
    viewC = { ...viewC, busy: false, messages: [viewC.messages[0], { ...viewC.messages[1], status: 'interrupted', error_category: 'user_cancelled', content: '用户已停止本条对话；迟到的模型结果不会启动研究。' }] };
    return json(viewC);
  }
  if (url.pathname === `/api/conversations/${taskC.id}`) {
    if (!stopped) {
      const captured = structuredClone(viewC);
      signalStalePoll();
      await stalePollReleased;
      return json(captured);
    }
    return json(viewC);
  }
  if (url.pathname === `/api/conversations/${taskA.id}`) return json(viewA);
  if (url.pathname === `/api/conversations/${taskB.id}`) {
    if (blockB) { beginB(); await bRelease; }
    return json(viewB);
  }
  if (url.pathname === `/api/conversations/${taskA.id}/messages`) {
    const payload = route.request().postDataJSON();
    posts.push(payload);
    if (preferencesOnly) {
      viewA = { ...viewA, messages: [...viewA.messages, message(`preferences-${posts.length}`, taskA.id, 'user', payload.content)] };
      return route.fulfill({ status: 202, contentType: 'application/json', body: JSON.stringify(viewA) });
    }
    if (firstPost) {
      firstPost = false;
      viewA = { ...viewA, messages: [...viewA.messages, message('supplement-user', taskA.id, 'user', payload.content), message('supplement-answer', taskA.id, 'assistant', '补充已收到（离线样例）', { action: 'research', run_id: run.id })] };
      return route.abort('failed'); // 服务端已保存，但响应不确定；客户端必须重试原request_id。
    }
    return route.fulfill({ status: 202, contentType: 'application/json', body: JSON.stringify(viewA) });
  }
  if (url.pathname === `/api/runs/${run.id}/events`) return json([{ id: 'event-1', run_id: run.id, stage: 'searching', category: 'search', message: '人工检索过程记录', created_at: now }]);
  if (url.pathname === `/api/runs/${run.id}/papers`) return json([paper]);
  if (url.pathname === `/api/runs/${run.id}/papers/${paper.id}`) return json({ paper, sources: [source], evidence: [] });
  if (url.pathname === `/api/runs/${run.id}/report`) return json({ id: 'offline-report', run_id: run.id, title: '人工阶段性报告', content_markdown: '# 人工离线报告\n\n非真实研究结果。', gaps: ['人工样例，不用于科研结论。'], stop_reason: '离线界面验证' });
  if (url.pathname === `/api/runs/${run.id}/report.md`) return route.fulfill({ contentType: 'text/markdown', body: '# 人工离线报告\n非真实研究结果。' });
  if (url.pathname.startsWith('/api/')) throw new Error(`Unexpected mocked API: ${url.pathname}`);
  const relative = url.pathname === '/' ? 'index.html' : decodeURIComponent(url.pathname.slice(1));
  const target = path.resolve(root, 'frontend/dist', relative);
  assert.ok(target.startsWith(path.join(root, 'frontend/dist') + path.sep));
  const types = { '.html': 'text/html', '.js': 'application/javascript', '.css': 'text/css', '.svg': 'image/svg+xml', '.png': 'image/png' };
  return route.fulfill({ contentType: types[path.extname(target)] || 'application/octet-stream', body: await fs.readFile(target) });
});
async function chooseModelId(id) {
  const picker = page.locator('.model-picker');
  if (!await picker.getAttribute('open')) await page.getByLabel('选择模型', { exact: true }).click();
  const clear = picker.getByRole('button', { name: '清除选择', exact: true });
  if (await clear.isEnabled()) await clear.click();
  await page.locator('#model-name').fill(id);
  await picker.locator('.model-picker-manual').click();
  await page.keyboard.press('Escape');
}
async function openModelSettings() {
  await page.getByRole('button', { name: '打开设置', exact: true }).click();
  await page.getByRole('button', { name: 'AI服务', exact: true }).click();
}
try {
  await page.goto('http://127.0.0.1:5173/');
  const composer = page.getByRole('textbox', { name: '输入消息', exact: true });
  await composer.waitFor();
  assert.equal(await composer.inputValue(), '');
  assert.equal(await page.locator('.stage-stepper').count(), 0);
  await page.screenshot({ path: path.join(output, 'conversation-empty.png'), fullPage: true });
  console.log('PASS empty conversational workspace; no prefilled fake task/stepper');

  if (catalogOnly || settingsOnly) {
    await composer.fill('配置AI服务时保留的草稿');
    await openModelSettings();
    await page.getByRole('heading', { name: 'AI服务', exact: true }).waitFor();
    assert.equal(await page.locator('.settings-footer').count(), 0);
    await page.getByRole('button', { name: '添加供应商', exact: true }).click();
    await page.locator('#provider-name').fill('人工供应商 A');
    await page.locator('#model-protocol').selectOption('anthropic_messages');
    await page.locator('#model-base-url').fill('https://offline.example/v1');
    await page.locator('#model-api-key').fill('artificial-catalog-secret');
    await page.getByRole('button', { name: '获取模型', exact: true }).click();
    await page.getByText('已获取 2 个模型，可加载更多。', { exact: true }).waitFor();
    assert.equal(catalogPosts[0].provider_id, null);
    await page.getByLabel('选择模型', { exact: true }).click();
    await page.getByRole('checkbox', { name: '选择模型：catalog-a', exact: true }).check();
    await page.getByRole('checkbox', { name: '选择模型：catalog-b', exact: true }).check();
    await page.getByRole('textbox', { name: '搜索或输入模型 ID', exact: true }).fill('模型 B');
    assert.equal(await page.getByRole('checkbox', { name: '选择模型：catalog-a', exact: true }).count(), 0);
    assert.equal(await page.getByRole('checkbox', { name: '选择模型：catalog-b', exact: true }).isChecked(), true);
    await page.getByRole('textbox', { name: '搜索或输入模型 ID', exact: true }).fill('');
    await page.locator('.model-picker').scrollIntoViewIfNeeded();
    await page.screenshot({ path: path.join(output, 'ai-provider-models-light.png'), fullPage: true });
    await page.keyboard.press('Escape');
    assert.equal(await page.getByRole('dialog', { name: '设置', exact: true }).isVisible(), true);
    rejectNextSettingsSave = true;
    await page.getByRole('button', { name: '保存供应商', exact: true }).click();
    await page.getByText('人工供应商保存失败，请稍后重试', { exact: false }).waitFor();
    assert.equal(modelSettings.providers.length, 0);
    assert.equal(await page.locator('.model-picker-chips > span').count(), 2);
    await page.getByRole('button', { name: '保存供应商', exact: true }).click();
    await page.getByText('供应商已添加', { exact: true }).waitFor();
    assert.equal(modelSettings.providers.length, 1);
    assert.equal(modelSettings.enabled, false);
    assert.equal(modelSettings.active_provider_id, null);
    assert.equal(selectionPosts.length, 0, 'saving never selects a provider/model');
    assert.equal(await page.locator('.provider-use-row, .model-use-button').count(), 0);
    assert.equal(await page.getByRole('button', { name: /^使用/ }).count(), 0);
    const aid = modelSettings.providers[0].id;
    await page.getByRole('button', { name: '关闭设置', exact: true }).click();
    assert.equal(await composer.inputValue(), '配置AI服务时保留的草稿');
    assert.equal(await page.getByRole('button', { name: '发送消息', exact: true }).isDisabled(), true);
    await page.getByLabel('选择当前模型', { exact: true }).click();
    await page.getByRole('button', { name: '人工供应商 A · catalog-b', exact: true }).click();
    await page.getByText('已切换当前模型', { exact: true }).waitFor();
    assert.equal(modelSettings.active_provider_id, aid);
    assert.equal(modelSettings.active_model, 'catalog-b');
    assert.equal(await page.getByRole('button', { name: '发送消息', exact: true }).isEnabled(), true);
    await openModelSettings();
    await page.getByRole('button', { name: '编辑供应商：人工供应商 A', exact: true }).click();
    assert.equal(await page.locator('#model-api-key').inputValue(), '');
    await page.getByRole('button', { name: '获取模型', exact: true }).click();
    await page.getByText('已获取 2 个模型，可加载更多。', { exact: true }).waitFor();
    assert.equal(catalogPosts.at(-1).api_key, null);
    assert.equal(catalogPosts.at(-1).provider_id, aid);
    await page.getByLabel('选择模型', { exact: true }).click();
    await page.getByRole('button', { name: '加载更多', exact: true }).click();
    await page.getByRole('checkbox', { name: '选择模型：catalog-c', exact: true }).check();
    await page.keyboard.press('Escape');
    await page.getByRole('button', { name: '保存供应商', exact: true }).click();
    await page.getByText('供应商已更新', { exact: true }).waitFor();
    assert.equal(modelSettings.providers.length, 1, 'multiple models stay in one provider');
    assert.deepEqual(modelSettings.providers[0].models, ['catalog-a', 'catalog-b', 'catalog-c']);
    assert.equal(modelSettings.active_model, 'catalog-b');
    await page.getByRole('button', { name: '添加供应商', exact: true }).click();
    await page.locator('#provider-name').fill('人工供应商 B');
    await page.locator('#model-base-url').fill('https://stale.example/v1');
    holdCatalog = true;
    await page.getByRole('button', { name: '获取模型', exact: true }).click(); await catalogStarted;
    await page.locator('#model-base-url').fill('https://changed.example/v1');
    releaseCatalog(); await catalogSettled;
    assert.equal(await page.locator('.model-catalog-status').count(), 0);
    holdCatalog = false; rejectCatalog = true;
    await page.getByRole('button', { name: '获取模型', exact: true }).click();
    await page.getByText('人工列表接口不支持，可手动添加模型 ID。', { exact: false }).waitFor();
    await chooseModelId('manual-offline-model');
    await page.getByRole('button', { name: '供应商列表', exact: true }).click();
    await page.getByRole('dialog', { name: '放弃本次编辑？', exact: true }).waitFor();
    await page.keyboard.press('Escape');
    assert.equal(await page.locator('.model-picker-chips').innerText(), 'manual-offline-model');
    await page.getByRole('button', { name: '保存供应商', exact: true }).click();
    await page.getByText('供应商已添加', { exact: true }).waitFor();
    assert.equal(modelSettings.providers.length, 2);
    assert.equal(modelSettings.active_model, 'catalog-b');
    assert.equal(selectionPosts.length, 1);
    const bid = modelSettings.providers[1].id;
    await page.screenshot({ path: path.join(output, 'ai-services-light.png'), fullPage: true });
    await page.emulateMedia({ colorScheme: 'dark' });
    await page.screenshot({ path: path.join(output, 'ai-services-dark.png'), fullPage: true });
    await page.setViewportSize({ width: 320, height: 700 });
    assert.equal(await page.locator('.settings-dialog').evaluate(element => element.scrollWidth <= element.clientWidth), true);
    await page.screenshot({ path: path.join(output, 'ai-services-mobile.png'), fullPage: true });
    await page.getByRole('button', { name: '编辑供应商：人工供应商 B', exact: true }).click();
    await page.getByRole('button', { name: '获取模型', exact: true }).click();
    await page.getByText('已获取 2 个模型，可加载更多。', { exact: true }).waitFor();
    await page.getByLabel('选择模型', { exact: true }).click();
    await page.locator('.model-picker').scrollIntoViewIfNeeded();
    assert.equal(await page.locator('.model-picker').evaluate(element => element.scrollWidth <= element.clientWidth), true);
    await page.screenshot({ path: path.join(output, 'ai-provider-models-mobile.png'), fullPage: true });
    await page.keyboard.press('Escape'); await page.keyboard.press('Escape');
    await page.setViewportSize({ width: 1440, height: 1000 });
    modelSettings.busy = true;
    await openModelSettings();
    assert.equal(await page.getByRole('button', { name: '编辑供应商：人工供应商 A', exact: true }).isDisabled(), true);
    assert.equal(await page.getByRole('button', { name: '编辑供应商：人工供应商 B', exact: true }).isEnabled(), true);
    modelSettings.busy = false;
    await page.getByRole('button', { name: '刷新状态', exact: true }).click();
    await page.getByRole('button', { name: '编辑供应商：人工供应商 B', exact: true }).click();
    await page.locator('#provider-name').fill('人工供应商 B 更新');
    holdSettingsSave = true;
    await page.getByRole('button', { name: '保存供应商', exact: true }).click(); await settingsSaveStarted;
    await page.getByRole('button', { name: '关闭设置', exact: true }).click(); releaseSettingsSave();
    await page.locator('.workspace-notice').filter({ hasText: '供应商已更新' }).waitFor();
    holdSettingsSave = false;
    await page.getByLabel('选择当前模型', { exact: true }).click();
    await page.getByRole('button', { name: '人工供应商 B 更新 · manual-offline-model', exact: true }).click();
    await page.getByText('已切换当前模型', { exact: true }).waitFor();
    assert.equal(modelSettings.active_provider_id, bid);
    await openModelSettings();
    await page.getByRole('button', { name: '编辑供应商：人工供应商 B 更新', exact: true }).click();
    await chooseModelId('manual-replacement');
    await page.getByText('当前使用的型号已移出。保存后请在对话中重新选择模型。', { exact: true }).waitFor();
    await page.getByRole('button', { name: '保存供应商', exact: true }).click();
    await page.getByText('供应商已更新', { exact: true }).waitFor();
    assert.equal(modelSettings.enabled, false);
    await page.getByRole('button', { name: '删除供应商：人工供应商 A', exact: true }).click();
    await page.getByRole('button', { name: '取消', exact: true }).click();
    assert.equal(modelSettings.providers.length, 2);
    await page.getByRole('button', { name: '删除供应商：人工供应商 A', exact: true }).click();
    await page.getByRole('button', { name: '删除供应商', exact: true }).click();
    await page.getByText('供应商已删除', { exact: true }).waitFor();
    assert.equal(modelSettings.providers.length, 1);
    assert.equal(await page.evaluate(() => localStorage.length), 0);
    assert.deepEqual(errors, []);
    console.log('PASS provider credentials/model lists, catalog search/pagination/errors/stale replies, atomic save/retry, migration-shaped data and no automatic model selection');
    console.log('PASS model choice only in chat, provider edits retain current model, removed model clears selection, busy restrictions, delayed close, dark/mobile UI and confirmed provider deletion');
  } else if (usageOnly) {
    await composer.fill('用量查看时保留的草稿');
    async function openUsage() { await page.getByRole('button', { name: '打开设置', exact: true }).click(); await page.getByRole('button', { name: '研究与用量', exact: true }).click(); }
    await openUsage();
    await page.getByRole('button', { name: '执行上限', exact: true, pressed: true }).waitFor();
    assert.deepEqual(await page.locator('.usage-limit-rows dd').allTextContents(), ['40 次', '15 分钟', '3 轮', '20 次', '15 分钟']);
    assert.equal(await page.locator('.research-usage input').count(), 0);
    await page.screenshot({ path: path.join(output, 'usage-limits-light.png'), fullPage: true });
    await page.getByRole('button', { name: '用量概览', exact: true }).click();
    await page.getByRole('heading', { name: '选择对话后查看用量', exact: true }).waitFor();
    assert.equal(await page.getByRole('progressbar').count(), 0);
    await page.getByRole('button', { name: '返回对话', exact: true }).click();
    assert.equal(await composer.inputValue(), '用量查看时保留的草稿');
    await page.getByRole('button', { name: /离线示例A/ }).click();
    await page.getByText('人工会话A的原始问题', { exact: true }).waitFor();
    await openUsage();
    const calls = page.getByRole('progressbar', { name: '对话模型调用', exact: true });
    assert.equal(await calls.getAttribute('aria-valuemax'), '10');
    assert.equal(await calls.getAttribute('aria-valuenow'), '3');
    assert.equal(await page.getByRole('progressbar', { name: '对话执行时间', exact: true }).getAttribute('aria-valuetext'), '1 分钟，上限 2 分钟');
    assert.deepEqual(await page.getByLabel('对话 Token', { exact: true }).locator('dd').allTextContents(), ['12,400', '12,000', '400']);
    const runSelect = page.getByLabel('查看调研', { exact: true });
    assert.equal(await runSelect.inputValue(), run.id, 'latest research selected despite response order');
    assert.equal(await page.getByRole('progressbar', { name: '调研外部调用', exact: true }).getAttribute('aria-valuemax'), '12');
    assert.deepEqual(await page.getByLabel('调研 Token', { exact: true }).locator('dd').allTextContents(), ['未知', '未知', '未知']);
    await runSelect.selectOption('usage-old');
    await page.locator('.research-usage').getByText('达到调用上限，保留阶段性资料。', { exact: true }).waitFor();
    assert.equal(await page.getByRole('progressbar', { name: '调研执行时间', exact: true }).getAttribute('aria-valuenow'), '60');
    assert.deepEqual(await page.getByLabel('调研 Token', { exact: true }).locator('dd').allTextContents(), ['未知', '500', '未知']);
    assert.equal(await page.locator('.usage-research .usage-meter-title').getByText('已达上限', { exact: true }).count(), 2);
    viewA = { ...viewA, usage: { ...viewA.usage, model_calls: 4 } };
    await page.locator('[aria-label="对话模型调用"][aria-valuenow="4"]').waitFor();
    assert.equal(await runSelect.inputValue(), 'usage-old', 'polling preserves explicitly chosen research');
    await runSelect.selectOption(run.id);
    await page.screenshot({ path: path.join(output, 'usage-overview-light.png'), fullPage: true });
    await page.emulateMedia({ colorScheme: 'dark' });
    await page.screenshot({ path: path.join(output, 'usage-overview-dark.png'), fullPage: true });
    await page.getByRole('button', { name: '执行上限', exact: true }).click();
    await page.screenshot({ path: path.join(output, 'usage-limits-dark.png'), fullPage: true });
    await page.setViewportSize({ width: 320, height: 640 });
    for (const view of ['执行上限', '用量概览']) {
      await page.getByRole('button', { name: view, exact: true }).click();
      for (const selector of ['.settings-dialog', '.settings-scroll', '.research-usage']) assert.equal(await page.locator(selector).evaluate(element => element.scrollWidth <= element.clientWidth), true);
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
      await page.screenshot({ path: path.join(output, view === '执行上限' ? 'usage-limits-mobile.png' : 'usage-overview-mobile.png'), fullPage: true });
    }
    await page.getByText('用量如何计算', { exact: true }).click();
    await page.getByText('Token 显示“未知”表示未取得完整统计，不会按 0 计入。', { exact: true }).waitFor();
    await page.screenshot({ path: path.join(output, 'usage-accounting-mobile.png'), fullPage: true });
    await page.keyboard.press('Escape');
    await page.setViewportSize({ width: 1440, height: 1000 });
    await page.getByRole('button', { name: /离线示例B/ }).click();
    await page.getByText('人工会话B的原始问题', { exact: true }).waitFor();
    await openUsage();
    await page.getByText('此对话尚未发起调研，后续记录会显示在这里。', { exact: true }).waitFor();
    assert.equal(await page.locator('#usage-run-select').count(), 0);
    assert.equal(await calls.getAttribute('aria-valuemax'), '40');
    assert.equal(settingsPosts.length + posts.length + creationPosts.length + trashPosts.length, 0);
    assert.deepEqual(errors, []);
    console.log('PASS usage/default limits separation, actual conversation/run limits, run switching and polling, unknown/partial Token, time formatting and limit progress semantics');
    console.log('PASS no-conversation/no-research states, dark/light and 320px layouts, accounting disclosure, close/draft preservation and no mutations/model calls');
  } else if (trashOnly) {
    await composer.fill('回收站管理期间保留的草稿');
    await page.getByRole('button', { name: '回收站', exact: true }).click();
    const recycle = page.locator('.trash-dialog');
    const rows = recycle.locator('.trash-row');
    await rows.first().waitFor();
    assert.equal(await rows.count(), 50);
    assert.equal(await page.locator('.history-select').count(), 2, 'sidebar remains conversation history');
    await page.getByRole('button', { name: '回收站下一页', exact: true }).click();
    await page.getByText('已删除的研究 000', { exact: true }).waitFor();
    assert.equal(await rows.count(), 7);
    await page.getByRole('button', { name: '回收站上一页', exact: true }).click();
    await page.getByText('已删除的研究 056', { exact: true }).waitFor();
    const search = page.getByRole('searchbox', { name: '搜索已删除的对话', exact: true });
    await search.fill('研究 00');
    await page.getByText('已删除的研究 000', { exact: true }).waitFor();
    assert.equal(await rows.count(), 10);
    await page.getByRole('checkbox', { name: '选择本页对话', exact: true }).check();
    await page.getByText('已选择 10 项', { exact: true }).waitFor();
    await search.fill('');
    await page.getByText('已删除的研究 056', { exact: true }).waitFor();
    assert.equal(await page.getByRole('button', { name: '恢复所选', exact: true }).count(), 0);
    await page.getByLabel('回收站排序', { exact: true }).selectOption('oldest');
    await page.getByText('已删除的研究 000', { exact: true }).waitFor();
    assert.equal(await rows.first().locator('strong').textContent(), '已删除的研究 000');
    await page.getByRole('checkbox', { name: '选择对话：已删除的研究 000', exact: true }).check();
    await page.getByRole('checkbox', { name: '选择对话：已删除的研究 001', exact: true }).check();
    await page.screenshot({ path: path.join(output, 'trash-light.png'), fullPage: true });
    await page.getByRole('button', { name: '恢复所选', exact: true }).click();
    await page.getByText('已恢复 2 个对话；研究不会自动重启', { exact: true }).waitFor();
    assert.equal(deletedFixtures.filter(task => task.deleted_at).length, 55);
    assert.equal(await page.locator('.history-select').count(), 4);
    console.log('PASS independent trash window, search, sort, pagination and batch restore update history without replacing sidebar');
    const remove = page.getByRole('button', { name: '彻底删除对话：已删除的研究 002', exact: true });
    await remove.click();
    const beforeCancel = trashPosts.length;
    await page.getByRole('button', { name: '取消', exact: true }).click();
    assert.equal(trashPosts.length, beforeCancel);
    await remove.click();
    rejectNextTrashAction = true;
    await page.getByRole('button', { name: '彻底删除', exact: true }).click();
    await page.locator('.action-dialog').getByRole('alert').waitFor();
    assert.equal(deletedFixtures.filter(task => task.deleted_at).length, 55);
    await page.getByRole('button', { name: '彻底删除', exact: true }).click();
    await page.getByText('已彻底删除 1 个对话', { exact: true }).waitFor();
    assert.equal(deletedFixtures.filter(task => task.deleted_at).length, 54);
    await search.fill('研究 03');
    await page.getByText('已删除的研究 030', { exact: true }).waitFor();
    await page.getByRole('button', { name: '全部恢复', exact: true }).click();
    await page.getByText(/恢复回收站中的全部 54 个对话/).waitFor();
    await page.getByRole('button', { name: '取消', exact: true }).click();
    await page.getByRole('button', { name: '清空回收站', exact: true }).click();
    await page.getByText(/永久删除回收站中的全部 54 个对话/).waitFor();
    await page.keyboard.press('Escape');
    assert.equal(await recycle.isVisible(), true);
    await search.fill('not-found');
    await page.getByText('没有找到相关对话', { exact: true }).waitFor();
    await page.getByRole('button', { name: '清除搜索', exact: true }).click();
    await rows.first().waitFor();
    rejectNextTrashRead = true;
    await page.getByRole('button', { name: '刷新回收站', exact: true }).click();
    await page.getByText('暂时无法读取回收站', { exact: true }).waitFor();
    await page.getByRole('button', { name: '重试', exact: true }).click();
    await rows.first().waitFor();
    await page.emulateMedia({ colorScheme: 'dark' });
    await page.screenshot({ path: path.join(output, 'trash-dark.png'), fullPage: true });
    await page.setViewportSize({ width: 320, height: 640 });
    await page.getByRole('checkbox', { name: '选择本页对话', exact: true }).check();
    assert.equal(await recycle.evaluate(element => element.scrollWidth <= element.clientWidth), true);
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
    await page.screenshot({ path: path.join(output, 'trash-mobile.png'), fullPage: true });
    await page.getByRole('button', { name: '取消选择', exact: true }).click();
    await page.getByRole('button', { name: '清空回收站', exact: true }).click();
    holdTrashAction = true;
    await page.getByRole('button', { name: '确认清空', exact: true }).click();
    await trashActionStarted;
    await page.getByRole('button', { name: '关闭对话操作', exact: true }).click();
    await page.getByRole('button', { name: '关闭回收站', exact: true }).click();
    assert.equal(await recycle.isVisible(), false);
    releaseTrashAction();
    await page.getByText('已彻底删除 54 个对话', { exact: true }).waitFor();
    assert.equal(deletedFixtures.filter(task => task.deleted_at).length, 0);
    assert.equal(trashPosts.at(-1).ids, null, 'clear applies to all pages, not only the current page');
    assert.equal(await composer.inputValue(), '回收站管理期间保留的草稿');
    await page.getByRole('button', { name: '打开对话列表', exact: true }).click();
    await page.getByRole('button', { name: '打开设置', exact: true }).click();
    await page.getByRole('button', { name: '数据管理', exact: true }).click();
    await page.getByRole('button', { name: '打开回收站', exact: true }).click();
    await page.getByText('回收站是空的', { exact: true }).waitFor();
    await page.keyboard.press('Escape');
    assert.equal(await page.getByRole('button', { name: '打开对话列表', exact: true }).evaluate(element => document.activeElement === element), true);
    assert.deepEqual(errors, []);
    console.log('PASS permanent deletion confirmation/cancel/failure/retry, clear all pages, close during pending delete, read failure, dark/mobile layout and both entrances/focus/draft preservation');
  } else if (preferencesOnly) {
    await page.getByRole('button', { name: '打开设置', exact: true }).click();
    await page.getByRole('heading', { name: '通用', exact: true }).waitFor();
    await page.locator('#send-shortcut').selectOption('modifier-enter');
    await page.locator('#default-message-mode').selectOption('ask');
    await page.getByRole('switch', { name: '自动跟随最新消息', exact: true }).uncheck();
    await page.screenshot({ path: path.join(output, 'settings-general.png'), fullPage: true });
    await page.getByRole('button', { name: '外观', exact: true }).click();
    await page.getByRole('radio', { name: '暗色', exact: true }).check();
    await page.locator('#reading-text-size').selectOption('large');
    await page.locator('#reading-width').selectOption('wide');
    await page.screenshot({ path: path.join(output, 'settings-reading.png'), fullPage: true });
    await page.getByRole('button', { name: '关闭设置', exact: true }).click();
    assert.equal(await composer.evaluate(element => getComputedStyle(element).fontSize), '17px');
    assert.equal(await page.locator('html').evaluate(element => getComputedStyle(element).getPropertyValue('--reading-width').trim()), '1040px');
    await page.reload(); await composer.waitFor();
    assert.equal(await composer.evaluate(element => getComputedStyle(element).fontSize), '17px');
    await page.getByRole('button', { name: '打开设置', exact: true }).click();
    assert.equal(await page.locator('#send-shortcut').inputValue(), 'modifier-enter');
    assert.equal(await page.locator('#default-message-mode').inputValue(), 'ask');
    assert.equal(await page.getByRole('switch', { name: '自动跟随最新消息', exact: true }).isChecked(), false);
    await page.getByRole('button', { name: '数据管理', exact: true }).click();
    assert.equal(await page.getByRole('button', { name: '导出 Markdown', exact: true }).isDisabled(), true);
    await page.getByRole('button', { name: '关闭设置', exact: true }).click();
    assert.match(await page.getByLabel('选择消息意图', { exact: true }).textContent(), /只问已有资料/);
    console.log('PASS general/reading preferences apply, persist on reload and disable export without a saved conversation');

    await page.getByRole('button', { name: /离线示例A/ }).click();
    await page.getByText('人工会话A的原始问题', { exact: true }).waitFor();
    await composer.fill('快捷键验证'); await composer.press('Enter'); await composer.press('Shift+Enter');
    assert.equal(posts.length, 0);
    assert.equal(await composer.inputValue(), '快捷键验证\n\n');
    await composer.dispatchEvent('keydown', { key: 'Enter', ctrlKey: true, isComposing: true });
    assert.equal(posts.length, 0);
    await composer.press('Control+Enter');
    await page.waitForFunction(() => document.querySelector('#chat-input').value === '');
    assert.equal(posts.length, 1);
    assert.equal(posts[0].mode, 'ask');
    assert.equal(posts[0].content, '快捷键验证');
    await page.getByLabel('选择消息意图', { exact: true }).click();
    await page.getByRole('button', { name: /补充检索.*明确请求检索/ }).click();
    await page.getByRole('button', { name: '打开设置', exact: true }).click();
    await page.locator('#default-message-mode').selectOption('auto');
    await page.getByRole('button', { name: '关闭设置', exact: true }).click();
    assert.match(await page.getByLabel('选择消息意图', { exact: true }).textContent(), /补充检索/);
    console.log('PASS Enter/Shift+Enter create lines, IME does not submit, Ctrl+Enter sends the selected default mode; manual mode is preserved');

    await composer.fill('未发送的私有草稿，不应导出');
    await page.locator('button.model-status').click();
    await page.getByRole('heading', { name: 'AI服务', exact: true }).waitFor();
    assert.equal(await page.locator('.model-enable-row').count(), 0);
    assert.equal(await page.getByRole('switch', { name: '启用AI服务', exact: true }).count(), 0);
    assert.equal(await page.getByText(/云端/).count(), 0);
    await page.getByRole('button', { name: '添加供应商', exact: true }).click();
    await page.locator('#model-api-key').fill('artificial-unsaved-key-must-not-export');
    await page.getByRole('button', { name: '数据管理', exact: true }).click();
    const jsonDownloadPromise = page.waitForEvent('download');
    await page.getByRole('button', { name: '导出 JSON', exact: true }).click();
    const jsonDownload = await jsonDownloadPromise;
    const jsonContent = await fs.readFile(await jsonDownload.path(), 'utf8');
    const exported = JSON.parse(jsonContent);
    assert.equal(exported.task.id, taskA.id);
    assert.equal(exported.messages[1].citations[0].quote, quote);
    assert.equal(exported.messages[1].citations[0].location_start, 1);
    assert.equal(exported.runs[0].id, run.id);
    assert.equal(exported.usage.model_calls, usage.model_calls);
    assert.ok(!jsonContent.includes('artificial-unsaved-key-must-not-export'));
    assert.ok(!jsonContent.includes('未发送的私有草稿'));
    const markdownDownloadPromise = page.waitForEvent('download');
    await page.getByRole('button', { name: '导出 Markdown', exact: true }).click();
    const markdownDownload = await markdownDownloadPromise;
    const markdown = await fs.readFile(await markdownDownload.path(), 'utf8');
    assert.ok(markdown.includes('人工会话A的原始问题'));
    assert.ok(markdown.includes(quote)); assert.ok(markdown.includes('第 2 页'));
    assert.ok(markdown.includes(source.id)); assert.ok(markdown.includes(source.source_url));
    assert.ok(!markdown.includes('artificial-unsaved-key-must-not-export'));
    assert.ok(!markdown.includes('未发送的私有草稿'));
    assert.equal(settingsPosts.length, 0);
    await page.screenshot({ path: path.join(output, 'settings-data.png'), fullPage: true });
    await page.getByRole('button', { name: '关闭设置', exact: true }).click();
    console.log('PASS Markdown/JSON downloads contain the selected conversation and exact citation locations, with no unsaved draft or API key');

    const longContent = '用于验证阅读位置的人工消息。\n'.repeat(26);
    viewA = { ...viewA, messages: [...viewA.messages, message('scroll-1', taskA.id, 'assistant', `滚动内容一\n${longContent}`)] };
    await page.getByText(`滚动内容一\n${longContent}`, { exact: true }).waitFor();
    await page.getByRole('button', { name: '回到最新消息', exact: true }).click();
    const scroll = page.locator('.timeline-scroll');
    const before = await scroll.evaluate(element => element.scrollTop);
    viewA = { ...viewA, messages: [...viewA.messages, message('scroll-2', taskA.id, 'assistant', `滚动内容二\n${longContent}`)] };
    await page.getByText(`滚动内容二\n${longContent}`, { exact: true }).waitFor();
    assert.ok(Math.abs(await scroll.evaluate(element => element.scrollTop) - before) < 2);
    await page.getByRole('button', { name: '回到最新消息', exact: true }).waitFor();
    await page.getByRole('button', { name: '打开设置', exact: true }).click();
    await page.getByRole('switch', { name: '自动跟随最新消息', exact: true }).check();
    await page.getByRole('button', { name: '关闭设置', exact: true }).click();
    await page.getByRole('button', { name: '回到最新消息', exact: true }).click();
    viewA = { ...viewA, messages: [...viewA.messages, message('scroll-3', taskA.id, 'assistant', `滚动内容三\n${longContent}`)] };
    await page.getByText(`滚动内容三\n${longContent}`, { exact: true }).waitFor();
    assert.ok(await scroll.evaluate(element => element.scrollHeight - element.scrollTop - element.clientHeight < 3));
    await scroll.evaluate(element => { element.scrollTop = 0; });
    await page.getByRole('button', { name: '回到最新消息', exact: true }).waitFor();
    viewA = { ...viewA, messages: [...viewA.messages, message('scroll-4', taskA.id, 'assistant', `滚动内容四\n${longContent}`)] };
    await page.getByText(`滚动内容四\n${longContent}`, { exact: true }).waitFor();
    assert.ok(await scroll.evaluate(element => element.scrollTop < 2));
    console.log('PASS disabled follow keeps position, enabled follow tracks updates at bottom and preserves reading above');

    await page.getByRole('button', { name: '打开设置', exact: true }).click();
    await page.getByRole('button', { name: '数据管理', exact: true }).click();
    await page.getByRole('button', { name: '恢复默认', exact: true }).click();
    await page.getByRole('dialog', { name: '恢复默认偏好？', exact: true }).waitFor();
    await page.keyboard.press('Escape');
    assert.equal(await page.locator('html').getAttribute('data-text-size'), 'large');
    await page.getByRole('button', { name: '恢复默认', exact: true }).click();
    await page.getByRole('dialog', { name: '恢复默认偏好？', exact: true }).getByRole('button', { name: '恢复默认', exact: true }).click();
    await page.locator('html[data-text-size="standard"][data-reading-width="standard"][data-theme-preference="system"]').waitFor();
    await page.getByRole('button', { name: '通用', exact: true }).click();
    assert.equal(await page.locator('#send-shortcut').inputValue(), 'enter');
    assert.equal(await page.locator('#default-message-mode').inputValue(), 'auto');
    await page.getByRole('button', { name: '关闭设置', exact: true }).click();
    assert.equal(await composer.inputValue(), '未发送的私有草稿，不应导出');
    assert.equal(settingsPosts.length, 0);
    console.log('PASS reset requires confirmation, cancel preserves preferences and reset leaves draft/model configuration untouched');

    await page.setViewportSize({ width: 320, height: 640 });
    await page.getByRole('button', { name: '打开对话列表', exact: true }).click();
    await page.getByRole('button', { name: '打开设置', exact: true }).click();
    for (const section of ['通用', 'AI服务', '外观', '数据管理', '研究与用量']) {
      await page.getByRole('button', { name: section, exact: true }).click();
      await page.getByRole('heading', { name: section, exact: true }).waitFor();
      assert.equal(await page.locator('.settings-dialog').evaluate(element => element.scrollWidth <= element.clientWidth), true);
    }
    await page.getByRole('button', { name: '通用', exact: true }).click();
    await page.screenshot({ path: path.join(output, 'settings-general-mobile.png'), fullPage: true });
    await page.getByRole('button', { name: '数据管理', exact: true }).click();
    await page.getByRole('button', { name: '打开回收站', exact: true }).click();
    assert.equal(await page.getByRole('dialog', { name: '设置', exact: true }).count(), 0);
    await page.getByText('回收站是空的', { exact: true }).waitFor();
    assert.equal(await page.locator('.trash-dialog[open]').count(), 1);
    assert.equal(await page.locator('.sidebar.mobile-open').count(), 0);
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
    await page.keyboard.press('Escape');
    await page.addInitScript(() => {
      Object.defineProperty(window, 'localStorage', { configurable: true, get() { throw new DOMException('Artificial storage refusal', 'SecurityError'); } });
    });
    await page.reload(); await composer.waitFor();
    await page.getByRole('button', { name: '打开对话列表', exact: true }).click();
    await page.getByRole('button', { name: '打开设置', exact: true }).click();
    await page.locator('#send-shortcut').selectOption('modifier-enter');
    await page.getByText('浏览器未允许保存，此次选择仅在当前页面生效', { exact: true }).waitFor();
    assert.deepEqual(errors, []);
    console.log('PASS five settings sections at 320px, recycle-bin navigation and in-memory controls with blocked storage');

  } else if (themeOnly) {

    const rootTheme = () => page.locator('html').getAttribute('data-theme');
    assert.equal(await rootTheme(), 'dark');
    assert.equal(await page.locator('html').getAttribute('data-theme-preference'), 'system');
    assert.equal(await page.locator('.sidebar-footer, .sidebar-insight, .workspace-avatar').count(), 0);
    assert.equal(await page.getByText('个人研究空间', { exact: true }).count(), 0);
    await page.screenshot({ path: path.join(output, 'theme-dark-workspace.png'), fullPage: true });
    await page.getByRole('button', { name: '打开设置', exact: true }).click();
    await page.getByRole('button', { name: '外观', exact: true }).click();
    assert.equal(await page.getByRole('radio', { name: '跟随系统', exact: true }).isChecked(), true);
    await page.emulateMedia({ colorScheme: 'light' });
    await page.locator('html[data-theme="light"]').waitFor();
    await page.getByRole('radio', { name: '暗色', exact: true }).check();
    assert.equal(await page.evaluate(() => localStorage.getItem('paper-scout.theme')), 'dark');
    assert.equal(await rootTheme(), 'dark');
    await page.screenshot({ path: path.join(output, 'theme-dark-settings.png'), fullPage: true });
    await page.reload();
    await composer.waitFor();
    assert.equal(await rootTheme(), 'dark');
    assert.equal(await page.locator('html').getAttribute('data-theme-preference'), 'dark');
    console.log('PASS system default/dynamic changes, explicit dark override and reload persistence');
    await page.getByRole('button', { name: '打开设置', exact: true }).click();
    await page.getByRole('button', { name: '外观', exact: true }).click();
    await page.getByRole('radio', { name: '亮色', exact: true }).check();
    await page.emulateMedia({ colorScheme: 'dark' });
    assert.equal(await rootTheme(), 'light');
    await page.getByRole('button', { name: '关闭设置', exact: true }).click();
    await page.screenshot({ path: path.join(output, 'theme-light-workspace.png'), fullPage: true });
    await page.getByRole('button', { name: '打开设置', exact: true }).click();
    await page.getByRole('button', { name: '外观', exact: true }).click();
    await page.getByRole('radio', { name: '跟随系统', exact: true }).check();
    assert.equal(await page.evaluate(() => localStorage.getItem('paper-scout.theme')), null);
    assert.equal(await rootTheme(), 'dark');
    await page.getByRole('button', { name: '关闭设置', exact: true }).click();
    await page.getByRole('button', { name: /离线示例A/ }).click();
    await page.getByText('人工会话A的原始问题', { exact: true }).waitFor();
    await page.getByRole('button', { name: /引用 1/ }).click();
    await page.locator('mark').waitFor();
    assert.equal(await page.locator('.artifact-panel').evaluate(element => getComputedStyle(element).backgroundColor), 'rgb(27, 27, 27)');
    await page.screenshot({ path: path.join(output, 'theme-dark-sources.png'), fullPage: true });
    await page.getByLabel(/对话操作：离线示例A/).click();
    await page.getByRole('button', { name: '重命名', exact: true }).click();
    assert.equal(await page.locator('.action-dialog').evaluate(element => getComputedStyle(element).backgroundColor), 'rgb(34, 34, 34)');
    await page.screenshot({ path: path.join(output, 'theme-dark-dialog.png'), fullPage: true });
    await page.keyboard.press('Escape');
    await page.getByRole('button', { name: '关闭资料面板', exact: true }).click();
    console.log('PASS explicit light ignores dark system, reset follows system; source panel and native dialogs use dark surfaces');
    await page.getByRole('button', { name: '打开设置', exact: true }).click();
    await page.getByRole('button', { name: '外观', exact: true }).click();
    await page.setViewportSize({ width: 390, height: 844 });
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), true);
    await page.screenshot({ path: path.join(output, 'theme-mobile-settings.png'), fullPage: true });
    await page.getByRole('button', { name: '关闭设置', exact: true }).click();
    await page.addInitScript(() => {
      Object.defineProperty(window, 'localStorage', { configurable: true, get() { throw new DOMException('Storage unavailable in this artificial browser case', 'SecurityError'); } });
    });
    await page.reload(); await composer.waitFor();
    await page.getByRole('button', { name: '打开对话列表', exact: true }).click();
    await page.getByRole('button', { name: '打开设置', exact: true }).click();
    await page.getByRole('button', { name: '外观', exact: true }).click();
    await page.getByRole('radio', { name: '亮色', exact: true }).check();
    assert.equal(await rootTheme(), 'light');
    await page.getByText('浏览器未允许保存，此次选择仅在当前页面生效', { exact: true }).waitFor();
    assert.deepEqual(errors, []);
    console.log('PASS mobile appearance controls and usable theme switching when browser storage is blocked');

  } else if (basicsOnly) {
    await composer.fill('基础功能修复时保留的草稿');
    const intent = page.getByLabel('选择消息意图', { exact: true });
    await intent.click(); await composer.click();
    assert.equal(await page.locator('.intent-menu').getAttribute('open'), null);
    await intent.click(); await page.keyboard.press('Escape');
    assert.equal(await page.locator('.intent-menu').getAttribute('open'), null);
    assert.equal(await intent.evaluate(element => element === document.activeElement), true);
    await page.getByRole('button', { name: /离线示例A/ }).click();
    await page.getByText('人工会话A的原始问题', { exact: true }).waitFor();
    await page.locator('.usage-details > summary').click(); await composer.click();
    assert.equal(await page.locator('.usage-details').getAttribute('open'), null);
    console.log('PASS intent/usage menus dismiss outside and with Escape/focus restoration');
    await page.getByLabel(/对话操作：离线示例A/).click();
    await page.getByRole('button', { name: '重命名', exact: true }).click();
    await page.getByRole('textbox', { name: '对话名称', exact: true }).fill('重命名离线对话');
    await page.getByRole('button', { name: '保存名称', exact: true }).click();
    await page.getByRole('heading', { name: '重命名离线对话', exact: true }).waitFor();
    assert.equal(taskA.topic, '离线示例A：通信资料');
    await page.getByLabel('对话操作：重命名离线对话', { exact: true }).click();
    await page.getByRole('button', { name: '删除对话', exact: true }).click();
    await page.getByRole('button', { name: '移到回收站', exact: true }).click();
    await page.getByText('对话已移到回收站', { exact: true }).waitFor();
    assert.equal(await page.locator('.history-select').filter({ hasText: '重命名离线对话' }).count(), 0);
    await page.getByRole('button', { name: '撤销删除', exact: true }).click();
    await page.locator('.history-select').filter({ hasText: '重命名离线对话' }).waitFor();
    await page.getByLabel('对话操作：重命名离线对话', { exact: true }).click();
    await page.getByRole('button', { name: '删除对话', exact: true }).click();
    await page.getByRole('button', { name: '移到回收站', exact: true }).click();
    await page.getByText('对话已移到回收站', { exact: true }).waitFor();
    await page.getByRole('button', { name: '回收站', exact: true }).click();
    await page.getByRole('button', { name: '恢复对话：重命名离线对话', exact: true }).click();
    await page.getByText('已恢复 1 个对话；研究不会自动重启', { exact: true }).waitFor();
    await page.getByRole('button', { name: '关闭回收站', exact: true }).click();
    assert.equal(await composer.inputValue(), '基础功能修复时保留的草稿');
    console.log('PASS rename keeps research question, current chat trash/undo/recycle restore and independent draft');
    assert.equal(await composer.inputValue(), '基础功能修复时保留的草稿');
    assert.deepEqual(errors, []);
    console.log('PASS conversation management remains intact with provider-based settings');
  } else if (controlOnly) {
    await composer.fill('先明确研究问题，不要立刻开始检索');
    await page.getByRole('button', { name: '发送消息', exact: true }).click();
    await page.getByRole('button', { name: '重试发送', exact: true }).waitFor();
    await page.getByRole('button', { name: /离线示例A/ }).click();
    await page.getByText('人工会话A的原始问题', { exact: true }).waitFor();
    await page.getByRole('button', { name: '新建对话', exact: true }).click();
    assert.equal(await composer.inputValue(), '先明确研究问题，不要立刻开始检索');
    await page.getByRole('button', { name: '重试发送', exact: true }).click();
    await page.getByRole('heading', { name: taskC.topic, exact: true }).waitFor();
    assert.equal(creationPosts.length, 2);
    assert.deepEqual(creationPosts[1], creationPosts[0]);
    assert.equal(await composer.inputValue(), '');
    console.log('PASS initial creation uncertain retry survives switching and returns same acknowledged conversation');
    const stop = page.getByRole('button', { name: '停止', exact: true });
    assert.equal(await stop.isEnabled(), true, 'busy first dialogue without a Run must remain stoppable');
    await composer.fill('停止之后仍未发送的草稿');
    await stalePollStarted;
    await stop.click();
    await page.getByText('用户已停止本条对话；迟到的模型结果不会启动研究。', { exact: true }).waitFor();
    releaseStalePoll();
    assert.equal(await composer.inputValue(), '停止之后仍未发送的草稿');
    assert.equal(await page.getByRole('button', { name: '发送消息', exact: true }).isEnabled(), true);
    assert.equal(await page.getByText('等待当前回复完成再发送', { exact: true }).count(), 0);
    assert.equal(await page.getByRole('button', { name: '停止', exact: true }).count(), 0);
    await page.screenshot({ path: path.join(output, 'conversation-stopped.png'), fullPage: true });
    console.log('PASS stop during first dialogue/no Run; interrupted transcript visible, late poll blocked, draft preserved');
    await page.getByRole('button', { name: '新建对话', exact: true }).click();
    await page.setViewportSize({ width: 390, height: 844 });
    await page.getByRole('button', { name: '打开对话列表', exact: true }).waitFor({ state: 'visible' });
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), true);
    await page.screenshot({ path: path.join(output, 'conversation-mobile.png'), fullPage: true, animations: 'disabled' });
    assert.deepEqual(errors, []);
    console.log('PASS final mobile screenshot without transitional sidebar; no uncaught browser errors');
  } else {
  await composer.fill('新对话未发送草稿');
  await page.getByRole('button', { name: /离线示例A/ }).click();
  await page.getByText('人工会话A的原始问题', { exact: true }).waitFor();
  await composer.fill('A会话未发送草稿');
  await page.getByRole('button', { name: /离线示例B/ }).click();
  await page.getByText('人工会话B的原始问题', { exact: true }).waitFor();
  await composer.fill('B会话未发送草稿');
  await page.getByRole('button', { name: '新建对话', exact: true }).click();
  assert.equal(await composer.inputValue(), '新对话未发送草稿');
  await page.getByRole('button', { name: /离线示例A/ }).click();
  await page.getByText('人工会话A的原始问题', { exact: true }).waitFor();
  assert.equal(await composer.inputValue(), 'A会话未发送草稿');
  console.log('PASS independent unsent drafts across conversation switches');

  await composer.fill('执行中直接补充方向');
  const send = page.getByRole('button', { name: '发送消息', exact: true });
  assert.equal(await send.isEnabled(), true, 'running research must allow natural supplements');
  await send.click();
  const retry = page.getByRole('button', { name: '重试发送', exact: true });
  await retry.waitFor();
  await retry.click();
  await page.getByText('补充已收到（离线样例）', { exact: true }).waitFor();
  assert.equal(posts.length, 2);
  assert.deepEqual(posts[1], posts[0]);
  assert.equal(posts[0].content, '执行中直接补充方向');
  assert.equal(await composer.inputValue(), '');
  console.log('PASS supplement during running research; uncertain POST retries same request_id/payload');

  await page.getByRole('button', { name: /引用 1/ }).click();
  await page.locator('mark').waitFor();
  assert.equal(await page.locator('mark').innerText(), quote);
  assert.equal(await page.getByText(/引用范围或摘录与已保存快照不一致/).count(), 0);
  await page.screenshot({ path: path.join(output, 'conversation-desktop.png'), fullPage: true });
  console.log('PASS citation opens correct saved run/paper and Unicode-character quote highlight');

  blockB = true;
  await page.getByRole('button', { name: /离线示例B/ }).click();
  await bStarted;
  await page.getByRole('button', { name: /离线示例A/ }).click();
  releaseB();
  await page.getByText('人工会话A的原始问题', { exact: true }).waitFor();
  assert.equal(await page.getByText('人工会话B的原始问题', { exact: true }).count(), 0);
  console.log('PASS delayed previous conversation response cannot overwrite current conversation');

  await page.getByRole('button', { name: '新建对话', exact: true }).click();
  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByRole('button', { name: '打开对话列表', exact: true }).waitFor({ state: 'visible' });
  await composer.waitFor({ state: 'visible' });
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), true, 'mobile view must not overflow horizontally');
  await page.screenshot({ path: path.join(output, 'conversation-mobile.png'), fullPage: true });
  assert.deepEqual(errors, []);
  console.log('PASS mobile composer/layout; no uncaught browser JavaScript errors');
  }
} catch (error) {
  await page.screenshot({ path: path.join(output, 'conversation-failure.png'), fullPage: true });
  throw error;
} finally {
  releaseB();
  releaseStalePoll();
  releaseSettingsSave();
  releaseTrashAction();
  releaseCatalog();
  await context.close();
  await browser.close();
}
