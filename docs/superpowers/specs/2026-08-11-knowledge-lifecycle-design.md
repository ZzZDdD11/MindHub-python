# 知识沉淀完整闭环设计

## 目标

在现有 `conversation_records → conversation_candidates` 可信链路之后，实现由管理员审核控制的完整知识闭环：审核 Candidate、生成或手工维护草稿、发布版本化知识卡到指定知识库、构建 Wiki 与图谱投影，并以一跳图谱扩展增强现有 RAG。

## 已确认决策

- Candidate 必须人工审核；只有 `approved` 的 Candidate 可以创建草稿或发布知识。
- 管理操作由环境变量 `ADMIN_API_KEY` 保护，使用 `X-Admin-API-Key` 请求头。
- 草稿支持 AI 生成和人工创建/编辑；管理页默认使用 AI 生成。
- 每次发布必须选择既有 `kb_id`。
- 图谱由 AI 在发布时自动抽取；关系保留卡片版本、证据与置信度。
- 不新增图数据库、队列或第三方依赖。

## 边界与状态机

```text
conversation_candidate
pending_review ──审核通过──> approved ──创建草稿──> draft
       │                              │
       └────审核拒绝──> rejected       └──管理员发布──> published card version
                                                     ├── KB 文档投影
                                                     ├── Wiki 页面投影
                                                     └── 图节点/关系投影
```

- 审核只能从 `pending_review` 迁移到 `approved` 或 `rejected`，并一次性写入审核时间、审核结论和可选理由。
- 草稿可多次编辑；仅发布动作产生不可变的 `knowledge_card_versions`。
- 发布只能从草稿进行，且目标 `kb_id` 必须存在。
- 发布失败时不标记版本为发布成功；已发布版本不允许修改。
- Wiki、图谱和 KB 文档都是知识卡版本的投影，均保留来源版本 ID，允许按版本重建。

## 管理安全

- 新增独立 `/api/v1/admin/knowledge` 路由；普通 `/v1` API Key 不能访问。
- `ADMIN_API_KEY` 缺失时所有管理接口返回 `503`，绝不降级为匿名访问。
- 通过 `hmac.compare_digest` 比较 `X-Admin-API-Key`；请求头和密钥不会进入日志、数据库或响应。
- 候选、草稿、卡片与图谱查询均只在管理员路由暴露；普通 KB 问答只使用已发布且已投影的内容。
- 管理 UI 不持久化管理员密钥；每次管理请求显式提供该请求头。

## 数据模型

单个版本化迁移新增以下表：

| 表 | 职责 | 关键约束 |
| --- | --- | --- |
| `conversation_candidates` 扩展列 | 审核信息 | `status`、`reviewed_at`、`review_note`；只允许服务层从待审状态审核 |
| `knowledge_drafts` | 候选对应的可编辑草稿 | `(candidate_id, revision)` 唯一；保存 `title`、`summary`、`content`、`tags`、生成方式、状态 |
| `knowledge_cards` | 稳定的发布实体 | Candidate 唯一；保存当前发布版本和状态 |
| `knowledge_card_versions` | 不可变发布版本 | `(card_id, version)` 唯一；保存发布正文、标签、目标 `kb_id` |
| `knowledge_card_projections` | KB 文档投影链接 | `(card_version_id, projection_type)` 唯一；记录 `kb_document_id` |
| `knowledge_wiki_pages` | Wiki Markdown 投影 | `card_version_id` 唯一；保存标题、slug、正文 |
| `knowledge_graph_nodes` | KB 范围内的实体节点 | `(kb_id, normalized_name)` 唯一 |
| `knowledge_graph_edges` | 带证据的有向关系 | 来源卡片版本、证据、置信度；避免同版本重复边 |

Candidate、草稿、卡片都只保存 ID 或管理员提交的知识内容；不复制 API Key、Authorization 头或上游渠道凭据。

## 应用服务

### CandidateReviewService

- 列表、详情、`approve(candidate_id, note)`、`reject(candidate_id, note)`。
- 审核详情结合 `conversation_record` 返回，便于管理员判断；不会把这些内容暴露给非管理员。

### KnowledgeDraftService

- `create_manual(candidate_id, title, summary, content, tags)` 仅接受已通过 Candidate。
- `generate_ai(candidate_id, request_id)` 通过现有 `GatewayService` 请求 `KNOWLEDGE_PIPELINE_MODEL`。
- AI 返回严格 JSON：`title`、`summary`、`content`、`tags`、`entities`、`relations`。解析或上游失败不会发布，只返回可处理错误；管理员仍可创建手工草稿。
- 草稿保存 AI 建议的实体与关系 JSON，允许管理员修改正文和标签；发布时从当前草稿内容重新抽取图谱，防止编辑后使用过时关系。

### KnowledgePublicationService

- 校验草稿、Candidate 审核状态与 `kb_id`。
- 创建卡片/下一不可变版本并保存发布内容。
- 通过现有 `KbService.upload_doc` 创建 `knowledge_card` 类型文档，文件名稳定为卡片标题，内容为标题、摘要、正文和标签。
- 写入 KB 文档、Wiki 与图谱投影；投影失败返回明确错误且不伪造成功，管理员可重试同一发布操作。
- 重试同一已发布版本使用唯一约束重用投影，避免重复 KB 文档和图边。

### KnowledgeGraphService

- 使用现有网关，基于已发布卡片内容抽取严格 JSON 的实体和关系。
- 节点在同一 KB 内按规范化名称去重；边包含关系类型、来源版本、证据片段和 `0..1` 置信度。
- 不把 AI 的未验证文本当作系统指令，也不让模型调用工具。

## API 与最小管理 UI

新增管理 API：

```text
GET    /api/v1/admin/knowledge/candidates?status=pending_review
GET    /api/v1/admin/knowledge/candidates/{candidate_id}
POST   /api/v1/admin/knowledge/candidates/{candidate_id}/approve
POST   /api/v1/admin/knowledge/candidates/{candidate_id}/reject
POST   /api/v1/admin/knowledge/candidates/{candidate_id}/drafts/ai
POST   /api/v1/admin/knowledge/candidates/{candidate_id}/drafts/manual
GET    /api/v1/admin/knowledge/drafts/{draft_id}
PUT    /api/v1/admin/knowledge/drafts/{draft_id}
POST   /api/v1/admin/knowledge/drafts/{draft_id}/publish
GET    /api/v1/admin/knowledge/cards
GET    /api/v1/admin/knowledge/cards/{card_id}
GET    /api/v1/admin/knowledge/wiki/{kb_id}
GET    /api/v1/admin/knowledge/graph/{kb_id}
```

静态 SPA 增加“知识沉淀”页：输入管理员密钥、列出待审 Candidate、审核、生成/手工编辑草稿、选择知识库发布，并查看发布卡片、Wiki 与图谱关系。UI 仅调用管理 API，不含独立权限逻辑。

## 图谱增强 RAG

- `KbAskRequestDTO.search_mode` 增加 `graph_hybrid`；普通 `vector`、`keyword`、`hybrid` 保持原逻辑。
- `graph_hybrid` 先执行现有混合检索，再从查询文本匹配同一 KB 的实体节点。
- 最多一跳：匹配节点 → 相关边 → 来源卡片版本 → 对应 KB 文档分块。
- 最多追加 3 个去重来源，总结果仍受 `top_k` 限制；图谱不可用时回退到普通混合检索。
- RAG 输出来源仍使用现有 DTO，并在 metadata 标记 `graphExpanded: true` 与关联实体名称。

## 配置

```text
ADMIN_API_KEY=<required for admin endpoints>
KNOWLEDGE_PIPELINE_MODEL=<required only for AI draft/graph extraction>
```

应用启动不要求设置以上变量；管理接口或 AI 草稿接口按各自需要 fail-closed。普通代理与普通 RAG 不受影响。

## 验收与测试

- 无或错误管理员密钥：拒绝；正确密钥：允许；从不记录密钥。
- Candidate 只能审核一次；拒绝项不能创建草稿；未审核草稿不能发布。
- AI 草稿失败不发布，手工草稿仍可创建。
- 发布要求有效 KB；一次发布创建一个不可变版本、一个 KB 投影、一个 Wiki 页面和带来源的图关系。
- 重试发布不重复创建投影或关系。
- `graph_hybrid` 仅一跳、去重、限量；图谱查询失败时普通 RAG 仍返回结果。
- 既有网关、Candidate、KB、SSE 测试保持通过。
