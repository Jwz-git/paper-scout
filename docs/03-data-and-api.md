# 数据与接口草案

状态：供实施讨论，不代表现有接口。时间统一保存 UTC，界面按用户本地时间显示；标识由系统生成，外部来源 ID 原样保留。

## 核心实体

| 实体 | 关键字段与约束 |
| --- | --- |
| Task | id、研究问题、年份范围（含起止年）、关注维度、输出要求、创建和更新时间。 |
| Run | id、task_id、初始输入快照、status、stage、执行限制配置及累计用量、创建／开始／结束时间、终止原因；暂停和继续保留同一 run_id 与计数。 |
| RunMessage | id、run_id、用户补充文本、时间、处理状态及其对计划的影响；按顺序追加，不修改原始输入。 |
| ModelProfile | 协议、服务地址、模型名和服务端凭据引用；读取配置不返回密钥。运行记录配置标识，不保存明文密钥。 |
| SearchQuery | run_id、轮次、查询、来源、筛选条件、时间、结果数量和错误类别。 |
| Paper | id、标题、作者、年份、DOI、来源 ID 和链接；各来源的原始记录和获取时间保留，缺失字段可空。 |
| RunPaper | run_id、paper_id、相关性说明、筛选状态与原因；同一论文可被多个任务使用。 |
| SourceText | id、paper_id、来源类型（metadata、abstract、fulltext）、来源链接、获取时间、读取／解析状态、实际读取页。全文每页文本保留独立定位。 |
| Evidence | id、source_text_id、页码（摘要为空）、原文片段及其在已保存文本中的位置。位置以该快照文本为准，不能推断 PDF 排版位置。 |
| Extraction | run_id、paper_id、字段名、值或空值、证据 ID 列表、缺失原因；事实与推断分开。 |
| Assessment | run_id、轮次、各子问题覆盖、字段完整率、缺口、规则结果和决定。 |
| Report | run_id、章节、带证据引用的主张、参考文献、缺口、终止原因和生成时间。 |
| Event | run_id、时间、阶段、事件类别及对用户有意义的简短说明。 |

论文版本和出版状态如数据源可提供则保存；预印本和正式版本不因标题近似自动合并。DOI 标准化后精确匹配；不同来源 ID 只能在同来源内精确匹配。标题相似只能标记疑似重复，不自动合并。

缺失原因至少区分 `not_available`、`not_read`、`not_found`、`parse_failed`、`not_applicable`；空值不是零。来源链接、文本快照、原文片段和页码相互关联，未能定位的主张不得标为有证据。对论文条目和证据保存必要快照；不得把链接现存状态或原文内容推断为永不变化。

## 运行状态

`queued`（排队）、`running`（执行）、`pause_requested`（等待当前请求结束）、`paused`（暂停）、`needs_input`（需要补充）、`completed`（满足条件并完成报告）、`partial`（受限但有可交付部分结果）、`failed`（无法形成可交付结果）、`cancelled`（用户取消）、`interrupted`（进程中断）。阶段单独记录：理解、规划、检索、解析、评估、综合和报告。

暂停请求在当前外部请求结束或超时后生效；不发起新的外部请求，并保存检查点。`paused` 和 `needs_input` 均可接收补充信息，用户显式继续后排队执行，保持 run_id、历史证据和累计用量。继续前重新检查补充信息对计划及已有论文相关性的影响，并记录处理结果；与新范围不再相关的结果保留历史但不纳入新报告。暂停等待时间不计入运行时限；实际执行时间和调用计数跨暂停累加。终态不可原地重启，重新尝试产生新 Run。取消保留已有数据；请求中的外部调用可能需要等待超时或返回。`partial` 必须包含缺口和终止原因；没有任何可供核查的成果时为 `failed`。

## HTTP 接口草案

前缀 `/api`，JSON 输入输出；列表分页参数与最终字段在实现时固定并生成接口文档。

| 方法与路径 | 用途 |
| --- | --- |
| POST /tasks | 创建任务，返回任务 ID；不自动调用外部服务。 |
| GET /tasks | 列出历史任务和最近运行状态。 |
| GET /tasks/{task_id} | 获取任务和历史运行。 |
| PATCH /tasks/{task_id} | 修改后续运行使用的任务输入，不改已有运行快照。 |
| POST /tasks/{task_id}/runs | 创建并排队新运行；同任务有活动运行时返回冲突。 |
| GET /runs/{run_id} | 查询状态、阶段、执行限制及用量、缺口与终止原因。 |
| POST /runs/{run_id}/pause | 请求暂停；已在途请求完成或超时后进入 paused。 |
| POST /runs/{run_id}/messages | 在 paused 或 needs_input 时追加补充信息，保留记录。 |
| POST /runs/{run_id}/resume | 从 paused 或 needs_input 继续同一运行；先处理待处理补充信息。 |
| POST /runs/{run_id}/cancel | 请求取消，返回当前状态；重复请求保持结果一致。 |
| GET /runs/{run_id}/events | 查看时间顺序事件与检索记录。 |
| GET /runs/{run_id}/papers | 查看筛选后的论文及读取状态。 |
| GET /runs/{run_id}/papers/{paper_id} | 查看结构化提取、缺失原因及证据定位。 |
| GET /runs/{run_id}/report | 获取报告结构与引用。报告尚不存在时明确返回状态。 |
| GET /runs/{run_id}/report.md | 导出 Markdown 报告。 |
| GET /runs/{run_id}/report.docx | 导出 Word 报告。 |
| GET /runs/{run_id}/report.pdf | 导出 PDF 报告。 |
| GET /model-profiles | 查看模型配置，不返回密钥。 |
| POST /model-profiles | 创建模型配置，包含协议、服务地址、模型及凭据。 |
| PATCH /model-profiles/{profile_id} | 修改模型配置；未提供凭据时保留已有凭据。 |

输入错误返回可读的 4xx；不存在返回 404；状态冲突返回 409。服务内部故障记录日志并返回不泄露密钥的错误信息。错误响应格式应一致，具体字段随实现确定。

## 报告约定

每条关键事实关联一条或多条 Evidence 和 Paper；参考文献包含可得的标题、作者、年份、DOI 或来源链接，缺失明示。报告依次展示：问题及范围、检索方法和限制、分类与比较、结果和条件、局限及缺口、参考文献。只有摘要时注明“基于摘要”；综合推断明确标识，不能呈现为论文原话。各导出格式与页面展示引用使用同一套数据。
