<template>
  <main :inert="settingsOpen" class="workspace" :class="{ 'panel-visible': panelOpen, 'welcome-view': selectedKey === NEW_CHAT, 'sidebar-collapsed': !compactLayout && sidebarCollapsed, resizing: !!resizing }" :style="paneStyle">
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
      :inert="compactLayout ? (!sidebarOpen || panelOpen) : sidebarCollapsed"
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
          <UiIcon :name="compactLayout ? 'close' : 'panelLeft'" />
        </button>
      </div>
      <button class="new-chat" aria-label="新建对话" @click="newConversation">
        <UiIcon name="edit" /><span>新建对话</span>
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
      <nav class="history-list" aria-label="历史研究对话" @scroll="onHistoryScroll">
        <section v-for="group in historyGroups" :key="group.label" class="history-group">
          <h2>{{ group.label }}</h2>
          <div v-for="task in group.tasks" :key="task.id" class="history-item" :class="{ selected: selectedKey === task.id }">
            <button class="history-select" :aria-current="selectedKey === task.id ? 'true' : undefined" :title="taskTitle(task)" @click="selectConversation(task.id)"><span class="history-copy"><span class="history-title">{{ taskTitle(task) }}</span></span><small class="history-date">{{ pending[task.id] ? '待确认' : drafts[task.id] ? '草稿' : shortDate(task.updated_at) }}</small></button>
            <details data-menu class="history-menu"><summary :aria-label="`对话操作：${taskTitle(task)}`"><UiIcon name="more" /></summary><div><button type="button" :disabled="conversationActionBusy || !!pending[task.id]" @click="openConversationAction('rename', task)"><UiIcon name="edit" />重命名</button><button type="button" class="danger-text" :disabled="conversationActionBusy" @click="openConversationAction('trash', task)"><UiIcon name="trash" />删除对话</button></div></details>
          </div>
        </section>
        <p v-if="historyLoaded && historyQuery.trim() && !historyGroups.length && !historyLoading" class="history-empty">没有找到相关对话，换个关键词试试。</p>
        <button v-if="historyMore && !historyLoading" type="button" class="text-button history-more" @click="loadMoreHistory">加载更多对话</button>
      </nav>
      <div class="sidebar-actions">
      <button ref="trashButton" class="sidebar-settings" type="button" @click="openTrash"><UiIcon name="trash" />回收站<UiIcon name="chevronRight" /></button>
      <button ref="settingsButton" class="sidebar-settings" type="button" aria-label="打开设置" @click="openSettings('general')"><UiIcon name="settings" />设置<UiIcon name="chevronRight" /></button>
      </div>
      <div v-if="!compactLayout" class="resize-handle resize-sidebar" :class="{ dragging: resizing === 'sidebar' }" role="separator" aria-orientation="vertical" aria-label="调整对话列表宽度，双击恢复默认" tabindex="0" :aria-valuemin="PANE_LIMITS.sidebar[0]" :aria-valuemax="PANE_LIMITS.sidebar[1]" :aria-valuenow="preferences.sidebarWidth ?? undefined" @pointerdown="startResize('sidebar', $event)" @keydown="nudgePane('sidebar', $event)" @dblclick="preferences.sidebarWidth = null"></div>
    </aside>

    <section class="chat-shell" :inert="compactLayout && (sidebarOpen || panelOpen)" aria-label="研究对话">
      <header class="chat-header">
        <div class="header-title">
          <button ref="sidebarToggleButton" class="icon-button menu-toggle" aria-label="打开对话列表" :aria-expanded="compactLayout ? sidebarOpen : !sidebarCollapsed" @click="openSidebar">
            <UiIcon name="panelLeft" />
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
            aria-label="查看本对话资料"
            :aria-expanded="panelOpen"
            @click="togglePanel"
          >
            <UiIcon name="documents" />
            <span>本对话资料</span>
          </button>
        </div>
      </header>

      <div class="chat-body">

        <div ref="timelineElement" class="timeline-scroll" @scroll="trackScroll">
          <div class="timeline-content">
            <section v-if="selectedKey === NEW_CHAT" class="empty-state">
              <h2>今天，想研究什么？</h2>
              <p class="empty-description">从一个问题开始，一起找到有据可查的答案。</p>
            </section>

            <p v-if="conversationLoading" class="muted" role="status">正在读取对话…</p>
            <div v-if="conversationError" class="error-message" role="alert">
              {{ conversationError }}
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
                  <div class="message-body">
                    <div v-if="entry.message.work" class="turn-activity">
                      <template v-if="entry.message.status === 'processing'">
                        <p class="work-activity" role="status"><span class="processing-indicator" aria-hidden="true"></span><span>{{ entry.message.work.activity || '正在处理' }}</span></p>
                        <ul v-if="entry.message.work.todos.length" class="todo-list" aria-label="计划">
                          <li v-for="(item, index) in entry.message.work.todos" :key="index" :class="item.status"><UiIcon v-if="item.status === 'done'" name="check" /><span v-else class="todo-dot" aria-hidden="true"></span><span class="sr-only">{{ todoLabels[item.status] }}：</span>{{ item.text }}</li>
                        </ul>
                      </template>
                      <details class="process-records" :open="processState(entry.message.id).open" @toggle="onProcessToggle(entry.message.id, $event)">
                        <summary><span class="process-label"><UiIcon name="process" />{{ workSummary(entry.message) }}</span></summary>
                        <div class="process-content">
                          <p v-if="processState(entry.message.id).loading" class="muted" role="status">正在读取过程记录…</p>
                          <p v-if="processState(entry.message.id).error" class="error-message" role="alert">{{ processState(entry.message.id).error }} <button class="text-button" @click="loadProcess(entry.message.id)">重试</button></p>
                          <ol v-if="processState(entry.message.id).items.length" class="process-steps">
                            <li v-for="item in processState(entry.message.id).items" :key="item.id">
                              <details v-if="item.detail || item.entries.length" class="process-fold">
                                <summary><UiIcon name="chevronRight" /><span class="fold-title">{{ item.title }}</span><small :class="{ failed: item.failures }">{{ stepMeta(item) }}</small><time :datetime="item.time">{{ clockTime(item.time) }}</time></summary>
                                <p v-if="item.detail" class="fold-detail">{{ item.detail }}</p>
                                <ol v-if="item.entries.length" class="event-list">
                                  <template v-for="logEntry in item.entries" :key="logEntry.id">
                                    <li v-if="logEntry.kind === 'event'"><span>{{ eventLabels[logEntry.event.category] || logEntry.event.category }}</span><time :datetime="logEntry.event.created_at">{{ clockTime(logEntry.event.created_at) }}</time><p>{{ logEntry.event.message }}</p></li>
                                    <li v-else class="reader-group">
                                      <details class="process-fold">
                                        <summary><UiIcon name="chevronRight" /><span class="fold-title">{{ logEntry.title }}</span><small :class="{ failed: logEntry.status === '失败' }">{{ logEntry.status || (entry.message.status === 'processing' ? '阅读中' : entry.message.work.continued ? '见下一条回复' : '已中止') }}</small></summary>
                                        <ol class="event-list">
                                          <li v-for="event in logEntry.events" :key="event.id"><span>{{ eventLabels[event.category] || event.category }}</span><time :datetime="event.created_at">{{ clockTime(event.created_at) }}</time><p>{{ event.message }}</p></li>
                                        </ol>
                                      </details>
                                    </li>
                                  </template>
                                </ol>
                              </details>
                              <p v-else class="process-line" :class="{ 'from-user': item.fromUser }"><span class="fold-title">{{ item.title }}</span><time :datetime="item.time">{{ clockTime(item.time) }}</time></p>
                            </li>
                          </ol>
                          <p v-else-if="!processState(entry.message.id).loading && !processState(entry.message.id).error" class="muted">还没有记录。</p>
                        </div>
                      </details>
                      <p v-if="entry.message.work.stop_reason" class="work-note">提前结束：{{ entry.message.work.stop_reason }}</p>
                      <p v-if="entry.message.work.continued" class="work-note">收到新消息，后续工作在下一条回复中继续。</p>
                    </div>
                    <template v-if="entry.message.content">
                      <p v-if="entry.message.role === 'user'" class="message-text" :title="formatTime(entry.message.created_at)">{{ entry.message.content }}</p>
                      <MessageMarkdown v-else :content="entry.message.content" />
                    </template>
                    <p v-else-if="!entry.message.work" class="processing-placeholder" role="status"><span v-if="['queued', 'processing'].includes(entry.message.status)" class="processing-indicator" aria-hidden="true"></span>{{ messageLabels[entry.message.status] }}…</p>
                    <span v-if="entry.message.content && entry.message.status !== 'completed'" class="message-status" :class="entry.message.status">{{ messageLabels[entry.message.status] }}</span>
                    <p v-if="entry.message.error_category && entry.message.error_category !== 'user_cancelled'" class="error-message" role="alert">错误类别：{{ entry.message.error_category }}</p>
                    <div v-if="entry.message.citations.length" class="citation-buttons" aria-label="回答引用">
                      <button v-for="(citation, index) in entry.message.citations" :key="`${citation.source_text_id}-${index}`" :aria-label="`引用 ${index + 1}：${sourceLabels[citation.source_type]}${citation.page_number != null ? `，PDF 第 ${citation.page_number} 页` : ''}`" :title="citation.quote" @click="openCitation(citation)">
                        <span>[{{ index + 1 }}]</span>{{ sourceLabels[citation.source_type] }}{{ citation.page_number != null ? ` · p${citation.page_number}` : '' }}<UiIcon name="arrowUpRight" />
                      </button>
                    </div>
                    <div v-if="entry.message.role === 'assistant' && (entry.message.content || entry.message.run_id || entry.message.work?.report_id)" class="message-actions">
                      <button v-if="entry.message.content && entry.message.status === 'completed'" class="message-copy icon-button" type="button" aria-label="复制回复" title="复制回复" @click="copyMessage(entry.message.content)"><UiIcon name="copy" /></button>
                      <button v-if="entry.message.work?.report_id" class="message-artifact text-button" @click="openReport(entry.message.work!)"><UiIcon name="documents" />查看报告</button>
                      <button v-if="entry.message.run_id" class="message-artifact text-button" @click="openRun(entry.message.run_id!)"><UiIcon name="documents" />查看调研资料</button>
                      <time :datetime="entry.message.created_at">{{ formatTime(entry.message.created_at) }}</time>
                    </div>
                  </div>
                </article>
              </template>
              <p v-if="!conversation.messages.length && !conversation.runs.length" class="muted">这条记录还没有对话或调研。可以在下方直接继续。</p>
            </template>
          </div>
        </div>
        <footer class="composer-dock">
          <button v-if="!nearBottom && conversation" class="jump-bottom" @click="scrollToBottom"><UiIcon name="arrowDown" />回到最新消息</button>
          <p v-if="modelConfigured === false" class="model-note"><UiIcon name="info" /><span>{{ availableProviders.length ? '尚未选择模型，请在输入区选择要使用的型号。' : '请先配置AI服务，再选择对话使用的模型。' }}</span><button type="button" class="text-button" @click="availableProviders.length ? openModelPicker() : openSettings('model')">{{ availableProviders.length ? '选择模型' : '配置AI服务' }}</button></p>
          <div v-if="currentPending" class="pending-notice" role="status">
            <div><strong>{{ currentPending.busy ? '正在发送…' : '发送未确认' }}</strong><p>{{ currentPending.error || '等待服务确认，草稿已保留。' }}</p><blockquote v-if="!currentPending.busy">{{ currentPending.content }}</blockquote></div>
            <button v-if="!currentPending.busy" class="text-button" aria-label="重试发送" @click="retrySend">重试原消息</button>
          </div>
          <p v-if="sendErrors[selectedKey]" class="error-message" role="alert">{{ sendErrors[selectedKey] }}</p>
          <form class="composer" @submit.prevent="sendDraft">
            <label class="sr-only" for="chat-input">输入消息</label>
            <textarea id="chat-input" ref="inputElement" v-model="draft" :maxlength="inputLimit" rows="2" :placeholder="selectedKey === NEW_CHAT ? '描述你想研究的问题' : '继续提问，或补充研究方向'" :title="preferences.sendShortcut === 'enter' ? 'Enter 发送，Shift + Enter 换行' : 'Ctrl / ⌘ + Enter 发送，Enter 换行'" aria-label="输入消息" @keydown="handleInputKey"></textarea>
            <div class="composer-bottom">
              <div class="composer-options">
                <details ref="modelMenu" data-menu class="model-menu" @toggle="onModelMenuToggle">
                  <summary aria-label="选择当前模型" :title="currentProvider?.name"><span>{{ modelSettings?.enabled ? modelSettings.model : '选择模型' }}</span><UiIcon name="chevronDown" /></summary>
                  <div class="model-menu-options"><p>选择用于后续对话的模型</p><div v-for="provider in availableProviders" :key="provider.id" class="model-menu-provider"><p>{{ provider.name }}</p><button v-for="model in provider.models" :key="model" type="button" :disabled="modelChangeBusy || settingsBusy || !!modelSettings?.busy" :aria-label="`${provider.name} · ${model}`" :aria-pressed="modelSettings?.enabled && provider.id === modelSettings.active_provider_id && model === modelSettings.active_model" @click="chooseModel(provider.id, model)"><span><strong>{{ model }}</strong></span><UiIcon v-if="modelSettings?.enabled && provider.id === modelSettings.active_provider_id && model === modelSettings.active_model" name="check" /></button></div><p v-if="modelSettings?.busy">当前这一轮结束或停止后可切换。</p><button type="button" class="manage-models" @click="closeMenus(); openSettings('model')"><UiIcon name="settings" />管理AI服务</button></div>
                </details>
                <details ref="intentMenu" data-menu class="intent-menu">
                  <summary aria-label="选择消息意图"><UiIcon :name="currentMode === 'research' ? 'search' : currentMode === 'ask' ? 'book' : 'chat'" />{{ modeLabels[currentMode] }}<UiIcon name="chevronDown" /></summary>
                  <div class="intent-options">
                    <button v-for="mode in intentModes" :key="mode" type="button" :class="{ selected: currentMode === mode }" :aria-pressed="currentMode === mode" @click="chooseMode(mode)"><span>{{ modeLabels[mode] }}</span><small>{{ modeDescriptions[mode] }}</small></button>
                  </div>
                </details>
              </div>
              <div class="send-group">
                <span v-if="draft.length" class="char-count">{{ draft.length }}/{{ inputLimit }}</span>
                <button v-if="conversation?.busy" type="button" class="send-button stop-button" aria-label="停止" :title="stopBusy ? '正在停止…' : '停止当前工作'" :disabled="!!currentPending || stopBusy" @click="stopWork"><UiIcon name="stop" /></button>
                <button v-if="!conversation?.busy || draft.trim()" type="submit" class="send-button" aria-label="发送消息" :disabled="!canSend"><UiIcon name="arrowUp" /></button>
              </div>
            </div>
          </form>
          <div class="composer-footnote">
            <span v-if="conversation?.busy" class="busy-hint">执行中也可以发送，agent 会在当前这一步之后读到</span>
            <button type="button" class="model-status" title="AI服务与模型选择" @click="availableProviders.length && !modelConfigured ? openModelPicker() : openSettings('model')">{{ modelConfigured === true ? '模型已配置' : modelConfigured === false ? availableProviders.length ? '请选择模型' : '配置AI服务' : healthError ? '连接状态未知 · 设置' : 'AI服务' }}</button>
          </div>
        </footer>
        <section v-if="selectedKey === NEW_CHAT" class="starter-section" aria-labelledby="examples-title">
          <div class="starter-heading"><h3 id="examples-title">从这些方向开始</h3></div>
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
      <div v-if="!compactLayout" class="resize-handle resize-panel" :class="{ dragging: resizing === 'materials' }" role="separator" aria-orientation="vertical" aria-label="调整资料面板宽度，双击恢复默认" tabindex="0" :aria-valuemin="PANE_LIMITS.materials[0]" :aria-valuemax="PANE_LIMITS.materials[1]" :aria-valuenow="preferences.materialsWidth ?? undefined" @pointerdown="startResize('materials', $event)" @keydown="nudgePane('materials', $event)" @dblclick="preferences.materialsWidth = null"></div>
      <header class="panel-header">
        <h2 id="materials-title"><UiIcon name="documents" />本对话资料</h2>
        <button ref="panelCloseButton" class="icon-button" aria-label="关闭资料面板" @click="closePanel"><UiIcon name="close" /></button>
      </header>
      <div class="panel-content">
        <details v-if="sortedRuns.length > 1" ref="runMenu" data-menu class="run-picker">
          <summary>{{ selectedRun ? runTitle(selectedRun) : '选择资料' }}<UiIcon name="chevronDown" /></summary>
          <div><button v-for="run in sortedRuns" :key="run.id" :class="{ selected: selectedRunId === run.id }" :aria-pressed="selectedRunId === run.id" @click="chooseRun(run.id)"><strong>{{ runTitle(run) }}</strong><small>{{ formatTime(run.created_at) }} · {{ run.initial_topic }}</small></button></div>
        </details>
        <p v-if="selectedRun && !selectedRun.agent" class="panel-note">{{ selectedRun.initial_input?.topic || selectedRun.initial_topic }}</p>
        <div class="panel-tabs" aria-label="资料类型">
          <button :class="{ active: panelTab === 'papers' }" :aria-pressed="panelTab === 'papers'" @click="panelTab = 'papers'"><UiIcon name="book" />文献<span v-if="artifact?.loaded">{{ artifact.papers.length }}</span></button>
          <button :class="{ active: panelTab === 'analysis' }" :aria-pressed="panelTab === 'analysis'" @click="panelTab = 'analysis'; clearPaper()">分析与比较</button>
          <button :class="{ active: panelTab === 'report' }" :aria-pressed="panelTab === 'report'" @click="panelTab = 'report'; clearPaper()"><UiIcon name="documents" />研究报告</button>
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
            <button v-for="(paper, index) in artifact?.papers || []" :key="paper.id" class="paper-row" @click="openPaper(paper.id)">
              <span class="paper-number">{{ String(index + 1).padStart(2, '0') }}</span>
              <span class="paper-copy"><span class="paper-title">{{ paper.title }}</span><small>{{ paper.year ?? '年份缺失' }} · {{ paper.authors.slice(0, 2).join('、') || '作者缺失' }}{{ paper.authors.length > 2 ? ' 等' : '' }}</small><span class="paper-link">查看来源与读取状态</span></span>
              <UiIcon name="arrowUpRight" />
            </button>
            <p v-if="artifact?.loaded && !artifact.papers.length" class="muted">暂无已纳入的论文。</p>
          </template>
        </template>
        <ResearchAnalysisView v-else-if="panelTab === 'analysis' && selectedRun" :run="selectedRun" @paper="openPaper" />
        <template v-else-if="panelTab === 'report'">
          <template v-if="artifact?.report">
            <div class="report-heading"><h3>报告快照</h3><div class="report-downloads"><button :disabled="downloadBusy" class="download-button" @click="downloadReport('md')">下载 .md</button><button v-if="artifact.report.document" :disabled="downloadBusy" class="download-button" @click="downloadReport('docx')">Word</button><button v-if="artifact.report.document" :disabled="downloadBusy" class="download-button" @click="downloadReport('pdf')">PDF</button></div></div>
            <p class="report-title">{{ artifact.report.title }}</p>
            <p v-if="downloadError" class="error-message" role="alert">{{ downloadError }}</p>
            <div v-if="artifact.report.document" class="report-claims">
              <section v-for="section in artifact.report.document.sections" :key="section.title"><h4>{{ section.title }}</h4><div v-for="(claim, index) in section.claims" :key="index"><p><small>{{ originLabels[claim.origin] }}</small> {{ claim.text }}</p><button v-for="(id, evidenceIndex) in claim.evidence_ids" :key="id" class="text-button" @click="openReportEvidence(id)">查看依据 {{ evidenceIndex + 1 }}</button></div></section>
            </div>
            <ul v-if="artifact.report.gaps.length" class="gap-list"><li v-for="gap in artifact.report.gaps" :key="gap">{{ gap }}</li></ul>
            <p v-if="artifact.report.stop_reason" class="muted">停止说明：{{ artifact.report.stop_reason }}</p>
            <pre class="markdown-preview">{{ artifact.report.content_markdown }}</pre>
          </template>
          <p v-else-if="artifact?.loaded" class="muted">{{ artifact.reportNotice }}</p>
        </template>
      </div>
    </aside>
  </main>
  <Teleport to="body">
    <Transition name="toast">
      <div v-if="notice" :key="noticeKey" class="toast" :class="{ 'toast-error': noticeError }" :role="noticeError ? 'alert' : 'status'" @mouseenter="holdNotice" @mouseleave="scheduleNotice" @focusin="holdNotice" @focusout="scheduleNotice"><UiIcon :name="noticeError ? 'info' : 'check'" /><span>{{ notice }}</span><button v-if="undoTask" type="button" class="text-button" :disabled="conversationActionBusy" @click="restoreTask(undoTask.id)">撤销删除</button><button type="button" class="icon-button" aria-label="关闭提示" @click="clearNotice"><UiIcon name="close" /></button></div>
    </Transition>
  </Teleport>
  <SettingsDialog :open="settingsOpen" :initial-tab="settingsInitialTab" :conversation="conversation" @close="closeSettings" @open-trash="openTrashFromSettings" @saved="applyModelSettings" @busy="settingsBusy = $event" @notice="setNotice" />
  <TrashDialog :open="trashOpen" @close="closeTrash" @restored="applyRestoredTasks" @deleted="applyDeletedTasks" @notice="setNotice" />
  <ActionDialog v-if="conversationAction" :title="conversationAction.kind === 'rename' ? '重命名对话' : '删除这个对话？'" :description="conversationAction.kind === 'rename' ? '' : '对话将移到回收站，可随时恢复；正在执行的对话和调研会停止。'" :confirm-label="conversationAction.kind === 'rename' ? '保存名称' : '移到回收站'" :editable="conversationAction.kind === 'rename'" :initial-value="taskTitle(conversationAction.task).slice(0, 120)" :danger="conversationAction.kind === 'trash'" :busy="conversationActionBusy" :error="conversationActionError" @close="closeConversationAction" @confirm="confirmConversationAction" />
</template>
<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, reactive, ref, watch } from 'vue';
import UiIcon from './components/UiIcon.vue';
import MessageMarkdown from './components/MessageMarkdown.vue';
import ResearchAnalysisView from './components/ResearchAnalysis.vue';
import { originLabels } from './analysisLabels';
import PaperDetailView from './components/PaperDetail.vue';
import SettingsDialog from './components/SettingsDialog.vue';
import ActionDialog from './components/ActionDialog.vue';
import TrashDialog from './components/TrashDialog.vue';
import { useDismissableMenus, closeMenus } from './composables/useDismissableMenus';
import { PANE_LIMITS, usePreferences } from './composables/usePreferences';
import { eventLabels, runLabels, todoLabels } from './runLabels';
import type { ModelSettings } from './api/client';
import { ApiError, getModelSettings, selectProviderModel, renameConversation, trashConversation, restoreConversation, getConversations, getConversation, sendConversationMessage, stopConversation, getPapers, getRunEvents, getReport, getPaperDetail, getReportFile, type Task, type ConversationView, type ChatMode, type ChatMessage, type ChatCitation, type AgentWork, type Run, type ChatStatus, type SourceType, type Paper, type Report, type RunEvent, type PaperDetail } from './api/client.ts';

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
const noticeKey = ref(0);
let noticeTimer: number | undefined;
function clearNotice() { window.clearTimeout(noticeTimer); notice.value = ''; undoTask.value = null; }
function holdNotice() { window.clearTimeout(noticeTimer); }
// 带撤销的提示留更久，给出操作时间。
function scheduleNotice() { window.clearTimeout(noticeTimer); if (notice.value && !noticeError.value) noticeTimer = window.setTimeout(clearNotice, undoTask.value ? 8000 : 4000); }
// 错误提示需用户关闭；期间的普通提示不顶替它，带撤销的除外。
function setNotice(message: string, error = false, undo: Task | null = null) { if (!error && !undo && noticeError.value && notice.value) return; notice.value = message; noticeError.value = error; undoTask.value = undo; noticeKey.value += 1; scheduleNotice(); }

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
const canSend = computed(() => !(availableProviders.value.length && modelConfigured.value === false) && !!draft.value.trim() && !stopBusy.value && !currentPending.value && !conversationLoading.value && (selectedKey.value === NEW_CHAT || !!conversation.value));
const sortedRuns = computed(() => [...(conversation.value?.runs || [])].sort((a, b) => b.created_at.localeCompare(a.created_at)));
const latestRun = computed(() => sortedRuns.value[0]);
const legacyOrder = computed(() => (conversation.value?.runs || []).filter(run => !run.agent).sort((a, b) => a.created_at.localeCompare(b.created_at)).map(run => run.id));
const runTitle = (run: Run) => run.agent ? '对话 agent' : `调研 ${runNumber(run.id)} · ${runLabels[run.status]}`;
const elapsedText = (seconds: number) => {
  const total = Math.max(0, Math.round(seconds));
  const hours = Math.floor(total / 3600); const minutes = Math.floor((total % 3600) / 60); const rest = total % 60;
  if (hours) return `${hours}h ${minutes}m ${rest}s`;
  if (minutes) return `${minutes}m ${rest}s`;
  return rest === 0 ? '<1s' : `${rest}s`;
};
// 服务端只在外部调用和步骤边界保存耗时；执行中按最近一次保存时间在本地续算，避免长时间模型调用期间计时停住。
const clock = ref(Date.now());
let clockTimer: ReturnType<typeof setInterval> | null = null;
const liveSeconds = (message: ChatMessage, work: AgentWork) => message.status === 'processing' && work.progress_at ? work.seconds + Math.max(0, (clock.value - Date.parse(work.progress_at)) / 1000) : work.seconds;
function workSummary(message: ChatMessage) {
  const work = message.work!;
  if (message.status === 'processing') return `第 ${work.steps}/${work.limits.steps} 步 · 外部调用 ${work.calls}/${work.limits.calls} · 已用 ${elapsedText(liveSeconds(message, work))}`;
  const parts = [`${work.steps} 步`, `外部调用 ${work.calls} 次`];
  if (work.subagents) parts.push(`阅读子 agent ${work.subagents} 个`);
  parts.push(`用时 ${elapsedText(work.seconds)}`);
  return parts.join(' · ');
}
const selectedRunId = computed(() => selectedRuns[selectedKey.value] || latestRun.value?.id || '');
const selectedRun = computed(() => conversation.value?.runs.find(run => run.id === selectedRunId.value));
const legacyRuns = computed(() => (conversation.value?.runs || []).filter(run => !run.agent && !conversation.value?.messages.some(message => message.run_id === run.id)));
// 执行中连发的消息并入同一轮后，中间的助手回复既无内容也无工作记录，不显示。
const hidden = (message: ChatMessage) => message.role === 'assistant' && message.status === 'completed' && !message.content && !message.work;
type TimelineEntry = { kind: 'message'; id: string; created_at: string; message: ChatMessage } | { kind: 'run'; id: string; created_at: string; run: Run };
const timeline = computed<TimelineEntry[]>(() => [...(conversation.value?.messages || []).filter(message => !hidden(message)).map(message => ({ kind: 'message' as const, id: message.id, created_at: message.created_at, message })), ...legacyRuns.value.map(run => ({ kind: 'run' as const, id: run.id, created_at: run.created_at, run }))].sort((a, b) => a.created_at.localeCompare(b.created_at)));
const messageLabels: Record<ChatStatus, string> = { queued: '等待处理', processing: '正在处理', completed: '已完成', failed: '回复失败', interrupted: '回复已中断' };
const sourceLabels: Record<SourceType, string> = { metadata: '元数据', abstract: '摘要', fulltext: '全文' };
const modeLabels: Record<ChatMode, string> = { auto: '自动理解', research: '补充检索', ask: '只问已有资料' };
const modeDescriptions: Record<ChatMode, string> = { auto: '根据对话理解问题、澄清或调研', research: '明确请求检索和阅读论文', ask: '根据已保存来源回答，不发起新检索' };
const intentModes: ChatMode[] = ['auto', 'research', 'ask'];
const examples = [
  { title: '多智能体协作', icon: 'network' as const, text: '帮我梳理多智能体通信的研究方向，先看看有哪些值得关注的问题。' },
  { title: '小样本 RAG', icon: 'search' as const, text: '我想研究小样本条件下的检索增强生成，关注评估方法和局限。' },
  { title: '长上下文与 RAG', icon: 'book' as const, text: '我对长上下文与 RAG 的关系还不太清楚，可以先帮我明确问题吗？' },
];
const compactQuery = window.matchMedia('(max-width: 1100px)');
const compactLayout = ref(compactQuery.matches);
const sidebarOpen = ref(false);
const sidebarCollapsed = ref(false);
const panelOpen = ref(false);
type Pane = 'sidebar' | 'materials';
const resizing = ref<Pane | null>(null);
const paneStyle = computed(() => {
  if (compactLayout.value) return undefined;
  const style: Record<string, string> = {};
  if (preferences.sidebarWidth !== null) style['--sidebar-width'] = `${preferences.sidebarWidth}px`;
  // 窗口变窄时给对话区至少保留 440px。
  if (preferences.materialsWidth !== null) style['--materials-width'] = `min(${preferences.materialsWidth}px, calc(100vw - var(--sidebar-width) - 440px))`;
  return style;
});
function setPane(pane: Pane, width: number) {
  const [min, max] = PANE_LIMITS[pane];
  preferences[pane === 'sidebar' ? 'sidebarWidth' : 'materialsWidth'] = Math.round(Math.min(max, Math.max(min, width)));
}
function paneWidth(pane: Pane) {
  return (pane === 'sidebar' ? sidebarElement.value : panelElement.value)?.getBoundingClientRect().width ?? PANE_LIMITS[pane][0];
}
function startResize(pane: Pane, event: PointerEvent) {
  if (event.button !== 0) return;
  event.preventDefault();
  const handle = event.currentTarget as HTMLElement;
  handle.setPointerCapture(event.pointerId);
  const startX = event.clientX, startWidth = paneWidth(pane);
  resizing.value = pane;
  const move = (next: PointerEvent) => setPane(pane, startWidth + (pane === 'sidebar' ? next.clientX - startX : startX - next.clientX));
  const end = () => {
    resizing.value = null;
    handle.removeEventListener('pointermove', move);
    handle.removeEventListener('pointerup', end);
    handle.removeEventListener('pointercancel', end);
  };
  handle.addEventListener('pointermove', move);
  handle.addEventListener('pointerup', end);
  handle.addEventListener('pointercancel', end);
}
function nudgePane(pane: Pane, event: KeyboardEvent) {
  if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') return;
  event.preventDefault();
  const wider = (event.key === 'ArrowRight') === (pane === 'sidebar');
  setPane(pane, paneWidth(pane) + (wider ? 16 : -16));
}
const sidebarElement = ref<HTMLElement | null>(null);
const panelElement = ref<HTMLElement | null>(null);
const sidebarToggleButton = ref<HTMLButtonElement | null>(null);
const sidebarCloseButton = ref<HTMLButtonElement | null>(null);
const panelCloseButton = ref<HTMLButtonElement | null>(null);
const artifactToggleButton = ref<HTMLButtonElement | null>(null);
let panelReturnFocus: HTMLElement | null = null;
const panelTab = ref<'papers' | 'analysis' | 'report'>('papers');
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
// 从某轮回复打开报告时固定该轮的报告版本；切换运行或关闭面板后回到最新报告。
const pinnedReport = ref<{ runId: string; reportId: string } | null>(null);
const reportKey = computed(() => pinnedReport.value?.runId === selectedRunId.value ? pinnedReport.value.reportId : '');
const artifactKey = computed(() => `${selectedRunId.value}|${reportKey.value}`);
const artifact = computed(() => artifacts[artifactKey.value]);
const artifactLoading = ref(false);
const artifactError = ref('');
const paperSelection = ref<{ runId: string; paperId: string; evidenceId?: string } | null>(null);
const paperDetail = ref<PaperDetail | null>(null);
const selectedCitation = ref<ChatCitation | null>(null);
const paperLoading = ref(false);
const paperError = ref('');
type LogEntry = { kind: 'event'; id: string; event: RunEvent } | { kind: 'reader'; id: string; paperId: string; title: string; status: string; events: RunEvent[] };
type LogItem = { id: string; time: string; title: string; detail: string; entries: LogEntry[]; failures: number; fromUser: boolean };
// final 表示读取时该轮已结束，记录不会再增加，展开时不再重复请求。
interface TurnProcess { open: boolean; loaded: boolean; loading: boolean; final: boolean; error: string; items: LogItem[]; }
const EMPTY_PROCESS: TurnProcess = { open: false, loaded: false, loading: false, final: false, error: '', items: [] };
// 每条助手回复各自保存展开状态与已读记录；轮询刷新不改变读者已展开的回复。
const processes = reactive<Record<string, TurnProcess>>({});
// 渲染期只读取，不在这里创建条目，避免在 patch 过程中修改响应式状态。
function processState(messageId: string): TurnProcess { return processes[messageId] || EMPTY_PROCESS; }
function writableProcess(messageId: string): TurnProcess {
  return processes[messageId] || (processes[messageId] = { ...EMPTY_PROCESS, items: [] });
}
// 模型的每次思考开启一步，之后的操作归到这一步下；阅读子 agent 的记录再按论文归组，同一篇论文再次委派时另起一组。
function logItem(event: RunEvent, fromUser = false): LogItem {
  const text = event.message.trim();
  const title = text.split('\n')[0];
  return { id: event.id, time: event.created_at, title, detail: title === text ? '' : text, entries: [], failures: 0, fromUser };
}
function logItems(events: RunEvent[]): LogItem[] {
  const items: LogItem[] = [];
  let step: LogItem | null = null;
  let open = new Map<string, Extract<LogEntry, { kind: 'reader' }>>();
  for (const event of events) {
    if (event.category === 'message') { items.push(logItem(event, true)); step = null; continue; }
    const paperId = event.actor?.startsWith('reader:') ? event.actor.slice('reader:'.length) : '';
    if (!step || (event.category === 'thought' && !paperId)) {
      step = logItem(event);
      items.push(step);
      open = new Map();
      if (!paperId) continue;
    }
    if (event.category === 'tool_error' || event.category === 'error') step.failures += 1;
    if (!paperId) { step.entries.push({ kind: 'event', id: event.id, event }); continue; }
    let group = open.get(paperId);
    if (!group) {
      group = { kind: 'reader', id: event.id, paperId, title: event.message.match(/开始阅读「(.+)」/)?.[1] ?? paperId, status: '', events: [] };
      open.set(paperId, group);
      step.entries.push(group);
    }
    group.events.push(event);
    if (event.category === 'reader' && group.events.length > 1) {
      group.status = event.message.match(/」(完成|未完成|失败)：/)?.[1] ?? '';
      open.delete(paperId);
    }
  }
  return items;
}
function stepMeta(item: LogItem) {
  const count = item.entries.reduce((total, entry) => total + (entry.kind === 'reader' ? 0 : 1), 0);
  const readers = item.entries.length - count;
  return [readers ? `${readers} 篇论文` : '', count ? `${count} 项操作` : '', item.failures ? `${item.failures} 处失败` : ''].filter(Boolean).join('，');
}
const downloadBusy = ref(false);
const downloadError = ref('');
let disposed = false;
let viewVersion = 0;
let pollVersion = 0;
let artifactVersion = 0;
let paperVersion = 0;
const processVersions = new Map<string, number>();
const processControllers = new Map<string, AbortController>();
let historyVersion = 0;
let historyWriteVersion = 0;
const writeVersions: Record<string, number> = {};
let pollTimer: ReturnType<typeof setTimeout> | null = null;
let pollController: AbortController | null = null;
let artifactController: AbortController | null = null;
let paperController: AbortController | null = null;
let historyController: AbortController | null = null;
let sendController: AbortController | null = null;
let stopController: AbortController | null = null;
let downloadController: AbortController | null = null;
const pageController = new AbortController();
const errorText = (error: unknown) => error instanceof Error ? error.message : '未知错误，请查看服务端记录';
const formatTime = (value: string) => new Date(value).toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
const shortDate = (value: string) => new Date(value).toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
const clockTime = (value: string) => new Date(value).toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit', second: '2-digit' });
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
function openSidebar() {
  if (compactLayout.value) sidebarOpen.value = true;
  else {
    sidebarCollapsed.value = false;
    void nextTick(() => sidebarCloseButton.value?.focus());
  }
}
function closeSidebar() {
  if (compactLayout.value) sidebarOpen.value = false;
  else sidebarCollapsed.value = true;
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
function runNumber(id: string) { return legacyOrder.value.indexOf(id) + 1; }
function trackScroll() { const element = timelineElement.value; if (element) nearBottom.value = element.scrollHeight - element.scrollTop - element.clientHeight < 110; }
function scrollToBottom() { const element = timelineElement.value; if (element) { element.scrollTop = element.scrollHeight; nearBottom.value = true; } }
async function scrollIfNeeded(shouldScroll: boolean, previousHeight: number | undefined) {
  const version = viewVersion; const key = selectedKey.value; await nextTick();
  if (version !== viewVersion || key !== selectedKey.value) return;
  const heightChanged = timelineElement.value?.scrollHeight !== previousHeight;
  if (preferences.autoScroll && shouldScroll && nearBottom.value && heightChanged) scrollToBottom();
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
function upsertTask(task: Task) {
  if (trashedIds.has(task.id)) return;
  const index = tasks.value.findIndex(item => item.id === task.id);
  if (index >= 0) tasks.value[index] = task;
  else tasks.value.push(task);
  tasks.value.sort((a, b) => b.updated_at.localeCompare(a.updated_at));
  historyWriteVersion++;
}
function applyConversation(data: ConversationView, shouldScroll: boolean) {
  if (trashedIds.has(data.task.id)) return;
  const previousHeight = timelineElement.value?.scrollHeight;
  views[data.task.id] = data;
  upsertTask(data.task);
  if (selectedKey.value === data.task.id) void scrollIfNeeded(shouldScroll, previousHeight);
}
function stopPolling() { pollVersion++; if (pollTimer !== null) clearTimeout(pollTimer); pollTimer = null; pollController?.abort(); pollController = null; }
function abortMaterials() { artifactVersion++; artifactController?.abort(); artifactLoading.value = false; abortProcesses(); downloadController?.abort(); downloadBusy.value = false; clearPaper(); }
function abortProcesses() {
  for (const [messageId, controller] of processControllers) { processVersions.set(messageId, (processVersions.get(messageId) || 0) + 1); controller.abort(); }
  processControllers.clear();
  for (const state of Object.values(processes)) state.loading = false;
}
function beginView() { closeMenus(); viewVersion++; stopPolling(); sendController?.abort(); stopController?.abort(); stopBusy.value = false; abortMaterials(); conversationLoading.value = false; conversationError.value = ''; artifactError.value = ''; downloadError.value = ''; for (const key of Object.keys(processes)) delete processes[key]; pinnedReport.value = null; panelOpen.value = false; sidebarOpen.value = false; }
function newConversation() { historyQuery.value = ''; beginView(); selectedKey.value = NEW_CHAT; nearBottom.value = true; void nextTick(() => { scrollToBottom(); inputElement.value?.focus(); }); }
function selectConversation(taskId: string, acknowledged?: ConversationView) {
  const fromSidebar = compactLayout.value && sidebarOpen.value;
  beginView(); selectedKey.value = taskId; nearBottom.value = true;
  if (acknowledged) { applyConversation(acknowledged, true); schedulePolling(); } else void pollConversation();
  void nextTick(() => { scrollToBottom(); if (fromSidebar && selectedKey.value === taskId) inputElement.value?.focus(); });
}
function schedulePolling() { const data = conversation.value; if (!data || disposed || stopBusy.value || currentPending.value?.busy || conversationError.value) return; if (data.busy) { const version = pollVersion; if (pollTimer !== null) clearTimeout(pollTimer); pollTimer = setTimeout(() => { pollTimer = null; if (version === pollVersion) void pollConversation(); }, 1400); } }
async function pollConversation() {
  const key = selectedKey.value; if (key === NEW_CHAT || stopBusy.value || currentPending.value?.busy || pollController) return;
  const version = viewVersion; const cycle = pollVersion; const write = writeVersions[key] || 0;
  const controller = new AbortController(); pollController = controller; conversationLoading.value = !views[key];
  const active = () => !disposed && version === viewVersion && cycle === pollVersion && selectedKey.value === key && write === (writeVersions[key] || 0) && !controller.signal.aborted;
  try { const data = await getConversation(key, controller.signal); if (!active()) return; applyConversation(data, nearBottom.value); conversationError.value = ''; if (panelOpen.value) await loadArtifacts(); await refreshOpenProcesses(); }
  catch (error) { if (active()) conversationError.value = `读取对话失败：${errorText(error)}`; }
  finally { if (active()) { conversationLoading.value = false; pollController = null; schedulePolling(); } }
}
function retryConversation() { if (stopBusy.value || currentPending.value?.busy) return; stopPolling(); conversationError.value = ''; void pollConversation(); }
const HISTORY_PAGE = 50;
const historyMore = ref(false);
// 分页按查询分别计数；搜索结果并入本地列表，侧栏仍按关键词在本地筛选显示。
let historySearch = '';
let historyOffset = 0;
let historyQueryTimer: number | undefined;
function mergeTasks(data: Task[]) {
  const byId = new Map(data.map(task => [task.id, task]));
  for (const task of tasks.value) { const item = byId.get(task.id); if (!item || item.updated_at <= task.updated_at) byId.set(task.id, task); }
  tasks.value = [...byId.values()].sort((a, b) => b.updated_at.localeCompare(a.updated_at));
}
function refreshHistory() { return loadHistory(false); }
function loadMoreHistory() { if (historyMore.value && !historyLoading.value) void loadHistory(true); }
function onHistoryScroll(event: Event) { const element = event.target as HTMLElement; if (element.scrollHeight - element.scrollTop - element.clientHeight < 80) loadMoreHistory(); }
watch(historyQuery, () => { window.clearTimeout(historyQueryTimer); historyLoading.value = true; historyQueryTimer = window.setTimeout(() => void loadHistory(false), 250); });
async function loadHistory(more: boolean) {
  historyController?.abort(); const controller = new AbortController(); historyController = controller;
  const version = ++historyVersion; const write = historyWriteVersion; historyLoading.value = true; historyError.value = '';
  const query = more ? historySearch : historyQuery.value.trim(); const offset = more ? historyOffset : 0;
  try { const received = await getConversations({ query, offset, limit: HISTORY_PAGE }, controller.signal); const data = received.filter(task => !trashedIds.has(task.id)); if (disposed || version !== historyVersion) return; if (!more && !query && write === historyWriteVersion) tasks.value = data; else mergeTasks(data); historySearch = query; historyOffset = offset + received.length; historyMore.value = received.length === HISTORY_PAGE; historyLoaded.value = true; }
  catch (error) { if (!disposed && version === historyVersion && !controller.signal.aborted) historyError.value = `读取记录失败：${errorText(error)}`; }
  finally { if (!disposed && version === historyVersion) historyLoading.value = false; }
}
async function sendDraft() {
  if (!canSend.value) return; const key = selectedKey.value; const content = draft.value.trim();
  if (Array.from(content).length > inputLimit.value) { sendErrors[key] = `消息不能超过 ${inputLimit.value} 字符。`; return; }
  pending[key] = { request_id: crypto.randomUUID(), content, mode: currentMode.value, snapshot: draft.value, fromDraft: true, busy: false, error: '' }; await transmit(key);
}
async function stopWork() {
  const key = selectedKey.value;
  if (!conversation.value || currentPending.value || stopBusy.value) return;
  const view = viewVersion; stopPolling();
  const write = (writeVersions[key] || 0) + 1; writeVersions[key] = write;
  const controller = new AbortController(); stopController = controller; stopBusy.value = true; sendErrors[key] = '';
  const active = () => !disposed && view === viewVersion && key === selectedKey.value && write === writeVersions[key] && !controller.signal.aborted;
  try { const data = await stopConversation(key, controller.signal); if (active()) { applyConversation(data, nearBottom.value); conversationError.value = ''; if (panelOpen.value) void loadArtifacts(); void refreshOpenProcesses(); } }
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
    else request.error = controller.signal.aborted ? '已切换对话，发送结果未确认，可重试原消息。' : `${errorText(error)}。服务可能已接收，可重试原消息。`;
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
let actionReturnFocus: HTMLElement | null = null;
function openConversationAction(kind: 'rename' | 'trash', task: Task) { actionReturnFocus = (document.activeElement as HTMLElement | null)?.closest('details')?.querySelector('summary') || null; closeMenus(); conversationActionError.value = ''; conversationAction.value = { kind, task }; }
function closeConversationAction() {
  conversationAction.value = null;
  void nextTick(() => { const target = actionReturnFocus?.isConnected && actionReturnFocus.getClientRects().length ? actionReturnFocus : inputElement.value; target?.focus(); actionReturnFocus = null; });
}
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
    if (conversationAction.value === action) closeConversationAction();
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
    setNotice('对话已恢复');
  } catch (error) { if (!disposed) setNotice(`恢复失败：${errorText(error)}`, true); }
  finally { conversationActionBusy.value = false; }
}
async function copyMessage(content: string) {
  try { await navigator.clipboard.writeText(content); setNotice('回复已复制'); }
  catch { setNotice('无法访问剪贴板，请选择回复文本后复制', true); }
}
function clearPaper() { paperVersion++; paperController?.abort(); paperSelection.value = null; paperDetail.value = null; selectedCitation.value = null; paperError.value = ''; paperLoading.value = false; }
function closePanel() { panelOpen.value = false; pinnedReport.value = null; artifactVersion++; artifactController?.abort(); artifactLoading.value = false; downloadController?.abort(); downloadBusy.value = false; clearPaper(); void nextTick(() => panelReturnFocus?.focus()); }
function togglePanel() { if (panelOpen.value) closePanel(); else { if (!selectedRuns[selectedKey.value] && latestRun.value) selectedRuns[selectedKey.value] = latestRun.value.id; panelOpen.value = true; void loadArtifacts(); } }
function chooseRun(runId: string) { selectedRuns[selectedKey.value] = runId; pinnedReport.value = null; if (runMenu.value) runMenu.value.open = false; downloadController?.abort(); downloadBusy.value = false; clearPaper(); artifactError.value = ''; downloadError.value = ''; void loadArtifacts(); }
function openRun(runId: string) { panelOpen.value = true; panelTab.value = 'papers'; chooseRun(runId); }
function openReport(work: AgentWork) {
  selectedRuns[selectedKey.value] = work.run_id; pinnedReport.value = { runId: work.run_id, reportId: work.report_id! };
  downloadController?.abort(); downloadBusy.value = false; clearPaper(); artifactError.value = ''; downloadError.value = '';
  panelOpen.value = true; panelTab.value = 'report'; void loadArtifacts();
}
function openPaper(paperId: string, evidenceId?: string) { clearPaper(); panelTab.value = 'papers'; paperSelection.value = { runId: selectedRunId.value, paperId, evidenceId }; void loadPaper(); }
function openReportEvidence(id: string) { const evidence = artifact.value?.report?.document?.evidence.find(item => item.id === id); if (evidence) openPaper(evidence.paper_id, id); }
function openCitation(citation: ChatCitation) { downloadController?.abort(); downloadBusy.value = false; downloadError.value = ''; panelOpen.value = true; panelTab.value = 'papers'; selectedRuns[selectedKey.value] = citation.run_id; pinnedReport.value = null; clearPaper(); selectedCitation.value = citation; paperSelection.value = { runId: citation.run_id, paperId: citation.paper_id }; void loadArtifacts(); void loadPaper(); }
async function loadArtifacts() {
  if (!panelOpen.value || !selectedRunId.value) return;
  artifactController?.abort(); const controller = new AbortController(); artifactController = controller;
  const version = ++artifactVersion; const view = viewVersion; const runId = selectedRunId.value; const reportId = reportKey.value || null; const key = artifactKey.value; const run = selectedRun.value;
  const active = () => !disposed && view === viewVersion && version === artifactVersion && panelOpen.value && key === artifactKey.value && !controller.signal.aborted;
  artifactLoading.value = !artifacts[key]?.loaded;
  try {
    const [paperResult, reportResult] = await Promise.allSettled([getPapers(runId, controller.signal), getReport(runId, reportId, controller.signal)]); if (!active()) return;
    const data = artifacts[key] || { papers: [], report: null, reportNotice: '', loaded: false }; const errors: string[] = [];
    if (paperResult.status === 'fulfilled') { data.papers = paperResult.value; data.loaded = true; } else errors.push(`读取文献失败：${errorText(paperResult.reason)}`);
    if (reportResult.status === 'fulfilled') data.report = reportResult.value;
    else if (reportResult.reason instanceof ApiError && reportResult.reason.status === 409) { data.report = null; data.reportNotice = run?.agent ? '本对话还没有报告。' : `本次运行尚无可交付报告（${run ? runLabels[run.status] : '当前状态未知'}）。`; }
    else errors.push(`读取报告失败：${errorText(reportResult.reason)}`);
    artifacts[key] = data; artifactError.value = errors.join('；');
  } finally { if (active()) artifactLoading.value = false; }
}
async function loadPaper() {
  const selection = paperSelection.value; if (!selection) return;
  paperController?.abort(); const controller = new AbortController(); paperController = controller;
  const version = ++paperVersion; const view = viewVersion;
  const active = () => !disposed && view === viewVersion && version === paperVersion && !controller.signal.aborted;
  paperLoading.value = true; paperError.value = '';
  try {
    const data = await getPaperDetail(selection.runId, selection.paperId, controller.signal);
    if (active()) {
      paperDetail.value = data;
      const evidence = data.evidence.find(item => item.id === selection.evidenceId);
      const source = data.sources.find(item => item.id === evidence?.source_text_id);
      if (evidence && source) selectedCitation.value = { ...evidence, run_id: selection.runId, source_type: source.source_type, source_url: source.source_url };
    }
  }
  catch (error) { if (active()) paperError.value = `读取论文详情失败：${errorText(error)}`; }
  finally { if (active()) paperLoading.value = false; }
}
function onProcessToggle(messageId: string, event: Event) {
  const state = writableProcess(messageId);
  state.open = (event.target as HTMLDetailsElement).open;
  if (state.open) { if (!state.final) void loadProcess(messageId); }
  else { processVersions.set(messageId, (processVersions.get(messageId) || 0) + 1); processControllers.get(messageId)?.abort(); processControllers.delete(messageId); state.loading = false; }
}
// 轮询后刷新已展开且仍在进行的记录，不改变折叠状态。已读过一次的记录在后台刷新时
// 不显示占位段落，因此不会改变时间线高度或读者的滚动位置。
async function refreshOpenProcesses() {
  await Promise.all(Object.keys(processes).filter(id => processes[id].open && !processes[id].final).map(id => loadProcess(id)));
}
async function loadProcess(messageId: string) {
  const state = writableProcess(messageId);
  // 执行中连发消息并入时，尚未开始的回复会失去工作记录。
  const message = conversation.value?.messages.find(item => item.id === messageId);
  if (!state.open || !message?.work) return;
  const runId = message.work.run_id; const final = !['queued', 'processing'].includes(message.status);
  processControllers.get(messageId)?.abort();
  const controller = new AbortController(); processControllers.set(messageId, controller);
  const version = (processVersions.get(messageId) || 0) + 1; processVersions.set(messageId, version);
  const view = viewVersion;
  const active = () => !disposed && view === viewVersion && version === processVersions.get(messageId) && !controller.signal.aborted;
  state.loading = !state.loaded;
  try {
    const data = await getRunEvents(runId, messageId, controller.signal);
    if (active()) {
      const previousHeight = timelineElement.value?.scrollHeight;
      const shouldScroll = nearBottom.value;
      state.items = logItems(data); state.loaded = true; state.final = final; state.error = ''; state.loading = false;
      void scrollIfNeeded(shouldScroll, previousHeight);
    }
  }
  catch (error) { if (active()) state.error = `读取过程失败：${errorText(error)}`; }
  finally { if (active()) { state.loading = false; if (processControllers.get(messageId) === controller) processControllers.delete(messageId); } }
}
async function downloadReport(format: 'md' | 'docx' | 'pdf') {
  if (downloadBusy.value || !selectedRunId.value || !artifact.value?.report) return;
  const runId = selectedRunId.value; const reportId = artifact.value.report.id; const view = viewVersion;
  const controller = new AbortController(); downloadController = controller; downloadBusy.value = true; downloadError.value = '';
  const active = () => !disposed && view === viewVersion && runId === selectedRunId.value && !controller.signal.aborted;
  try { const blob = await getReportFile(runId, reportId, format, controller.signal); if (!active()) return; const url = URL.createObjectURL(blob); const link = document.createElement('a'); link.href = url; link.download = `paper-scout-${reportId}.${format}`; link.click(); URL.revokeObjectURL(url); }
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
  clockTimer = setInterval(() => { if (conversation.value?.messages.some(message => message.status === 'processing' && message.work)) clock.value = Date.now(); }, 1000);
});
onUnmounted(() => {
  window.removeEventListener('resize', resizeInput);
  compactQuery.removeEventListener('change', onLayoutChange);
  document.removeEventListener('keydown', handleOverlayKey);
  disposed = true; if (clockTimer !== null) clearInterval(clockTimer); window.clearTimeout(noticeTimer); window.clearTimeout(historyQueryTimer); stopPolling(); abortMaterials(); sendController?.abort(); stopController?.abort(); historyController?.abort(); pageController.abort();
});
</script>
<style src="./workspace.css"></style>
