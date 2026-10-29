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
