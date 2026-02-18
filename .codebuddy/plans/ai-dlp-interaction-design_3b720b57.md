---
name: ai-dlp-interaction-design
overview: 新建一个设计文档，详细描述AI-DLP系统中每个AI介入环节的交互方式、角色与Prompt设计、处理方案（含模型选型和算法设计）。
todos:
  - id: write-design-doc-part1
    content: 使用 [subagent:code-explorer] 精读PRD.md全文，编写AI-DLP-Design.md前半部分：文档头部、角色-AI模块交互矩阵总览、环节1-5处理方案（探针对接算法、数据管道算法、智能分类Prompt、语义分析Prompt、意图识别Prompt）
    status: completed
  - id: write-design-doc-part2
    content: 编写AI-DLP-Design.md后半部分：环节6-10处理方案（事件研判Prompt、策略生成Prompt、自适应学习Prompt、策略引擎算法、管理平台交互方案）以及模型选型与部署建议章节
    status: completed
    dependencies:
      - write-design-doc-part1
---

## 产品概述

新建一份AI-DLP系统的完整交互与Prompt设计文档，覆盖系统全链路10个环节的处理方案，重点包括：

## 核心功能

### 1. 角色-AI模块交互矩阵设计

- 基于PRD定义的5类角色（Admin/Analyst/Compliance/Operator/Viewer），明确每个角色与6个AI模块的交互方式
- 区分"系统自动调用"与"角色主动触发"两类交互模式
- 给出每个交互场景的输入输出定义

### 2. 全环节Prompt设计

- 为6个AI介入环节（智能分类、语义分析、意图识别、事件研判、策略生成、自适应学习）设计完整的System Prompt和User Prompt模板
- 明确每个Prompt由哪个角色/系统组件触发使用
- 包含Few-shot示例和输出格式约束

### 3. 全链路处理方案

- 覆盖10个环节（探针对接、数据管道、智能分类、语义分析、意图识别、事件研判、策略生成、自适应学习、策略引擎、管理平台）
- 对非AI环节给出具体算法设计（特征提取算法、策略匹配算法、冲突裁决算法等）
- 对AI环节给出模型选型建议、调用方式、降级方案

### 4. 模型选型与部署建议

- 各环节推荐的LLM模型及备选方案
- 区分需要LLM和不需要LLM的环节
- 给出性能与成本的平衡策略

## 技术栈

- **文档格式**: Markdown，支持Mermaid图表
- **参考来源**: PRD.md中的完整架构定义、角色矩阵、AI模块设计

## 实现方案

新建一份Markdown设计文档 `AI-DLP-Design.md`，按全链路顺序逐一描述每个环节的处理方案。文档结构包含：角色交互矩阵总览、全链路处理方案（10个环节逐一展开）、完整Prompt设计集、模型选型建议。每个AI环节需包含：触发角色、交互方式、System Prompt、User Prompt模板、Few-shot示例、输出格式、降级算法。每个非AI环节需包含：具体算法伪代码、数据结构、性能指标。

## 实现注意事项

- 所有Prompt设计需严格对齐PRD中定义的数据结构（DLPEvent、ClassificationResult、SemanticResult、IntentResult、AdjudicationResult等）
- 角色权限映射需与PRD 2.2节的权限矩阵一致
- 非AI环节的算法设计需满足PRD第5章的性能需求（如归一化≤50ms、特征提取≤500ms）
- 降级方案需覆盖PRD中定义的所有降级场景

## 架构设计

文档以全链路数据流为主线，结合PRD的6层架构：数据采集层 -> 数据处理管道层 -> AI决策引擎层 -> 策略引擎层 -> API网关层 -> 管理可视化层。AI决策引擎层中的6个模块是Prompt设计的核心目标。

## 目录结构

```
ai-dlp/
├── PRD.md                    # [EXISTING] 产品需求文档
├── architecture.py           # [EXISTING] 架构总览
└── AI-DLP-Design.md          # [NEW] AI-DLP全链路交互与Prompt设计文档。包含：角色-AI模块交互矩阵、10个环节的完整处理方案（含算法设计和Prompt设计）、模型选型与部署建议。文档按数据流顺序组织，每个AI环节包含完整的System/User Prompt模板、Few-shot示例、输出格式约束、降级方案；每个非AI环节包含算法伪代码和数据流定义。
```

## Agent Extensions

### SubAgent

- **code-explorer**
- 用途：在编写设计文档时，深入阅读PRD.md中的所有数据结构定义、角色权限矩阵、AI模块输入输出规格，确保文档内容与PRD完全对齐
- 预期结果：准确引用PRD中定义的字段名、枚举值、阈值等，避免设计文档与PRD出现不一致