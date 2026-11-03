<template>
  <main :inert="settingsOpen" class="workspace" :class="{ 'panel-visible': panelOpen, 'welcome-view': selectedKey === NEW_CHAT }">
    <button
      v-if="compactLayout && (sidebarOpen || panelOpen)"
      class="mobile-scrim"
      :aria-label="sidebarOpen ? '关闭对话列表' : '关闭资料面板'"
      tabindex="-1"
      @click="sidebarOpen ? closeSidebar() : closePanel()"
    ></button>

    <aside
      ref="sidebarElement"
      class="sidebar"
      :class="{ 'mobile-open': sidebarOpen }"
      :inert="compactLayout && (!sidebarOpen || panelOpen)"
      :role="compactLayout ? 'dialog' : undefined"
      :aria-modal="compactLayout && sidebarOpen ? true : undefined"
      aria-labelledby="sidebar-title"
    >
      <div class="sidebar-top">
        <a class="brand" href="#" @click.prevent="newConversation">
          <span class="brand-symbol"><UiIcon name="scout" class="brand-mark" /></span>
          <span id="sidebar-title">Paper Scout</span>
        </a>
        <button ref="sidebarCloseButton" class="icon-button sidebar-close" aria-label="关闭对话列表" @click="closeSidebar">
          <UiIcon name="close" />
        </button>
      </div>
      <button class="new-chat" aria-label="新建对话" @click="newConversation">
        <UiIcon name="plus" /><span>新建对话</span><UiIcon name="edit" class="new-chat-end" />
      </button>
      <label class="history-search">
        <UiIcon name="search" />
        <input v-model="historyQuery" type="search" placeholder="搜索对话" aria-label="搜索对话" />
      </label>
      <div class="sidebar-heading">
        <span>最近对话 <small>{{ tasks.length }}</small></span>
        <button class="icon-button" aria-label="刷新对话记录" :disabled="historyLoading" @click="refreshHistory">
          <UiIcon name="refresh" />
        </button>
      </div>
      <p v-if="historyError" class="error-message" role="alert">{{ historyError }}</p>
      <p v-if="historyLoading" class="muted" role="status">正在读取记录…</p>
      <nav class="history-list" aria-label="历史研究对话">
        <section v-for="group in historyGroups" :key="group.label" class="history-group">
          <h2>{{ group.label }}</h2>
          <div v-for="task in group.tasks" :key="task.id" class="history-item" :class="{ selected: selectedKey === task.id }">
            <button class="history-select" :aria-current="selectedKey === task.id ? 'true' : undefined" :title="taskTitle(task)" @click="selectConversation(task.id)"><UiIcon name="chat" /><span class="history-copy"><span class="history-title">{{ taskTitle(task) }}</span><small>{{ shortDate(task.updated_at) }}<span v-if="drafts[task.id]"> · 草稿</span><span v-if="pending[task.id]"> · 发送待确认</span></small></span></button>
            <details data-menu class="history-menu"><summary :aria-label="`对话操作：${taskTitle(task)}`"><UiIcon name="more" /></summary><div><button type="button" :disabled="conversationActionBusy || !!pending[task.id]" @click="openConversationAction('rename', task)"><UiIcon name="edit" />重命名</button><button type="button" class="danger-text" :disabled="conversationActionBusy" @click="openConversationAction('trash', task)"><UiIcon name="trash" />删除对话</button></div></details>
          </div>
        </section>
        <p v-if="historyLoaded && historyQuery.trim() && !historyGroups.length && !historyLoading" class="history-empty">没有找到相关对话，换个关键词试试。</p>
      </nav>
      <div class="sidebar-actions">
      <button ref="trashButton" class="sidebar-settings" type="button" @click="openTrash"><UiIcon name="trash" />回收站<UiIcon name="chevronRight" /></button>
      <button ref="settingsButton" class="sidebar-settings" type="button" aria-label="打开设置" @click="openSettings('general')"><UiIcon name="settings" />设置<UiIcon name="chevronRight" /></button>
      </div>
    </aside>

    <section class="chat-shell" :inert="compactLayout && (sidebarOpen || panelOpen)" aria-label="研究对话">
      <header class="chat-header">
        <div class="header-title">
          <button ref="sidebarToggleButton" class="icon-button menu-toggle" aria-label="打开对话列表" :aria-expanded="sidebarOpen" @click="openSidebar">
            <UiIcon name="menu" />
          </button>
          <div>
            <h1 :title="conversation ? taskTitle(conversation.task) : undefined">{{ (conversation ? taskTitle(conversation.task) : '') || (selectedKey === NEW_CHAT ? 'Paper Scout' : '正在读取对话…') }}</h1>
          </div>
        </div>
        <div class="header-actions">
          <button
            v-if="conversation?.runs.length"
            ref="artifactToggleButton"
            class="artifact-toggle"
            aria-label="查看资料与报告"
            :aria-expanded="panelOpen"
            :disabled="!conversation?.runs.length"
            :title="conversation?.runs.length ? '查看本会话保存的资料与报告' : '发起研究后可查看文献与阶段性报告'"
            @click="togglePanel"
          >
            <UiIcon name="documents" />
            <span>资料与报告</span>
            <small v-if="conversation?.runs.length">{{ conversation.runs.length }}</small>
          </button>
        </div>
      </header>

      <div class="chat-body">

        <div ref="timelineElement" class="timeline-scroll" @scroll="trackScroll">
          <div class="timeline-content">
            <section v-if="selectedKey === NEW_CHAT" class="empty-state">
              <div class="welcome-emblem" aria-hidden="true"><UiIcon name="scout" /></div>
              <h2>今天，想研究什么？</h2>
              <p class="empty-description">描述一个问题，或从一个想法开始。</p>
            </section>

            <p v-if="conversationLoading" class="muted" role="status">正在读取对话…</p>
            <div v-if="conversationError" class="error-message" role="alert">
              {{ conversationError }} 已有记录保留，可能不是最新。
              <button class="text-button" :disabled="currentPending?.busy" @click="retryConversation">重新读取对话</button>
            </div>
            <template v-if="conversation">
              <section v-if="legacyRuns.length || !conversation.messages.length" class="legacy-input">
                <p class="record-label">历史任务输入 · 原始记录</p>
                <p>{{ conversation.task.topic }}</p>
                <small v-if="conversation.task.start_year || conversation.task.end_year">年份范围：{{ conversation.task.start_year ?? '不限' }} — {{ conversation.task.end_year ?? '不限' }}</small>
                <small v-if="conversation.task.focus_dimensions.length">关注：{{ conversation.task.focus_dimensions.join('、') }}</small>
              </section>
              <template v-for="entry in timeline" :key="entry.id">
                <section v-if="entry.kind === 'run'" class="legacy-run">
                  <div><strong><UiIcon name="documents" />既有调研记录</strong><time>{{ formatTime(entry.run.created_at) }}</time></div>
                  <p>{{ entry.run.initial_topic }} · {{ runLabels[entry.run.status] }}</p>
                  <p v-if="entry.run.stop_reason" class="muted">{{ entry.run.stop_reason }}</p>
                  <button class="text-button" @click="openRun(entry.run.id)">查看这次运行的资料与报告<UiIcon name="arrowRight" /></button>
                </section>
                <article v-else class="message" :class="[entry.message.role, entry.message.status]" :aria-label="entry.message.role === 'user' ? '用户消息' : '助手消息'">
                  <div class="message-avatar" aria-hidden="true"><span v-if="entry.message.role === 'user'">你</span><UiIcon v-else name="scout" /></div>
                  <div class="message-body">
                    <div class="message-heading">
                      <strong>{{ entry.message.role === 'user' ? '你' : 'Paper Scout' }}</strong>
                      <time>{{ formatTime(entry.message.created_at) }}</time>
                      <span v-if="entry.message.status !== 'completed'" class="message-status" :class="entry.message.status">{{ messageLabels[entry.message.status] }}</span>
                    </div>
                    <p v-if="entry.message.content" class="message-text">{{ entry.message.content }}</p>
                    <p v-else class="muted processing-placeholder"><span v-if="['queued', 'processing'].includes(entry.message.status)" class="processing-dots" aria-hidden="true"><i></i><i></i><i></i></span>{{ messageLabels[entry.message.status] }}{{ entry.message.status === 'processing' ? '，完成后显示实际回复。' : '' }}</p>
                    <p v-if="entry.message.error_category" class="error-message" role="alert">错误类别：{{ entry.message.error_category }}</p>
                    <div v-if="entry.message.citations.length" class="citation-buttons" aria-label="回答引用">
                      <button v-for="(citation, index) in entry.message.citations" :key="`${citation.source_text_id}-${index}`" :aria-label="`引用 ${index + 1}：${sourceLabels[citation.source_type]}${citation.page_number != null ? `，PDF 第 ${citation.page_number} 页` : ''}`" :title="citation.quote" @click="openCitation(citation)">
                        <span>[{{ index + 1 }}]</span>{{ sourceLabels[citation.source_type] }}{{ citation.page_number != null ? ` · p${citation.page_number}` : '' }}<UiIcon name="arrowUpRight" />
                      </button>
                    </div>
                    <button v-if="entry.message.role === 'assistant' && entry.message.content && entry.message.status === 'completed'" class="message-copy text-button" type="button" @click="copyMessage(entry.message.content)"><UiIcon name="copy" />复制回复</button>
                    <button v-if="entry.message.run_id" class="message-artifact text-button" @click="openRun(entry.message.run_id!)"><UiIcon name="documents" />查看相关调研资料</button>
                  </div>
                </article>
              </template>
              <p v-if="!conversation.messages.length && !conversation.runs.length" class="muted">这条记录还没有对话或调研。可以在下方直接继续。</p>
              <details v-if="latestRun" class="process-records" :open="processOpen" @toggle="onProcessToggle">
                <summary><span class="process-label"><UiIcon name="process" />过程记录</span><span class="process-summary">{{ processOpen ? '收起' : '按需查看实际执行记录' }} · {{ latestRun.current_round }}/{{ latestRun.max_rounds }} 轮<UiIcon name="chevronDown" /></span></summary>
                <div class="process-content">
                  <p class="muted">这是后端执行记录，不是模型的思维过程。{{ runLabels[latestRun.status] }} · {{ stageLabels[latestRun.stage] }}</p>
                  <p v-if="processLoading" class="muted" role="status">正在读取过程记录…</p>
                  <p v-if="processError" class="error-message" role="alert">{{ processError }} <button class="text-button" @click="loadProcess">重试</button></p>
                  <ol v-if="processEvents.length" class="event-list">
                    <li v-for="event in processEvents" :key="event.id"><time>{{ formatTime(event.created_at) }}</time><span>{{ stageLabels[event.stage] }} · {{ event.category }}</span><p>{{ event.message }}</p></li>
                  </ol>
                  <p v-else-if="!processLoading && !processError" class="muted">暂无已保存的执行记录。</p>
                  <ul v-if="latestRun.gaps.length" class="gap-list"><li v-for="gap in latestRun.gaps" :key="gap">{{ gap }}</li></ul>
                </div>
              </details>
            </template>
          </div>
        </div>
        <footer class="composer-dock">
          <button v-if="!nearBottom && conversation" class="jump-bottom" @click="scrollToBottom"><UiIcon name="arrowDown" />回到最新消息</button>
          <p v-if="modelConfigured === false" class="model-note"><UiIcon name="info" /><span>{{ availableProviders.length ? '尚未选择模型，请在输入区选择要使用的型号。' : '请先配置AI服务，再选择对话使用的模型。' }}</span><button type="button" class="text-button" @click="availableProviders.length ? openModelPicker() : openSettings('model')">{{ availableProviders.length ? '选择模型' : '配置AI服务' }}</button></p>
          <div v-if="conversation" class="execution-strip" aria-label="执行状态与用量">
            <div class="execution-description">
              <i :class="{ running: isResearchRunning }" aria-hidden="true"></i>
              <strong>{{ conversation.busy ? '对话处理中' : latestRun ? runLabels[latestRun.status] : '可以继续对话' }}</strong>
              <span v-if="latestRun && isResearchRunning">{{ stageLabels[latestRun.stage] }}</span>
              <span>{{ conversation.usage.model_calls }} 次模型调用 · {{ Math.round(conversation.usage.total_execution_seconds) }} 秒</span>
            </div>
            <div class="execution-actions">
              <details data-menu class="usage-details">
                <summary>用量<UiIcon name="chevronDown" /></summary>
                <div>
                  <h3>本次会话用量</h3>
                  <p>累计模型调用：{{ conversation.usage.model_calls }}</p>
                  <p>累计执行：{{ conversation.usage.total_execution_seconds.toFixed(1) }} 秒</p>
                  <p>Token：{{ tokenText(conversation.usage.token_usage.total_tokens) }}</p>
                  <p>输入 / 输出：{{ tokenText(conversation.usage.token_usage.prompt_tokens) }} / {{ tokenText(conversation.usage.token_usage.completion_tokens) }}</p>
                  <template v-if="latestRun">
                    <p>当前运行外部调用：{{ latestRun.total_calls }} / {{ latestRun.max_calls }}</p>
                    <p>当前运行执行上限：{{ latestRun.max_seconds }} 秒</p>
                    <p>当前轮次：{{ latestRun.current_round }} / {{ latestRun.max_rounds }}</p>
                  </template>
                  <p class="muted">未知 token 不记为零；暂停等待不计执行时间。</p>
                </div>
              </details>
              <button v-if="canPause" :disabled="controlsDisabled" @click="sendControl('pause')">暂停</button>
              <button v-if="canResume" :disabled="controlsDisabled" @click="sendControl('resume')">继续</button>
              <button v-if="activeRun || conversation.busy" class="stop-button" :disabled="!!currentPending || stopBusy" @click="stopWork">{{ stopBusy ? '正在停止…' : '停止' }}</button>
            </div>
          </div>
          <p v-if="latestRun?.stop_reason && !isResearchRunning" class="stop-note">{{ latestRun.stop_reason }}</p>
          <div v-if="currentPending" class="pending-notice" role="status">
            <div><strong>{{ currentPending.busy ? '正在发送…' : '发送未确认' }}</strong><p>{{ currentPending.error || '消息确认前保留草稿，不会重复提交。' }}</p><blockquote v-if="!currentPending.busy">{{ currentPending.content }}</blockquote></div>
            <button v-if="!currentPending.busy" class="text-button" aria-label="重试发送" @click="retrySend">重试原消息</button>
          </div>
          <p v-if="sendErrors[selectedKey]" class="error-message" role="alert">{{ sendErrors[selectedKey] }}</p>
          <div v-if="notice" class="workspace-notice" :class="{ 'notice-error': noticeError }" :role="noticeError ? 'alert' : 'status'"><span>{{ notice }}</span><button v-if="undoTask" type="button" class="text-button" :disabled="conversationActionBusy" @click="restoreTask(undoTask.id)">撤销删除</button><button type="button" class="icon-button" aria-label="关闭提示" @click="notice = ''; undoTask = null"><UiIcon name="close" /></button></div>
          <form class="composer" @submit.prevent="sendDraft">
            <label class="sr-only" for="chat-input">输入消息</label>
            <textarea id="chat-input" ref="inputElement" v-model="draft" :maxlength="inputLimit" rows="2" :placeholder="selectedKey === NEW_CHAT ? '你想研究什么？试着描述一个问题…' : '继续追问、补充方向，或聊聊已有资料…'" :title="preferences.sendShortcut === 'enter' ? 'Enter 发送，Shift + Enter 换行' : 'Ctrl / ⌘ + Enter 发送，Enter 换行'" aria-label="输入消息" @keydown="handleInputKey"></textarea>
            <div class="composer-bottom">
              <div class="composer-options">
                <details ref="intentMenu" data-menu class="intent-menu">
                  <summary aria-label="选择消息意图"><UiIcon :name="currentMode === 'research' ? 'search' : currentMode === 'ask' ? 'book' : 'chat'" />{{ modeLabels[currentMode] }}<UiIcon name="chevronDown" /></summary>
                  <div class="intent-options">
                    <button v-for="mode in intentModes" :key="mode" type="button" :class="{ selected: currentMode === mode }" :aria-pressed="currentMode === mode" @click="chooseMode(mode)"><span>{{ modeLabels[mode] }}</span><small>{{ modeDescriptions[mode] }}</small></button>
                  </div>
                </details>
                <details ref="modelMenu" data-menu class="model-menu" @toggle="onModelMenuToggle">
                  <summary aria-label="选择当前模型"><UiIcon name="model" /><span>{{ modelSettings?.enabled ? `${currentProvider?.name || ''} · ${modelSettings.model}` : '选择模型' }}</span><UiIcon name="chevronDown" /></summary>
                  <div class="model-menu-options"><p>选择用于后续对话的模型</p><div v-for="provider in availableProviders" :key="provider.id" class="model-menu-provider"><p>{{ provider.name }}</p><button v-for="model in provider.models" :key="model" type="button" :disabled="modelChangeBusy || settingsBusy || !!modelSettings?.busy" :aria-label="`${provider.name} · ${model}`" :aria-pressed="modelSettings?.enabled && provider.id === modelSettings.active_provider_id && model === modelSettings.active_model" @click="chooseModel(provider.id, model)"><span><strong>{{ model }}</strong></span><UiIcon v-if="modelSettings?.enabled && provider.id === modelSettings.active_provider_id && model === modelSettings.active_model" name="check" /></button></div><p v-if="modelSettings?.busy">执行中的工作结束或暂停后可切换。</p><button type="button" class="manage-models" @click="closeMenus(); openSettings('model')"><UiIcon name="settings" />管理AI服务</button></div>
                </details>
                <span class="input-hint">{{ conversation?.busy ? '等待当前回复完成再发送' : isResearchRunning ? '可直接补充，系统会保存检查点' : 'Enter 发送 · Shift + Enter 换行' }}</span>
              </div>
              <div class="send-group"><span v-if="draft.length" class="char-count">{{ draft.length }}/{{ inputLimit }}</span><button type="submit" class="send-button" aria-label="发送消息" :disabled="!canSend"><UiIcon name="arrowUp" /></button></div>
            </div>
          </form>
          <div class="composer-footnote">
            <span><UiIcon name="shield" />回答与引用请结合原文核查</span>
            <button type="button" class="model-status" title="AI服务与模型选择" @click="availableProviders.length && !modelConfigured ? openModelPicker() : openSettings('model')">{{ modelConfigured === true ? '模型已配置' : modelConfigured === false ? availableProviders.length ? '请选择模型' : '配置AI服务' : healthError ? '连接状态未知 · 设置' : 'AI服务' }}</button>
          </div>
        </footer>
        <section v-if="selectedKey === NEW_CHAT" class="starter-section" aria-labelledby="examples-title">
          <div class="starter-heading"><h3 id="examples-title">试试这些方向</h3><span>点击填入草稿</span></div>
          <div class="example-prompts">
            <button v-for="example in examples" :key="example.title" :disabled="!!currentPending" @click="useExample(example.text)"><UiIcon :name="example.icon" /><span>{{ example.title }}</span><UiIcon name="arrowUpRight" /></button>
          </div>
        </section>
      </div>
    </section>

    <aside
      v-if="panelOpen"
      ref="panelElement"
      class="artifact-panel"
      :role="compactLayout ? 'dialog' : undefined"
      :aria-modal="compactLayout ? true : undefined"
      aria-labelledby="materials-title"
    >
      <header class="panel-header">
        <div><p class="panel-eyebrow">RESEARCH NOTEBOOK</p><h2 id="materials-title"><UiIcon name="documents" />资料与报告</h2><p>让每一条线索，都有据可查</p></div>
        <button ref="panelCloseButton" class="icon-button" aria-label="关闭资料面板" @click="closePanel"><UiIcon name="close" /></button>
      </header>
      <div class="panel-content">
        <details ref="runMenu" data-menu class="run-picker">
          <summary>{{ selectedRun ? `调研 ${runNumber(selectedRun.id)} · ${runLabels[selectedRun.status]}` : '选择一次调研' }}<UiIcon name="chevronDown" /></summary>
          <div><button v-for="run in sortedRuns" :key="run.id" :class="{ selected: selectedRunId === run.id }" :aria-pressed="selectedRunId === run.id" @click="chooseRun(run.id)"><strong>调研 {{ runNumber(run.id) }} · {{ runLabels[run.status] }}</strong><small>{{ formatTime(run.created_at) }} · {{ run.initial_topic }}</small></button></div>
        </details>
        <p v-if="selectedRun" class="panel-note">{{ selectedRun.initial_input?.topic || selectedRun.initial_topic }}</p>
        <div class="panel-tabs" aria-label="资料类型">
          <button :class="{ active: panelTab === 'papers' }" :aria-pressed="panelTab === 'papers'" @click="panelTab = 'papers'"><UiIcon name="book" />文献<span v-if="artifact?.loaded">{{ artifact.papers.length }}</span></button>
          <button :class="{ active: panelTab === 'report' }" :aria-pressed="panelTab === 'report'" @click="panelTab = 'report'; clearPaper()"><UiIcon name="documents" />Markdown 报告</button>
        </div>
        <div v-if="artifactError" class="error-message" role="alert">{{ artifactError }}<button class="text-button" @click="loadArtifacts">重新获取资料</button></div>
        <p v-if="artifactLoading" class="muted" role="status">正在读取本次资料…</p>
        <template v-if="panelTab === 'papers'">
          <template v-if="paperSelection">
            <p v-if="paperLoading" class="muted" role="status">正在读取论文与来源快照…</p>
            <div v-if="paperError" class="error-message" role="alert">{{ paperError }}<button class="text-button" @click="loadPaper">重试论文详情</button><button class="text-button" @click="clearPaper">返回列表</button></div>
            <PaperDetailView v-if="paperDetail" :detail="paperDetail" :run-id="paperSelection.runId" :citation="selectedCitation" @back="clearPaper" @citation="selectedCitation = $event" />
          </template>
          <template v-else>
            <p class="panel-note">本次检索保存的论文。元数据、摘要与实际全文读取范围在详情中分开标记。</p>
            <button v-for="(paper, index) in artifact?.papers || []" :key="paper.id" class="paper-row" @click="openPaper(paper.id)">
              <span class="paper-number">{{ String(index + 1).padStart(2, '0') }}</span>
              <span class="paper-copy"><span class="paper-title">{{ paper.title }}</span><small>{{ paper.year ?? '年份缺失' }} · {{ paper.authors.slice(0, 2).join('、') || '作者缺失' }}{{ paper.authors.length > 2 ? ' 等' : '' }}</small><span class="paper-link">查看来源与读取状态</span></span>
              <UiIcon name="arrowUpRight" />
            </button>
            <p v-if="artifact?.loaded && !artifact.papers.length" class="muted">本次成功读取的检索结果中暂无已选论文。</p>
          </template>
        </template>
        <template v-else>
          <template v-if="artifact?.report">
            <div class="report-heading"><h3>阶段性报告</h3><button :disabled="downloadBusy" class="download-button" @click="downloadReport">{{ downloadBusy ? '下载中…' : '下载 .md' }}<UiIcon name="arrowDown" /></button></div>
            <p class="report-title">{{ artifact.report.title }}</p>
            <p v-if="downloadError" class="error-message" role="alert">{{ downloadError }}</p>
            <p class="panel-note">Markdown 原文预览，未渲染 HTML。阶段性报告不代表自主分析已经完成。</p>
            <ul v-if="artifact.report.gaps.length" class="gap-list"><li v-for="gap in artifact.report.gaps" :key="gap">{{ gap }}</li></ul>
            <p v-if="artifact.report.stop_reason" class="muted">停止说明：{{ artifact.report.stop_reason }}</p>
            <pre class="markdown-preview">{{ artifact.report.content_markdown }}</pre>
          </template>
          <p v-else-if="artifact?.loaded" class="muted">{{ artifact.reportNotice }}</p>
        </template>
      </div>
    </aside>
  </main>
  <SettingsDialog :open="settingsOpen" :initial-tab="settingsInitialTab" :conversation="conversation" @close="closeSettings" @open-trash="openTrashFromSettings" @saved="applyModelSettings" @busy="settingsBusy = $event" @notice="setNotice" />
  <TrashDialog :open="trashOpen" @close="closeTrash" @restored="applyRestoredTasks" @deleted="applyDeletedTasks" @notice="setNotice" />
  <ActionDialog v-if="conversationAction" :title="conversationAction.kind === 'rename' ? '重命名对话' : '删除这个对话？'" :description="conversationAction.kind === 'rename' ? '只修改会话名称，研究问题和历史资料保持不变。' : '对话将移到回收站，可随时恢复；正在执行的对话和调研会停止。'" :confirm-label="conversationAction.kind === 'rename' ? '保存名称' : '移到回收站'" :editable="conversationAction.kind === 'rename'" :initial-value="taskTitle(conversationAction.task).slice(0, 120)" :danger="conversationAction.kind === 'trash'" :busy="conversationActionBusy" :error="conversationActionError" @close="conversationAction = null" @confirm="confirmConversationAction" />
</template>
<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, reactive, ref, watch } from 'vue';
import UiIcon from './components/UiIcon.vue';
import PaperDetailView from './components/PaperDetail.vue';
import SettingsDialog from './components/SettingsDialog.vue';
import ActionDialog from './components/ActionDialog.vue';
import TrashDialog from './components/TrashDialog.vue';
import { useDismissableMenus, closeMenus } from './composables/useDismissableMenus';
import { usePreferences } from './composables/usePreferences';
import { runLabels, stageLabels } from './runLabels';
import type { ModelSettings } from './api/client';
import { ApiError, getModelSettings, selectProviderModel, renameConversation, trashConversation, restoreConversation, getConversations, getConversation, sendConversationMessage, stopConversation, getPapers, getRunEvents, getReport, getPaperDetail, getMarkdownReport, type Task, type ConversationView, type ChatMode, type ChatMessage, type ChatCitation, type Run, type RunStatus, type ChatStatus, type SourceType, type Paper, type Report, type RunEvent, type PaperDetail } from './api/client.ts';

const NEW_CHAT = '__new__';
useDismissableMenus();
const { preferences } = usePreferences();
const settingsBusy = ref(false);
const modelSettings = ref<ModelSettings | null>(null);
let modelReadVersion = 0;
const currentProvider = computed(() => modelSettings.value?.providers.find(provider => provider.id === modelSettings.value?.active_provider_id));
const availableProviders = computed(() => modelSettings.value?.providers.filter(provider => provider.models.length) || []);
const modelChangeBusy = ref(false);
const modelMenu = ref<HTMLDetailsElement | null>(null);
const notice = ref('');
const noticeError = ref(false);
const undoTask = ref<Task | null>(null);
function setNotice(message: string, error = false, undo: Task | null = null) { notice.value = message; noticeError.value = error; undoTask.value = undo; }

const settingsOpen = ref(false);
const settingsInitialTab = ref<'general' | 'model'>('general');
function openSettings(tab: 'general' | 'model') { settingsInitialTab.value = tab; settingsOpen.value = true; }
const settingsButton = ref<HTMLButtonElement | null>(null);
let settingsReturnFocus: HTMLElement | null = null;
watch(settingsOpen, open => { if (open) settingsReturnFocus = document.activeElement as HTMLElement; });
function closeSettings() {
  settingsOpen.value = false;
  void nextTick(() => { const target = settingsReturnFocus?.getClientRects().length ? settingsReturnFocus : inputElement.value; target?.focus(); });
}
function applyModelSettings(value: ModelSettings) {
  modelReadVersion++;
  modelSettings.value = value;
  healthConfigured.value = value.enabled;
  healthError.value = '';
  for (const view of Object.values(views)) view.model_configured = value.enabled;
}

const selectedKey = ref(NEW_CHAT);
const tasks = ref<Task[]>([]);
const historyQuery = ref('');
const trashOpen = ref(false);
const trashButton = ref<HTMLButtonElement | null>(null);
const trashedIds = new Set<string>();
const conversationAction = ref<{ kind: 'rename' | 'trash'; task: Task } | null>(null);
const conversationActionBusy = ref(false);
const conversationActionError = ref('');
const taskTitle = (task: Task) => task.title || task.topic;
const historyGroups = computed(() => {
  const query = historyQuery.value.trim().toLocaleLowerCase();
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const week = new Date(today);
  week.setDate(week.getDate() - 6);
  const groups = [
    { label: '今天', tasks: [] as Task[] },
    { label: '过去 7 天', tasks: [] as Task[] },
    { label: '更早', tasks: [] as Task[] },
  ];
  for (const task of tasks.value) {
    if (query && !`${taskTitle(task)} ${task.topic}`.toLocaleLowerCase().includes(query)) continue;
    const updated = new Date(task.updated_at);
    groups[updated >= today ? 0 : updated >= week ? 1 : 2].tasks.push(task);
  }
  return groups.filter(group => group.tasks.length);
});
const views = reactive<Record<string, ConversationView>>({});
const drafts = reactive<Record<string, string>>({ [NEW_CHAT]: '' });
const modes = reactive<Record<string, ChatMode>>({});
interface PendingSend { request_id: string; content: string; mode: ChatMode; snapshot: string; fromDraft: boolean; busy: boolean; error: string; }
const pending = reactive<Record<string, PendingSend | undefined>>({});
const sendErrors = reactive<Record<string, string>>({});
const selectedRuns = reactive<Record<string, string>>({});
const conversation = computed(() => views[selectedKey.value]);
const draft = computed({ get: () => drafts[selectedKey.value] || '', set: value => { drafts[selectedKey.value] = value; } });
const currentMode = computed(() => modes[selectedKey.value] || preferences.defaultMode);
const currentPending = computed(() => pending[selectedKey.value]);
const inputLimit = computed(() => selectedKey.value === NEW_CHAT ? 2000 : 4000);
const stopBusy = ref(false);
const canSend = computed(() => !(availableProviders.value.length && modelConfigured.value === false) && !!draft.value.trim() && !stopBusy.value && !currentPending.value && !conversation.value?.busy && !conversationLoading.value && (selectedKey.value === NEW_CHAT || !!conversation.value));
const terminal = new Set<RunStatus>(['completed', 'partial', 'failed', 'cancelled', 'interrupted']);
const running = new Set<RunStatus>(['queued', 'running', 'pause_requested']);
const sortedRuns = computed(() => [...(conversation.value?.runs || [])].sort((a, b) => b.created_at.localeCompare(a.created_at)));
const latestRun = computed(() => sortedRuns.value[0]);
const activeRun = computed(() => sortedRuns.value.find(run => !terminal.has(run.status)));
const isResearchRunning = computed(() => !!activeRun.value && running.has(activeRun.value.status));
const canPause = computed(() => !!activeRun.value && ['queued', 'running'].includes(activeRun.value.status));
const canResume = computed(() => !!activeRun.value && ['paused', 'needs_input'].includes(activeRun.value.status));
const controlsDisabled = computed(() => stopBusy.value || !!currentPending.value || !!conversation.value?.busy);
const selectedRunId = computed(() => selectedRuns[selectedKey.value] || latestRun.value?.id || '');
const selectedRun = computed(() => conversation.value?.runs.find(run => run.id === selectedRunId.value));
const legacyRuns = computed(() => (conversation.value?.runs || []).filter(run => !conversation.value?.messages.some(message => message.run_id === run.id)));
type TimelineEntry = { kind: 'message'; id: string; created_at: string; message: ChatMessage } | { kind: 'run'; id: string; created_at: string; run: Run };
const timeline = computed<TimelineEntry[]>(() => [...(conversation.value?.messages || []).map(message => ({ kind: 'message' as const, id: message.id, created_at: message.created_at, message })), ...legacyRuns.value.map(run => ({ kind: 'run' as const, id: run.id, created_at: run.created_at, run }))].sort((a, b) => a.created_at.localeCompare(b.created_at)));
const messageLabels: Record<ChatStatus, string> = { queued: '等待处理', processing: '正在处理', completed: '已完成', failed: '回复失败', interrupted: '回复已中断' };
const sourceLabels: Record<SourceType, string> = { metadata: '元数据', abstract: '摘要', fulltext: '全文' };
const modeLabels: Record<ChatMode, string> = { auto: '自动理解', research: '补充检索', ask: '只问已有资料', pause: '暂停', resume: '继续', cancel: '停止' };
const modeDescriptions: Record<string, string> = { auto: '根据对话理解问题、澄清或调研', research: '明确请求检索；终态后开启新运行并保留历史', ask: '根据已保存来源回答，不发起新检索' };
const intentModes: ChatMode[] = ['auto', 'research', 'ask'];
const examples = [
  { title: '多智能体协作', icon: 'network' as const, text: '帮我梳理多智能体通信的研究方向，先看看有哪些值得关注的问题。' },
  { title: '小样本 RAG', icon: 'search' as const, text: '我想研究小样本条件下的检索增强生成，关注评估方法和局限。' },
  { title: '长上下文与 RAG', icon: 'book' as const, text: '我对长上下文与 RAG 的关系还不太清楚，可以先帮我明确问题吗？' },
];
const compactQuery = window.matchMedia('(max-width: 1100px)');
const compactLayout = ref(compactQuery.matches);
const sidebarOpen = ref(false);
const panelOpen = ref(false);
const sidebarElement = ref<HTMLElement | null>(null);
const panelElement = ref<HTMLElement | null>(null);
const sidebarToggleButton = ref<HTMLButtonElement | null>(null);
const sidebarCloseButton = ref<HTMLButtonElement | null>(null);
const panelCloseButton = ref<HTMLButtonElement | null>(null);
const artifactToggleButton = ref<HTMLButtonElement | null>(null);
let panelReturnFocus: HTMLElement | null = null;
const panelTab = ref<'papers' | 'report'>('papers');
const timelineElement = ref<HTMLElement | null>(null);
const inputElement = ref<HTMLTextAreaElement | null>(null);
const intentMenu = ref<HTMLDetailsElement | null>(null);
const runMenu = ref<HTMLDetailsElement | null>(null);
const nearBottom = ref(true);
const historyLoading = ref(false);
const historyLoaded = ref(false);
const historyError = ref('');
const conversationLoading = ref(false);
const conversationError = ref('');
const healthConfigured = ref<boolean | null>(null);
const healthError = ref('');
const modelConfigured = computed(() => conversation.value?.model_configured ?? healthConfigured.value);
interface ArtifactData { papers: Paper[]; report: Report | null; reportNotice: string; loaded: boolean; }
const artifacts = reactive<Record<string, ArtifactData>>({});
const artifact = computed(() => artifacts[selectedRunId.value]);
const artifactLoading = ref(false);
const artifactError = ref('');
const paperSelection = ref<{ runId: string; paperId: string } | null>(null);
const paperDetail = ref<PaperDetail | null>(null);
const selectedCitation = ref<ChatCitation | null>(null);
const paperLoading = ref(false);
const paperError = ref('');
const processOpen = ref(false);
const processEvents = ref<RunEvent[]>([]);
let processRunId = '';
const processLoading = ref(false);
const processError = ref('');
const downloadBusy = ref(false);
const downloadError = ref('');
let disposed = false;
let viewVersion = 0;
let pollVersion = 0;
let artifactVersion = 0;
let paperVersion = 0;
let processVersion = 0;
let historyVersion = 0;
let historyWriteVersion = 0;
const writeVersions: Record<string, number> = {};
let pollTimer: ReturnType<typeof setTimeout> | null = null;
let pollController: AbortController | null = null;
let artifactController: AbortController | null = null;
let paperController: AbortController | null = null;
let processController: AbortController | null = null;
let historyController: AbortController | null = null;
let sendController: AbortController | null = null;
let stopController: AbortController | null = null;
let downloadController: AbortController | null = null;
const pageController = new AbortController();
const errorText = (error: unknown) => error instanceof Error ? error.message : '未知错误，请查看服务端记录';
const formatTime = (value: string) => new Date(value).toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
const shortDate = (value: string) => new Date(value).toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
const tokenText = (value: number | null) => value == null ? '未知' : value.toLocaleString();
watch(panelOpen, open => {
  if (open) panelReturnFocus = document.activeElement as HTMLElement;
});
watch([sidebarOpen, panelOpen, compactLayout], async () => {
  if (!compactLayout.value || (!sidebarOpen.value && !panelOpen.value)) return;
  await nextTick();
  (sidebarOpen.value ? sidebarCloseButton.value : panelCloseButton.value)?.focus();
});
function resizeInput() {
  const input = inputElement.value;
  if (!input) return;
  input.style.height = 'auto';
  input.style.height = `${Math.min(input.scrollHeight, 192)}px`;
}
watch(draft, () => { void nextTick(resizeInput); });
watch(() => preferences.textSize, () => { void nextTick(resizeInput); });
function openSidebar() { sidebarOpen.value = true; }
function closeSidebar() {
  sidebarOpen.value = false;
  void nextTick(() => sidebarToggleButton.value?.focus());
}
function onLayoutChange(event: MediaQueryListEvent) {
  compactLayout.value = event.matches;
  if (!event.matches) sidebarOpen.value = false;
}
function handleOverlayKey(event: KeyboardEvent) {
  if (settingsOpen.value || trashOpen.value || conversationAction.value) return;
  if (event.key === 'Escape') {
    if (sidebarOpen.value) closeSidebar();
    else {
      const menu = panelOpen.value && panelElement.value?.contains(document.activeElement) ? runMenu.value : intentMenu.value;
      if (menu?.open) {
        menu.open = false;
        menu.querySelector<HTMLElement>('summary')?.focus();
      } else if (panelOpen.value) closePanel();
      else return;
    }
    event.preventDefault();
    return;
  }
  // 只有窄屏模态区域隔离 Tab；桌面资料栏仍与对话按自然顺序工作。
  if (event.key !== 'Tab' || !compactLayout.value) return;
  const region = sidebarOpen.value ? sidebarElement.value : panelOpen.value ? panelElement.value : null;
  if (!region) return;
  const controls = [...region.querySelectorAll<HTMLElement>('button:not([disabled]), a[href], input, textarea, summary, [tabindex="0"]')]
    .filter(element => element.getClientRects().length > 0);
  const first = controls[0];
  const last = controls[controls.length - 1];
  if (event.shiftKey && document.activeElement === first) {
    event.preventDefault();
    last.focus();
  } else if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault();
    first.focus();
  }
}
function runNumber(id: string) { return [...sortedRuns.value].reverse().findIndex(run => run.id === id) + 1; }
function trackScroll() { const element = timelineElement.value; if (element) nearBottom.value = element.scrollHeight - element.scrollTop - element.clientHeight < 110; }
function scrollToBottom() { const element = timelineElement.value; if (element) { element.scrollTop = element.scrollHeight; nearBottom.value = true; } }
async function scrollIfNeeded(shouldScroll: boolean) {
  const version = viewVersion; const key = selectedKey.value; await nextTick();
  if (version !== viewVersion || key !== selectedKey.value) return;
  if (preferences.autoScroll && shouldScroll && nearBottom.value) scrollToBottom();
  else trackScroll();
}
function chooseMode(mode: ChatMode) { modes[selectedKey.value] = mode; if (intentMenu.value) intentMenu.value.open = false; }
function useExample(text: string) { if (!currentPending.value) draft.value = text; inputElement.value?.focus(); }
function handleInputKey(event: KeyboardEvent) {
  if (event.key !== 'Enter' || event.shiftKey || event.isComposing) return;
  const modified = event.ctrlKey || event.metaKey;
  if (event.altKey || (preferences.sendShortcut === 'modifier-enter' && !modified)) return;
  event.preventDefault(); void sendDraft();
}
function upsertTask(task: Task) { if (trashedIds.has(task.id)) return; const index = tasks.value.findIndex(item => item.id === task.id); if (index >= 0) tasks.value.splice(index, 1); tasks.value.unshift(task); historyWriteVersion++; }
function applyConversation(data: ConversationView, shouldScroll: boolean) { if (trashedIds.has(data.task.id)) return; views[data.task.id] = data; upsertTask(data.task); if (selectedKey.value === data.task.id) void scrollIfNeeded(shouldScroll); }
function stopPolling() { pollVersion++; if (pollTimer !== null) clearTimeout(pollTimer); pollTimer = null; pollController?.abort(); pollController = null; }
function abortMaterials() { artifactVersion++; artifactController?.abort(); artifactLoading.value = false; processVersion++; processController?.abort(); processLoading.value = false; downloadController?.abort(); downloadBusy.value = false; clearPaper(); }
function beginView() { closeMenus(); viewVersion++; stopPolling(); sendController?.abort(); stopController?.abort(); stopBusy.value = false; abortMaterials(); conversationLoading.value = false; conversationError.value = ''; artifactError.value = ''; processError.value = ''; downloadError.value = ''; processEvents.value = []; processOpen.value = false; panelOpen.value = false; sidebarOpen.value = false; }
function newConversation() { historyQuery.value = ''; beginView(); selectedKey.value = NEW_CHAT; nearBottom.value = true; void nextTick(() => { scrollToBottom(); inputElement.value?.focus(); }); }
function selectConversation(taskId: string, acknowledged?: ConversationView) {
  const fromSidebar = compactLayout.value && sidebarOpen.value;
  beginView(); selectedKey.value = taskId; nearBottom.value = true;
  if (acknowledged) { applyConversation(acknowledged, true); schedulePolling(); } else void pollConversation();
  void nextTick(() => { scrollToBottom(); if (fromSidebar && selectedKey.value === taskId) inputElement.value?.focus(); });
}
function schedulePolling() { const data = conversation.value; if (!data || disposed || stopBusy.value || currentPending.value?.busy || conversationError.value) return; if (data.busy || data.runs.some(run => running.has(run.status))) { const version = pollVersion; if (pollTimer !== null) clearTimeout(pollTimer); pollTimer = setTimeout(() => { pollTimer = null; if (version === pollVersion) void pollConversation(); }, 1400); } }
async function pollConversation() {
  const key = selectedKey.value; if (key === NEW_CHAT || stopBusy.value || currentPending.value?.busy || pollController) return;
  const version = viewVersion; const cycle = pollVersion; const write = writeVersions[key] || 0;
  const controller = new AbortController(); pollController = controller; conversationLoading.value = !views[key];
  const active = () => !disposed && version === viewVersion && cycle === pollVersion && selectedKey.value === key && write === (writeVersions[key] || 0) && !controller.signal.aborted;
  try { const data = await getConversation(key, controller.signal); if (!active()) return; applyConversation(data, nearBottom.value); conversationError.value = ''; if (panelOpen.value) await loadArtifacts(); if (processOpen.value) await loadProcess(); }
  catch (error) { if (active()) conversationError.value = `读取对话失败：${errorText(error)}`; }
  finally { if (active()) { conversationLoading.value = false; pollController = null; schedulePolling(); } }
}
function retryConversation() { if (stopBusy.value || currentPending.value?.busy) return; stopPolling(); conversationError.value = ''; void pollConversation(); }
async function refreshHistory() {
  historyController?.abort(); const controller = new AbortController(); historyController = controller;
  const version = ++historyVersion; const write = historyWriteVersion; historyLoading.value = true; historyError.value = '';
  try { const received = await getConversations(controller.signal); const data = received.filter(task => !trashedIds.has(task.id)); if (disposed || version !== historyVersion) return; if (write === historyWriteVersion) tasks.value = data; else { const byId = new Map(data.map(task => [task.id, task])); for (const task of tasks.value) { const item = byId.get(task.id); if (!item || item.updated_at <= task.updated_at) byId.set(task.id, task); } tasks.value = [...byId.values()].sort((a,b) => b.updated_at.localeCompare(a.updated_at)); } historyLoaded.value = true; }
  catch (error) { if (!disposed && version === historyVersion && !controller.signal.aborted) historyError.value = `读取记录失败：${errorText(error)}。现有历史仍保留。`; }
  finally { if (!disposed && version === historyVersion) historyLoading.value = false; }
}
async function sendDraft() {
  if (!canSend.value) return; const key = selectedKey.value; const content = draft.value.trim();
  if (Array.from(content).length > inputLimit.value) { sendErrors[key] = `消息不能超过 ${inputLimit.value} 字符。`; return; }
  pending[key] = { request_id: crypto.randomUUID(), content, mode: currentMode.value, snapshot: draft.value, fromDraft: true, busy: false, error: '' }; await transmit(key);
}
async function sendControl(mode: 'pause' | 'resume' | 'cancel') {
  if (controlsDisabled.value || !conversation.value) return; const key = selectedKey.value;
  const content = { pause: '暂停当前调研', resume: '继续当前调研', cancel: '停止当前调研' }[mode];
  pending[key] = { request_id: crypto.randomUUID(), content, mode, snapshot: '', fromDraft: false, busy: false, error: '' }; await transmit(key);
}
async function stopWork() {
  const key = selectedKey.value;
  if (!conversation.value || currentPending.value || stopBusy.value) return;
  const view = viewVersion; stopPolling();
  const write = (writeVersions[key] || 0) + 1; writeVersions[key] = write;
  const controller = new AbortController(); stopController = controller; stopBusy.value = true; sendErrors[key] = '';
  const active = () => !disposed && view === viewVersion && key === selectedKey.value && write === writeVersions[key] && !controller.signal.aborted;
  try { const data = await stopConversation(key, controller.signal); if (active()) { applyConversation(data, nearBottom.value); conversationError.value = ''; if (panelOpen.value) void loadArtifacts(); } }
  catch (error) { if (active()) sendErrors[key] = `停止请求未确认：${errorText(error)}。已有消息与草稿保留，可重新停止。`; }
  finally { if (active()) { stopBusy.value = false; stopController = null; schedulePolling(); } }
}
async function retrySend() { if (currentPending.value && !currentPending.value.busy) await transmit(selectedKey.value); }
async function transmit(key: string) {
  const request = pending[key]; if (!request || request.busy) return;
  const version = viewVersion; stopPolling(); const write = (writeVersions[key] || 0) + 1; writeVersions[key] = write;
  const controller = new AbortController(); sendController = controller; request.busy = true; request.error = ''; sendErrors[key] = '';
  try {
    const data = await sendConversationMessage(key === NEW_CHAT ? null : key, { content: request.content, mode: request.mode, request_id: request.request_id }, controller.signal);
    if (disposed || write !== writeVersions[key] || trashedIds.has(key)) return;
    if (request.fromDraft && drafts[key] === request.snapshot) drafts[key] = '';
    if (key === NEW_CHAT) { drafts[data.task.id] = drafts[key] || ''; drafts[key] = ''; modes[data.task.id] = request.mode; }
    delete pending[key]; applyConversation(data, nearBottom.value);
    if (version === viewVersion && selectedKey.value === key) { if (key === NEW_CHAT) selectConversation(data.task.id, data); else { conversationError.value = ''; if (panelOpen.value) void loadArtifacts(); } }
  } catch (error) {
    if (disposed) return;
    if (error instanceof ApiError && error.status >= 400 && error.status < 500) { sendErrors[key] = `消息未被接受：${errorText(error)}。草稿仍保留。`; delete pending[key]; }
    else request.error = controller.signal.aborted ? '已切换对话，请求结果未确认。返回后重试原消息，沿用同一请求标识。' : `${errorText(error)}。服务可能已接收；重试原消息不会新建重复请求。`;
  } finally { request.busy = false; if (sendController === controller) sendController = null; if (!disposed && version === viewVersion && selectedKey.value === key) schedulePolling(); }
}
async function loadModelSettings() {
  const version = ++modelReadVersion;
  try { const value = await getModelSettings(pageController.signal); if (!disposed && version === modelReadVersion) applyModelSettings(value); }
  catch (error) { if (!disposed && version === modelReadVersion && !pageController.signal.aborted) healthError.value = errorText(error); }
}
function openModelPicker() { if (modelMenu.value) { modelMenu.value.open = true; modelMenu.value.querySelector('summary')?.focus(); } }
function onModelMenuToggle(event: Event) { if ((event.target as HTMLDetailsElement).open) void loadModelSettings(); }
async function chooseModel(providerId: string, model: string) {
  if (modelChangeBusy.value || settingsBusy.value) return;
  modelChangeBusy.value = true;
  try { const value = await selectProviderModel(providerId, model, pageController.signal); if (!disposed) { applyModelSettings(value); closeMenus(); setNotice('已切换当前模型'); } }
  catch (error) { if (!disposed) setNotice(`切换模型失败：${errorText(error)}`, true); }
  finally { modelChangeBusy.value = false; }
}
function openTrash() { closeMenus(); trashOpen.value = true; }
function closeTrash() {
  trashOpen.value = false;
  void nextTick(() => { const target = compactLayout.value ? sidebarOpen.value ? trashButton.value : sidebarToggleButton.value : trashButton.value; target?.focus(); });
}
function openTrashFromSettings() {
  settingsOpen.value = false;
  sidebarOpen.value = false;
  openTrash();
}
function applyRestoredTasks(restored: Task[]) {
  historyController?.abort(); historyVersion++; historyLoading.value = false;
  for (const task of restored) { trashedIds.delete(task.id); upsertTask(task); }
  if (restored.some(task => task.id === undoTask.value?.id)) undoTask.value = null;
}
function applyDeletedTasks(ids: string[]) {
  for (const id of ids) {
    trashedIds.add(id);
    delete views[id]; delete drafts[id]; delete modes[id]; delete pending[id]; delete sendErrors[id]; delete selectedRuns[id];
  }
  if (ids.includes(undoTask.value?.id || '')) undoTask.value = null;
}
function openConversationAction(kind: 'rename' | 'trash', task: Task) { closeMenus(); conversationActionError.value = ''; conversationAction.value = { kind, task }; }
async function confirmConversationAction(title: string) {
  const action = conversationAction.value;
  if (!action || conversationActionBusy.value) return;
  const id = action.task.id;
  conversationActionBusy.value = true; conversationActionError.value = '';
  if (selectedKey.value === id) stopPolling();
  writeVersions[id] = (writeVersions[id] || 0) + 1;
  try {
    if (action.kind === 'rename') {
      const task = await renameConversation(id, title.trim(), pageController.signal);
      if (disposed) return;
      upsertTask(task);
      if (views[id]) views[id].task = task;
      setNotice('对话名称已更新');
    } else {
      const task = await trashConversation(id, pageController.signal);
      if (disposed) return;
      trashedIds.add(id); historyWriteVersion++;
      historyController?.abort(); historyVersion++; historyLoading.value = false;
      tasks.value = tasks.value.filter(item => item.id !== id);
      delete views[id]; delete pending[id];
      if (selectedKey.value === id) newConversation();
      setNotice('对话已移到回收站', false, task);
    }
    if (conversationAction.value === action) conversationAction.value = null;
  } catch (error) {
    if (!disposed) { const message = errorText(error); if (conversationAction.value === action) conversationActionError.value = message; else setNotice(message, true); }
  } finally { conversationActionBusy.value = false; if (selectedKey.value === id) schedulePolling(); }
}
async function restoreTask(id: string) {
  if (conversationActionBusy.value) return;
  conversationActionBusy.value = true;
  try {
    const task = await restoreConversation(id, pageController.signal);
    if (disposed) return;
    applyRestoredTasks([task]);
    setNotice('对话已恢复；已停止的工作不会自动重启');
  } catch (error) { if (!disposed) setNotice(`恢复失败：${errorText(error)}`, true); }
  finally { conversationActionBusy.value = false; }
}
async function copyMessage(content: string) {
  try { await navigator.clipboard.writeText(content); setNotice('回复已复制'); }
  catch { setNotice('无法访问剪贴板，请选择回复文本后复制', true); }
}
function clearPaper() { paperVersion++; paperController?.abort(); paperSelection.value = null; paperDetail.value = null; selectedCitation.value = null; paperError.value = ''; paperLoading.value = false; }
function closePanel() { panelOpen.value = false; artifactVersion++; artifactController?.abort(); artifactLoading.value = false; downloadController?.abort(); downloadBusy.value = false; clearPaper(); void nextTick(() => panelReturnFocus?.focus()); }
function togglePanel() { if (panelOpen.value) closePanel(); else { if (!selectedRuns[selectedKey.value] && latestRun.value) selectedRuns[selectedKey.value] = latestRun.value.id; panelOpen.value = true; void loadArtifacts(); } }
function chooseRun(runId: string) { selectedRuns[selectedKey.value] = runId; if (runMenu.value) runMenu.value.open = false; downloadController?.abort(); downloadBusy.value = false; clearPaper(); artifactError.value = ''; downloadError.value = ''; void loadArtifacts(); }
function openRun(runId: string) { panelOpen.value = true; panelTab.value = 'papers'; chooseRun(runId); }
function openPaper(paperId: string) { clearPaper(); paperSelection.value = { runId: selectedRunId.value, paperId }; void loadPaper(); }
function openCitation(citation: ChatCitation) { downloadController?.abort(); downloadBusy.value = false; downloadError.value = ''; panelOpen.value = true; panelTab.value = 'papers'; selectedRuns[selectedKey.value] = citation.run_id; clearPaper(); selectedCitation.value = citation; paperSelection.value = { runId: citation.run_id, paperId: citation.paper_id }; void loadArtifacts(); void loadPaper(); }
async function loadArtifacts() {
  if (!panelOpen.value || !selectedRunId.value) return;
  artifactController?.abort(); const controller = new AbortController(); artifactController = controller;
  const version = ++artifactVersion; const view = viewVersion; const runId = selectedRunId.value;
  const active = () => !disposed && view === viewVersion && version === artifactVersion && panelOpen.value && runId === selectedRunId.value && !controller.signal.aborted;
  artifactLoading.value = true;
  try {
    const [paperResult, reportResult] = await Promise.allSettled([getPapers(runId, controller.signal), getReport(runId, controller.signal)]); if (!active()) return;
    const data = artifacts[runId] || { papers: [], report: null, reportNotice: '', loaded: false }; const errors: string[] = [];
    if (paperResult.status === 'fulfilled') { data.papers = paperResult.value; data.loaded = true; } else errors.push(`读取文献失败：${errorText(paperResult.reason)}`);
    if (reportResult.status === 'fulfilled') data.report = reportResult.value;
    else if (reportResult.reason instanceof ApiError && reportResult.reason.status === 409) { data.report = null; data.reportNotice = `本次运行尚无可交付报告（${selectedRun.value ? runLabels[selectedRun.value.status] : '当前状态未知'}）。`; }
    else errors.push(`读取报告失败：${errorText(reportResult.reason)}`);
    artifacts[runId] = data; artifactError.value = errors.join('；');
  } finally { if (active()) artifactLoading.value = false; }
}
async function loadPaper() {
  const selection = paperSelection.value; if (!selection) return;
  paperController?.abort(); const controller = new AbortController(); paperController = controller;
  const version = ++paperVersion; const view = viewVersion;
  const active = () => !disposed && view === viewVersion && version === paperVersion && !controller.signal.aborted;
  paperLoading.value = true; paperError.value = '';
  try { const data = await getPaperDetail(selection.runId, selection.paperId, controller.signal); if (active()) paperDetail.value = data; }
  catch (error) { if (active()) paperError.value = `读取论文详情失败：${errorText(error)}`; }
  finally { if (active()) paperLoading.value = false; }
}
function onProcessToggle(event: Event) { processOpen.value = (event.target as HTMLDetailsElement).open; if (processOpen.value) void loadProcess(); else { processVersion++; processController?.abort(); processLoading.value = false; } }
async function loadProcess() {
  if (!processOpen.value || !latestRun.value) return;
  processController?.abort(); const controller = new AbortController(); processController = controller;
  const version = ++processVersion; const view = viewVersion; const runId = latestRun.value.id;
  if (processRunId !== runId) { processRunId = runId; processEvents.value = []; processError.value = ''; }
  const active = () => !disposed && view === viewVersion && version === processVersion && !controller.signal.aborted;
  processLoading.value = true;
  try { const data = await getRunEvents(runId, controller.signal); if (active()) { processEvents.value = data; processError.value = ''; } }
  catch (error) { if (active()) processError.value = `读取过程失败：${errorText(error)}`; }
  finally { if (active()) processLoading.value = false; }
}
async function downloadReport() {
  if (downloadBusy.value || !selectedRunId.value) return;
  const runId = selectedRunId.value; const view = viewVersion;
  const controller = new AbortController(); downloadController = controller; downloadBusy.value = true; downloadError.value = '';
  const active = () => !disposed && view === viewVersion && runId === selectedRunId.value && !controller.signal.aborted;
  try { const blob = await getMarkdownReport(runId, controller.signal); if (!active()) return; const url = URL.createObjectURL(blob); const link = document.createElement('a'); link.href = url; link.download = `paper-scout-${runId}.md`; link.click(); URL.revokeObjectURL(url); }
  catch (error) { if (active()) downloadError.value = `下载失败：${errorText(error)}`; }
  finally { if (active()) downloadBusy.value = false; }
}
onMounted(() => {
  resizeInput();
  window.addEventListener('resize', resizeInput);
  compactQuery.addEventListener('change', onLayoutChange);
  document.addEventListener('keydown', handleOverlayKey);
  void refreshHistory();
  void loadModelSettings();
});
onUnmounted(() => {
  window.removeEventListener('resize', resizeInput);
  compactQuery.removeEventListener('change', onLayoutChange);
  document.removeEventListener('keydown', handleOverlayKey);
  disposed = true; stopPolling(); abortMaterials(); sendController?.abort(); stopController?.abort(); historyController?.abort(); pageController.abort();
});
</script>
<style src="./workspace.css"></style>
