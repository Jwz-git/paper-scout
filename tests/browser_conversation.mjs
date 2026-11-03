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
const context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, locale: 'zh-CN', timezoneId: 'Asia/Shanghai', reducedMotion: 'reduce' });
const errors = [];
const page = await context.newPage();
page.on('pageerror', error => errors.push(error.message));
await context.route('**/*', async route => {
  const url = new URL(route.request().url());
  if (url.origin !== 'http://127.0.0.1:5173') return route.abort();
  const json = value => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(value) });
  if (url.pathname === '/api/health') return json({ status: 'ok', app: 'Paper Scout', version: '0.1.0' });
  if (url.pathname === '/api/conversations') {
    if (route.request().method() !== 'POST') return json(viewC ? [taskC, taskA, taskB] : [taskA, taskB]);
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
try {
  await page.goto('http://127.0.0.1:5173/');
  const composer = page.getByRole('textbox', { name: '输入消息', exact: true });
  await composer.waitFor();
  assert.equal(await composer.inputValue(), '');
  assert.equal(await page.locator('.stage-stepper').count(), 0);
  await page.screenshot({ path: path.join(output, 'conversation-empty.png'), fullPage: true });
  console.log('PASS empty conversational workspace; no prefilled fake task/stepper');

  if (controlOnly) {
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
} finally {
  releaseB();
  releaseStalePoll();
  await context.close();
  await browser.close();
}
