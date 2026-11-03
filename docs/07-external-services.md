# 外部服务与技术资料

官方文档核验日期：2026-10-29。这里只核验公开说明，**未在目标机器实测服务可达性、注册条件、费用或检索结果质量**。服务规则可能变更，接入前重新查证。

| 候选 | 已查阅的官方资料 | 当前设计含义 |
| --- | --- | --- |
| OpenAlex | [API 概览](https://help.openalex.org/api/)、[认证与限额](https://help.openalex.org/api/authentication/)、[价格](https://help.openalex.org/access/pricing/) | 可用于作品元数据检索；无密钥访问和账户预算存在限制，不能假定无限免费或所有全文可得。 |
| arXiv | [API 手册](https://info.arxiv.org/help/api/user-manual.html)、[使用条款](https://info.arxiv.org/help/api/tou.html) | 适合查找预印本；条款对请求速率和论文内容使用有约束，接入前核对当前限制。 |
| Semantic Scholar | [官方 API 教程](https://webflow.semanticscholar.org/product/api/tutorial) | 可作为另一候选；接口、认证及限流需根据目标环境验证。 |
| PDF 提取 | [pypdf 文本提取](https://pypdf.readthedocs.io/en/stable/user/extract-text.html) | 文本型 PDF 可逐页提取；扫描页可能无法直接得到文字，复杂版面和内存消耗需用样本评估。 |
| 本地数据库 | [SQLite 使用场景](https://www.sqlite.org/whentouse.html)、[事务](https://www.sqlite.org/lang_transaction.html) | 本地存储适合初期；并发写入受限，避免在事务内等待外部服务。 |
| Web | [FastAPI 后台任务](https://fastapi.tiangolo.com/tutorial/background-tasks/)、[Vue 入门](https://vuejs.org/guide/introduction.html) | 后端和前端框架已确认；长任务的持久状态与中断处理需要项目自行设计。 |
| 模型协议 | [OpenAI Chat Completions](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create)、[OpenAI Responses 对比](https://developers.openai.com/api/docs/guides/migrate-to-responses)、[Anthropic Messages](https://platform.claude.com/docs/en/api/messages/create) | 三种协议的输入、输出及可选能力不完全相同；用户配置的第三方服务需单独验证兼容性。 |

首期检索源已确定为 arXiv；OpenAlex 与 Semantic Scholar 仅作为后续扩展参考。

## 接入前实际验证

- 使用项目允许访问的网络和用户自己的配置确认 arXiv 可查询、字段可映射、限流能识别；记录时间与查询，不记录密钥。
- 分别选取文本型、多栏或表格、扫描型 PDF 样本，核对页码、可读性和缺项；保留符合使用许可的测试样本。
- 检查实际全文链接的可用性与相应使用许可。能打开不代表可以任意重新分发；不提交下载的论文。
- 确认模型服务的数据处理政策、价格、结构化输出能力和可提供的用量统计；真实调用前确认可能产生的费用。

## 协议字段与兼容边界

以下依据于2026-11-02通过官方 SDK 中由 OpenAPI 生成的类型及技术资料核对，不能据此假定已直接读取所有协议网页，也不证明第三方兼容服务或具体型号支持所有可选参数。资料核对和离线协议测试不替代实际供应商接入验收。

| 实现要点 | 官方依据 |
| --- | --- |
| Chat `max_completion_tokens`、JSON格式参数 | [OpenAI Chat参数](https://raw.githubusercontent.com/openai/openai-python/main/src/openai/types/chat/completion_create_params.py) |
| Responses内容块为 `output_text`，结构化格式在 `text.format`，上限为 `max_output_tokens` | [输出类型](https://raw.githubusercontent.com/openai/openai-python/main/src/openai/types/responses/response_output_text.py)、[text配置](https://raw.githubusercontent.com/openai/openai-python/main/src/openai/types/responses/response_text_config_param.py)、[请求参数](https://raw.githubusercontent.com/openai/openai-python/main/src/openai/types/responses/response_create_params.py) |
| Anthropic必需 `max_tokens`、输入及cache用量 | [请求参数](https://raw.githubusercontent.com/anthropics/anthropic-sdk-python/main/src/anthropic/types/message_create_params.py)、[响应usage说明](https://raw.githubusercontent.com/anthropics/anthropic-sdk-python/main/src/anthropic/types/message.py) |
| arXiv的Atom错误entry和PDF link，缺失链接不是可推造字段 | [arXiv API手册](https://info.arxiv.org/help/api/user-manual.html) |
| PDF复杂版面／扫描不能保证提取，已知内容异常须区分 | [pypdf文本提取](https://pypdf.readthedocs.io/en/stable/user/extract-text.html)、[pypdf 6.21.4异常](https://pypdf.readthedocs.io/en/6.21.4/modules/errors.html) |
| 同步subprocess超时的终止行为、异步路径需显式终止回收 | [Python subprocess.run](https://docs.python.org/3/library/subprocess.html#subprocess.run) |
| 校验后连接固定IP时保持原TLS服务名与证书校验 | [已安装httpcore 1.0.9连接实现](https://raw.githubusercontent.com/encode/httpcore/1.0.9/httpcore/_async/connection.py) |

实际价格、注册条件、服务可达性与课题检索质量须随用户所选服务独立核验。PDF 子进程隔离和时限不是完整内存资源沙箱；复杂表格和大压缩内容仍需受控样本人工评估。

## 模型列表接口

2026-11-03核验：[OpenAI模型列表](https://developers.openai.com/api/reference/resources/models/methods/list)为GET `/models`，返回`data`模型清单，使用Bearer凭据；Chat Completions与Responses配置共用此列表入口。[Anthropic模型列表](https://platform.claude.com/docs/en/api/models/list)为GET `/v1/models`，返回`data/has_more/last_id`，以`after_id`继续分页。本项目的服务地址已包含用户提供的API前缀，因此只追加`/models`。

Anthropic列表沿用现有适配器的`x-api-key`和`anthropic-version: 2023-06-01`。[认证文档](https://platform.claude.com/docs/en/manage-claude/authentication)说明仍支持该密钥头，[版本文档](https://platform.claude.com/docs/en/api/versioning)列出此版本。当前实现只接收供应商原样返回的模型标识，不预置或推断型号能力；第三方兼容服务、实际凭据权限及连通性仍需用户所选服务验证。
