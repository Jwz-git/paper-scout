# 数据与接口

状态：说明当前实际实现的会话、AI 服务、研究分析与报告接口。时间统一保存 UTC，界面按用户本地时间显示；标识由系统生成，外部来源 ID 原样保留。

## 实际会话接口

- `GET /api/conversations`：未删除会话，按更新时间倒序。`offset>=0`、`limit=1..100`（默认100）分页；`query` 按名称／问题做不区分大小写的字面子串搜索（最长2000字符）；`deleted=true` 查询回收站。按偏移分页，翻页期间有会话更新时可能出现个别重复或遗漏。
- `POST /api/conversations/{task_id}/rename`：提交 `title`（去空白后1–120字符），只改显示名称，不改研究问题或原始运行范围。
- `POST /api/conversations/{task_id}/trash`：在同一事务中停止该会话的排队和处理中消息并标记删除；保留消息、来源、报告及用量，可重复调用。
- `POST /api/conversations/{task_id}/restore`：恢复列表可见性，不恢复已停止的执行。回收站中的会话不允许继续发送消息；首条消息旧请求标识的重发也不能复活已删除会话。
- `GET /api/conversations/trash`：独立回收站列表；`query` 按名称／问题做字面子串搜索（最长2000字符），`sort=newest/oldest/title`，`offset>=0`，`limit=1..100`（默认50）。返回 `{items,total,matched}`，分别为当前页、回收站总数、筛选后总数；`deleted_at` 用于展示删除时间。
- `POST /api/conversations/trash/restore`：`{ids:[...]}` 恢复指定1–100个回收站会话，`{ids:null}` 恢复整个回收站；返回 `{tasks:[...]}`。不重启已停止的工作，不受列表分页或搜索条件限制。
- `POST /api/conversations/trash/delete`：选择体同上，返回 `{ids:[...]}`。仅允许彻底删除回收站中的会话；移除消息、对话用量、轮次幂等记录、工作区和旧运行及其报告／事件／查询／评估等关联记录。无其他运行引用的来源／证据和无其他关联的论文一并清理，共用来源保留。目标会话仍由串行 worker 处理时返回409，避免在途结果写入已删除对象。
- 批量恢复／删除在同一数据库事务内完成：明确指定的任一会话已恢复或不存在，整体返回409，不部分执行；空数组／未提交 `ids` 返回422。全量操作必须明确提交 `null`，空回收站返回空结果。界面彻底删除及全量恢复需确认，支持关闭窗口，已提交操作继续并反馈结果。
- `POST /api/conversations`：提交首条自然语言消息，创建会话并排队，返回 `202`。
- `GET /api/conversations/{task_id}`：任务、真实消息、所有运行、对话用量、busy 和模型是否配置。
- `POST /api/conversations/{task_id}/messages`：追加并排队消息，返回 `202`。执行中也可发送，agent 在下一次模型调用前并入（见 [对话 agent](<04-agent-workflow.md>) 的“执行中插话”）。`mode` 为 `auto`（默认）、`research`（提示用户要求开展调研）或 `ask`（只用已保存资料，拒绝检索和新的全文下载）。
- `POST /api/conversations/{task_id}/stop`：停止当前工作，返回 `200` 会话视图；无需模型或请求体。该会话所有排队和处理中的消息标为 `interrupted`，助手消息显示“已停止。”，正在进行的模型或外部请求被取消。即使尚无工作区也可停止；迟到的模型结果不能改写已停止的消息，重复停止无新增副作用。

提交包含 `content` 和 `request_id`。同一请求标识及内容重发返回已保存会话，不重复执行；同一标识对应不同内容或模式返回 `409`。首条文本最多2000字符，后续最多4000字符；接口本身不发起外部服务调用。

`ChatMessage` 保存角色、文本、状态（queued、processing、completed、failed、interrupted）、所属 Run、时间、错误类别、引用和本轮工作状态 `work`。`action` 只出现在旧版消息中。`ChatCitation` 保存运行／论文／快照／证据标识、读取类型、来源链接、页码、原文及字符区间。原文匹配不等于语义支持核验。

`AgentWork` 在执行中持续保存，供界面轮询显示：`run_id`、当前动作 `activity`、步数 `steps`、外部调用 `calls`（其中模型调用 `model_calls`）、执行秒数 `seconds`、最近进展时间 `progress_at`、计划清单 `todos`（`text` 与 `pending/in_progress/done`）、已启动的阅读子 agent 数 `subagents`、本轮生成的 `report_id`、终止原因 `stop_reason`、是否转到后续消息继续 `continued`，以及本轮上限 `limits`。

消息失败不会伪造助手回答或回滚用户消息。旧任务和旧运行保留，不把旧研究输入伪造成新助手发言。`busy` 表示该会话有排队或处理中的消息。

### 会话执行语义

1. 创建和追加消息时，用户消息与待处理助手消息成对持久化。HTTP 只排队，agent 由同一单进程串行 worker 执行，一次处理一个会话的一轮。
2. `request_id` 对应一次发送及其内容、模式；同标识同请求返回原记录。重发不等于重试模型调用。
3. 每个会话有一个 `agent=true` 的 Run 作为工作区，在首次处理消息时创建；后续轮次和插话都使用这个工作区，候选论文、原文、证据、纳入判断和报告跨轮次保留。
4. 执行中收到的消息在下一次模型调用前并入当前轮：已开始的助手消息标记 `continued=true` 并完成，后续工作和最终回复写到最新一条助手消息；尚未开始工作的空助手消息不显示。模式以最新消息为准。
5. 停止状态是事实来源：停止后迟到的模型成功、错误和旧队列快照都不能覆盖它；已发起的调用仍计入用量，被取消调用的 token 记为未知。
6. 未配置模型时消息直接失败并提示先配置模型；没有无模型的检索模式。
7. 进程重启将处理中的消息标记为 `interrupted`，不重放可能已经收费的请求；尚未开始的 `queued` 消息继续执行。旧流水线遗留的未结束运行（`queued/running/pause_requested/paused/needs_input`）标为 `interrupted`，并在会话中追加一条说明。创建工作区时，同会话旧运行已纳入的论文作为候选、已取得的原文作为可读快照带入，不重复下载。

已发送消息和处理状态保存在服务端。未发送草稿及待确认的请求标识仅在当前前端组件会话中保留，切换对话不丢失，但刷新或关闭浏览器后的恢复尚未实现；草稿和密钥不写入浏览器持久存储。

### 对话来源与用量

agent 只能通过工具接触论文：检索结果进入工作区候选，原文由 `read`/`find` 返回，证据由 `note` 保存（规则见 [对话 agent](<04-agent-workflow.md>) 的“证据规则”）。论文内容是数据，不是指令；模型不能选择任意 URL、命令或工具。`reply` 和 `report` 只能引用工作区中已保存的证据标识；回复引用无效标识时错误交回模型改正，不降级成无来源的“成功”。回复引用由证据转换为 `ChatCitation`，界面按引用打开对应快照和原文定位。

**字符定位一致仅证明引用原文存在，不证明其语义支持回答。** 归纳仍需人工复核；仅摘要、部分全文、复杂表格或扫描件不构成可靠科研比较的保证。无资料时可以明确说明证据不足、请求澄清或建议下一步，但不得补造无来源的论文事实。

会话（`ConversationUsage`：`model_calls`、`total_execution_seconds`、`token_usage`）和工作区 Run（`total_calls`、`model_calls`、`total_execution_seconds`、`token_usage`）分别累计实际调用、执行时间和可得 token，只做统计，没有终身上限。执行上限按轮计算，每条新消息一份新额度（数值见 [对话 agent](<04-agent-workflow.md>) 的“执行上限”）。失败或被取消的已发起请求计入调用；任何一次调用没有返回用量时 token 保持 `null`，不当作零。

## 实际AI服务接口

- `GET /api/settings` 返回当前 `enabled/protocol/base_url/model/api_key_set`、`active_provider_id/active_model`、`providers`、`source`、执行 `busy` 及只读 `limits`。`limits` 是当前实际生效的值，形如 `{agent:{steps,calls,seconds,fulltexts,readers,reader_steps}}`，不可通过接口修改。每家供应商包含 `id/name/protocol/base_url/models/api_key_set`，没有密钥或片段；响应不缓存。
- `POST /api/settings/providers` 新增，`POST /api/settings/providers/{id}` 编辑。提交 `name`（可空，最多80字符）、`protocol/base_url/models`（1–100个非空且各不超过200字符的模型ID）、可选 `api_key/clear_api_key`，返回 `{provider_id,settings}`。同一家供应商以一笔原子保存更新连接信息与完整模型清单；不会自动选择型号。修改当前供应商要求全局空闲，其他供应商可编辑。
- `POST /api/settings/models`：提交 `provider_id`（新供应商null）、`protocol/base_url`、可选 `api_key/clear_api_key/cursor`。使用本次凭据或该供应商已有凭据读取外部 `/models`，返回 `{models:[{id,name}],next_cursor}`。Anthropic分页100项，通过 `cursor` 请求下一页；OpenAI返回列表。不保存配置，不发起生成请求，不修改会话用量。HTTP请求各阶段15秒超时，不重试、不跟随重定向。鉴权失败400、限流429、超时504、其他服务／响应格式错误502，不回传供应商原始错误正文。
- `POST /api/settings/selection`：输入 `provider_id/model`，只能选择该供应商已保存的型号；同步更新对话与研究适配器，要求全局空闲，不发起模型调用。此操作仅从对话输入区发起。
- `POST /api/settings/providers/{id}/delete`：删除该供应商的连接信息、单份凭据与模型清单；删除当前供应商要求空闲，清空当前选择。历史会话和资料保留。
- 当前供应商编辑时如果移除正在使用的型号，清空当前选择，用户需在对话中重新选择；不自动切换到其他型号。
- 已发布的 `POST /api/settings` 单模型入口保留，更新当前供应商及所选型号；前端不使用此入口。

密钥省略／null只保留同一供应商已有密钥，非空值替换，`clear_api_key=true`清除，两者不能同时指定新值。新供应商不继承其他凭据。更改地址且有旧密钥时必须重新输入或明确清除。地址为HTTP(S) API前缀，不能带URL凭据、查询或片段；输入校验与外部失败不回显密钥。

`409` 表示尝试影响当前供应商／型号时仍有排队、执行或取消后未结束的请求；`422`为无效配置／选择不属于供应商的型号；`404`为供应商不存在；保存的`500`为本机写入失败，原文件与运行适配器保持不变。

本机文件保存在 `DATA_DIR/model-settings.json`，权限600，包含 `enabled/active_provider_id/active_model/providers`，旧文件中从未生效的 `limits` 读取时丢弃，每家供应商仅一份明文密钥。临时文件加原子替换提交，重启恢复。本机文件优先于环境配置，损坏时明确失败。旧单模型／profiles文件只对已知格式迁移；旧profiles按协议、地址和实际密钥相同才合并，保留当前型号和不同凭据，读取不改文件，首次保存再写入供应商结构。

当前模型为本机全局选择，影响后续对话与研究调用；不是每会话独立绑定或并行路由。已有来源、运行初始范围和累计用量不改写，尚无每次历史调用的配置快照。

## 实际研究分析与报告接口

- `GET /api/runs/{run_id}/papers/{paper_id}` 保留该运行内历史来源访问，`paper_id` 可含斜杠（如旧式 arXiv 编号 `hep-th/9901001`），返回 `paper/sources/evidence/analysis/selection/selected/analysis_revision`；`selected=false` 的旧资料不冒充当前纳入成果。
- `GET /api/runs/{run_id}/analysis?revision=N` 返回指定修订的论文元数据、筛选、最新逐篇分析和最近评估；省略 `revision` 读取当前修订。不存在的历史修订返回404。
- `GET /api/runs/{run_id}/report?report_id=ID` 返回指定报告快照；省略 ID 读取最新。运行不存在404、尚无报告409、指定版本不属于运行404。
- `GET /api/runs/{run_id}/report.md|report.docx|report.pdf?report_id=ID` 导出指定快照。下载仅本地渲染，不改变研究状态/用量或调用模型。没有结构化快照的历史报告仍可下载 Markdown，Word/PDF 返回明确409。

`PaperAnalysis` 以不可变 JSON 记录保存字段、实验、范围修订、实际输入区间、状态、错误类别和可选的复用来源；新增结果不覆盖旧记录。`Extraction` 的事实值关联证据；缺失为null加 `MissingReason`，空字符串或没有证据的非空字段不能通过模型入口。`origin=author/inference/user` 分别表示作者自述、系统推断和用户要求，不能将用户要求当作论文事实。

`ReadRange` 保存快照 ID、类型、页码、全局 `[start,end)` 与原文本长度，记录实际返回给模型的范围（摘要、读过的页、`find` 窗口）；下载或解析成功的全文不等于已读。agent 的 `note` 只提交 `source_text_id/quote`，不要求模型计算字符位置；代码在该来源中定位摘录，比较时忽略空白、连字符和 Unicode 兼容形式差异（PDF 换行与断词），保存的 Evidence 是原文中实际对应的那一段，数据库再核对 `content[start:end]==quote`。摘录过短、找不到、多处匹配无法唯一定位、来源不属于该论文或位置不在已读范围内时，这条引文被拒绝并附原因返回模型，不取第一个近似结果。持久化及对外 Evidence 区间使用 Python Unicode 字符索引，与前端 `Array.from()` 对齐，既有证据和报告不迁移或重算。`not_found` 仅指已读范围，不宣称整篇论文未报告。

`PaperSelection` 保存范围修订、是否纳入和理由。agent 通过 `decide` 写入，以最后一次判断为准；报告引用了尚未判断的论文时自动纳入，理由记为“报告引用了这篇论文的证据”；没有判断记录的论文只是候选。DOI 与同来源标识用于逻辑同作分组，arXiv 版本独立保存；标题作者相似只记录疑似关系，不删除论文或混合版本事实。

旧流水线保存的筛选（含 `reviewed`、子问题、依据）、逐篇分析和评估按原结构读取展示，不迁移或重算。

`Experiment` 保留数据集/版本、划分、指标/值/单位/方向、评价协议与计算条件的原文信息及证据。`Comparison` 区分 `comparable/not_comparable/insufficient`；未知条件不自动视作相同，不隐式单位换算或生成总体排名。

`Assessment` 保存规则版本、支持论文组、字段分子/分母、比较、缺口及下一动作。`Report.document` 固定当前范围、纳入资料、未纳入的已筛选论文（`excluded_papers`，用于在筛选记录中显示标题和链接）、字段、比较、综合主张、证据与执行统计；多格式渲染共用此结构。agent 的 `report` 工具在同一事务中保存报告与评估：字段覆盖、实验比较和“尚未阅读／未读取全文／全文只读了部分页”缺口由代码计算，章节与主张由模型给出并只能引用已保存证据。一个工作区可有多份报告，按 `report_id` 区分。

## 核心实体

| 实体 | 关键字段与约束 |
| --- | --- |
| Task | id、独立显示名称title、软删除时间deleted_at、研究问题、年份范围（含起止年）、关注维度、输出要求、创建和更新时间。 |
| Run | id、task_id、`agent`、初始输入快照、status、stage、累计用量、创建／开始／结束时间、终止原因。`agent=true` 为对话工作区，每个会话一个，状态固定为 `completed`，每轮的进度和终止原因记在助手消息的 `work` 中；`agent=false` 为旧流水线运行，只读保留。 |
| AIProvider | 名称、协议、服务地址、可用模型ID清单和服务端单份凭据；读取仅返回密钥是否保存。当前选择另存供应商ID和型号，不把每个型号拆成独立供应商。 |
| SearchQuery | run_id、轮次、查询、来源、筛选条件、时间、结果数量和错误类别。 |
| Paper | id、标题、作者、年份、DOI、来源 ID 和链接；各来源的原始记录和获取时间保留，缺失字段可空。 |
| RunPaper | run_id、paper_id、相关性说明、筛选状态与原因；同一论文可被多个任务使用。 |
| SourceText | id、paper_id、来源类型（metadata、abstract、fulltext）、来源链接、获取时间、读取／解析状态、实际读取页。全文每页文本保留独立定位。 |
| Evidence | id、source_text_id、页码（摘要为空）、原文片段及其在已保存文本中的位置。位置以该快照文本为准，不能推断 PDF 排版位置。 |
| Extraction | run_id、paper_id、字段名、值或空值、证据 ID 列表、缺失原因；事实与推断分开。 |
| Assessment | run_id、轮次、各子问题覆盖、字段完整率、缺口、规则结果和决定。 |
| Report | run_id、章节、带证据引用的主张、参考文献、缺口、终止原因和生成时间。 |
| Event | run_id、时间、事件类别及对用户有意义的简短说明；agent 事件另有 `turn_id`（对应助手消息）和 `actor`（`agent`、`user` 或 `reader:{paper_id}`），旧事件保留阶段。 |

论文版本和出版状态如数据源可提供则保存；预印本和正式版本不因标题近似自动合并。DOI 标准化后精确匹配；不同来源 ID 只能在同来源内精确匹配。标题相似只能标记疑似重复，不自动合并。

缺失原因至少区分 `not_available`、`not_read`、`not_found`、`parse_failed`、`not_applicable`；空值不是零。来源链接、文本快照、原文片段和页码相互关联，未能定位的主张不得标为有证据。对论文条目和证据保存必要快照；不得把链接现存状态或原文内容推断为永不变化。

## 运行状态

对话工作区 Run 不使用运行状态表达进度，固定为 `completed`；一轮工作的状态是助手消息的 `status`，终止原因是 `work.stop_reason`。

旧流水线运行保留原状态值：`queued`、`running`、`pause_requested`、`paused`、`needs_input`、`completed`、`partial`、`failed`、`cancelled`、`interrupted`，以及理解、规划、检索、筛选、提取、分析、评估、综合、报告等阶段。启动时未结束的旧运行标为 `interrupted`，不再继续、暂停或恢复；其报告、来源和事件仍可查看。

## 其他 HTTP 接口

前缀 `/api`，JSON 输入输出。会话与 AI 服务接口见上文；以下为任务与运行的底层接口，前端主要通过会话接口使用。

| 方法与路径 | 用途 |
| --- | --- |
| POST /tasks | 创建任务，返回任务；不自动调用外部服务。 |
| GET /tasks | 列出任务，`limit=1..100`（默认50）。 |
| GET /tasks/{task_id} | 获取任务。 |
| GET /tasks/{task_id}/runs | 获取任务的全部运行（含对话工作区和旧运行）。 |
| GET /runs/{run_id} | 查询运行与累计用量。 |
| GET /runs/{run_id}/events | 按时间顺序查看事件；可选 `turn_id` 只看某一轮。 |
| GET /runs/{run_id}/papers | 查看论文及读取状态。 |

论文详情、分析和报告接口见“实际研究分析与报告接口”。输入错误返回可读的 4xx；不存在返回 404；状态冲突返回 409。服务内部故障记录日志并返回不泄露密钥的错误信息。

外部服务错误类别：模型与 arXiv 的 HTTP 5xx 记为 `server_error`，与 `rate_limited`、`timeout`、`network_error` 同属暂时性错误，模型的内容过滤或拒绝（`refusal`）也按暂时性错误处理，按有限次数重试（见 [对话 agent](<04-agent-workflow.md>)）；PDF 解析子进程异常退出或解析库抛出意外错误记为 `parse_failed`。

## 报告约定

每条关键事实关联一条或多条 Evidence 和 Paper；参考文献包含可得的标题、作者、年份、DOI 或来源链接，缺失明示。报告依次展示：问题及范围、检索方法和限制、分类与比较、结果和条件、局限及缺口、参考文献。只有摘要时注明“基于摘要”；综合推断明确标识，不能呈现为论文原话。各导出格式与页面展示引用使用同一套数据。
