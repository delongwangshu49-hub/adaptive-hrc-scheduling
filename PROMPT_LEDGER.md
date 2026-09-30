# 规范化提示词记录

本文件用结构化语言记录项目负责人提出的目标、约束、审查要求和确认决定，以及相应的辅助工作。它服务于研究过程追溯，突出实际的人类决策链，同时如实说明 AI 辅助。

**这些记录是依据项目讨论重构的语义记录，不是逐字提示词，不是原始对话导出，也不是历史执行器实际接收的 JSON。**日期只精确到已知日期；不补造签名、原始消息编号或人工编码行为。

版本为 0.2.2，整理日期为 2026-09-30。操作字段采用英文枚举，解释与术语采用中文。负责人已验收并批准 v0.2.1 首发 r1；本次 v0.2.2 新增记录属于 r2 修订，仍待独立审阅与上传批准。历史记录保留各自时点的语义。

## 记录规则

- 每条记录表达一个实质性指令或决策；普通交流和反复表达不逐句复制。
- human_command 表示负责人指令的语义归一化结果。
- human_contribution 记录确有证据的目标设定、质疑、纠偏、选择或确认。
- assistant_support 记录实际辅助角色，不将 AI 建议伪装为负责人原始创意。
- resolution 区分任务完成、决策确认与仍待验证；请求研究深度不等于创新性已被证明。
- 历史记录默认 RETROSPECTIVE_NORMALIZED；当前整理请求为 CURRENT_NORMALIZED。
- 公开内容使用角色名、研究术语和相对路径，不含个人身份、原始对话或机器信息。

## 受控语言

| 字段或枚举 | 含义 |
| --- | --- |
| SET_OBJECTIVE | 设定研究目标 |
| SET_CONSTRAINTS | 设置范围与依赖约束 |
| REQUEST_CRITICAL_REVIEW | 要求批判性复核 |
| REQUIRE_SOURCE_REVIEW | 要求重新核对来源 |
| REFINE_ACCEPTANCE_CRITERIA | 提高选题或产物标准 |
| CORRECT_ARCHITECTURE | 修正整体框架与子课题层级 |
| REQUEST_SCOPE_TRADEOFF | 要求比较并行范围与取舍 |
| CONFIRM_RESEARCH_SCOPE | 确认研究组合 |
| CONFIRM_TECHNICAL_ROUTE | 确认已提出的技术路线 |
| AUTHOR_GOVERNANCE_DOCUMENTS | 授权编写治理文件 |
| REFINE_EXECUTION_AND_PUBLICATION_WORKFLOW | 细分步骤，补齐工程操作并规定逐次上传审批 |
| ACCEPT_GOVERNANCE_AND_START_STEP | 认可治理基线并授权本地开展步骤，不等于上传批准 |
| CONFIRM_REPOSITORY_CONFIGURATION | 确认仓库配置、许可和提交身份，不等于上传批准 |
| APPROVE_STEP_PUBLICATION | 仅在负责人实际批准特定快照上传时使用 |
| REQUEST_STEP_REVISION | 负责人要求修改具体步骤 |
| HUMAN_CONFIRMED | 负责人已确认该决策 |
| REVIEW_COMPLETED | 复核工作已进行，不代表所有结论成立 |
| INCORPORATED | 指令已纳入后续方案 |
| DRAFTED_PENDING_REVIEW | 初稿已形成，尚待负责人审阅 |

## 结构化记录

```json
{
  "schema_version": "1.0",
  "document_version": "0.2.2",
  "date_precision": "DAY",
  "timezone": "UTC+08:00",
  "record_basis": "NORMALIZED_FROM_PROJECT_DISCUSSION",
  "raw_prompt_included": false,
  "roles": {
    "HUMAN_LEAD": "研究目标、范围取舍、路线确认与验收的项目负责人",
    "AI_ASSISTANT": "资料、推理、文档及授权实现工作的辅助者"
  },
  "records": [
    {
      "id": "PR001",
      "date": "2026-09-25",
      "record_type": "RETROSPECTIVE_NORMALIZED",
      "human_command": {
        "operation": "SET_OBJECTIVE",
        "target": "PROJECT_PREPARATION",
        "parameters": {
          "actions": [
            "READ_PROVIDED_REFERENCES",
            "EXPLAIN_REQUIREMENTS",
            "ESTABLISH_PROJECT_UNDERSTANDING"
          ]
        }
      },
      "human_contribution": [
        "INITIATED_PROJECT",
        "DEFINED_PREPARATION_GOAL",
        "PROVIDED_REFERENCE_CONTEXT"
      ],
      "assistant_support": [
        "REFERENCE_READING",
        "REQUIREMENT_SUMMARY",
        "CONCEPT_EXPLANATION"
      ],
      "resolution": "REVIEW_COMPLETED",
      "evidence_refs": [
        "PROGRESS_LOG.md#2026年9月25日-研究准备启动"
      ],
      "limit": "NO_IMPLEMENTATION_OR_EXPERIMENT_CLAIM"
    },
    {
      "id": "PR002",
      "date": "2026-09-30",
      "record_type": "RETROSPECTIVE_NORMALIZED",
      "human_command": {
        "operation": "SET_CONSTRAINTS",
        "target": "PROJECT_DEPENDENCIES",
        "parameters": {
          "provided_runnable_assets": false,
          "build_model_scene_code_instances": true,
          "remove_administrative_confirmation_work": true,
          "remove_dependency_on_provided_runtime_resources": true
        }
      },
      "human_contribution": [
        "CORRECTED_RESOURCE_ASSUMPTION",
        "REMOVED_UNNECESSARY_WORK",
        "SET_BUILD_FROM_SCRATCH_BOUNDARY"
      ],
      "assistant_support": [
        "REVISED_FEASIBILITY_AND_SCOPE"
      ],
      "resolution": "INCORPORATED",
      "evidence_refs": [
        "PROGRESS_LOG.md#2026年9月30日-范围复核与研究问题收敛"
      ],
      "limit": "ENVIRONMENT_READINESS_NOT_ESTABLISHED"
    },
    {
      "id": "PR003",
      "date": "2026-09-30",
      "record_type": "RETROSPECTIVE_NORMALIZED",
      "human_command": {
        "operation": "REQUEST_CRITICAL_REVIEW",
        "target": "RESEARCH_CANDIDATES",
        "parameters": {
          "evaluate": [
            "SCIENTIFIC_DEPTH",
            "DIFFERENTIATION",
            "DIFFICULTY",
            "TRADEOFFS",
            "EFFORT"
          ],
          "challenge_shallow_scope": true
        }
      },
      "human_contribution": [
        "CHALLENGED_PROPOSED_DEPTH",
        "DEFINED_COMPARISON_CRITERIA"
      ],
      "assistant_support": [
        "LITERATURE_SCREENING",
        "CANDIDATE_COMPARISON",
        "CONDITIONAL_EFFORT_ESTIMATION"
      ],
      "resolution": "REVIEW_COMPLETED",
      "evidence_refs": [
        "PROGRESS_LOG.md#2026年9月30日-范围复核与研究问题收敛"
      ],
      "limit": "NOVELTY_NOT_PROVEN"
    },
    {
      "id": "PR004",
      "date": "2026-09-30",
      "record_type": "RETROSPECTIVE_NORMALIZED",
      "human_command": {
        "operation": "REQUIRE_SOURCE_REVIEW",
        "target": "REFERENCE_EVIDENCE",
        "parameters": {
          "reread_original_material": true,
          "reassess_candidates_against_source": true
        }
      },
      "human_contribution": [
        "REQUIRED_SOURCE_VERIFICATION",
        "PROVIDED_RENEWED_FILE_REFERENCES"
      ],
      "assistant_support": [
        "SOURCE_REACCESS",
        "FULL_TEXT_REVIEW",
        "KEY_FIGURE_CHECK"
      ],
      "resolution": "REVIEW_COMPLETED",
      "evidence_refs": [
        "PROGRESS_LOG.md#2026年9月30日-范围复核与研究问题收敛"
      ],
      "limit": "PRIVATE_SOURCE_CONTENT_NOT_REPRODUCED"
    },
    {
      "id": "PR005",
      "date": "2026-09-30",
      "record_type": "RETROSPECTIVE_NORMALIZED",
      "human_command": {
        "operation": "REFINE_ACCEPTANCE_CRITERIA",
        "target": "TOPIC_SELECTION",
        "parameters": {
          "require": [
            "TESTABLE_RESEARCH_QUESTION",
            "IMPLEMENTATION_FEASIBILITY",
            "FUTURE_RESEARCH_EXTENSION"
          ]
        }
      },
      "human_contribution": [
        "SET_RESEARCH_QUALITY_BAR",
        "REQUIRED_FEASIBILITY_AND_SCIENTIFIC_VALUE"
      ],
      "assistant_support": [
        "REFINED_FOUR_RESEARCH_DIRECTIONS",
        "IDENTIFIED_FAILURE_MODES"
      ],
      "resolution": "INCORPORATED",
      "evidence_refs": [
        "README.md"
      ],
      "limit": "CANDIDATE_CONTRIBUTIONS_REMAIN_HYPOTHESES"
    },
    {
      "id": "PR006",
      "date": "2026-09-30",
      "record_type": "RETROSPECTIVE_NORMALIZED",
      "human_command": {
        "operation": "CORRECT_ARCHITECTURE",
        "target": "FRAMEWORK_AND_SUBSTUDIES",
        "parameters": {
          "complete_scheduling_framework_is_primary": true,
          "research_directions_are_nested_substudies": true,
          "mandatory_resources": [
            "HUMAN",
            "ROBOT",
            "PROCESS_MACHINE",
            "GANTRY_CRANE"
          ],
          "mandatory_dynamics": [
            "FATIGUE",
            "FAILURE",
            "ORDER_CHANGE"
          ]
        }
      },
      "human_contribution": [
        "CORRECTED_SYSTEM_HIERARCHY",
        "REASSERTED_COMPLETE_DELIVERABLE",
        "ALIGNED_RESEARCH_WITH_SYSTEM_SCOPE"
      ],
      "assistant_support": [
        "RESTRUCTURED_ARCHITECTURE",
        "SEPARATED_FRAMEWORK_AND_RESEARCH_VALIDATION"
      ],
      "resolution": "INCORPORATED",
      "evidence_refs": [
        "README.md"
      ],
      "limit": "ARCHITECTURE_DEFINITION_IS_NOT_SYSTEM_COMPLETION"
    },
    {
      "id": "PR007",
      "date": "2026-09-30",
      "record_type": "RETROSPECTIVE_NORMALIZED",
      "human_command": {
        "operation": "REQUEST_SCOPE_TRADEOFF",
        "target": "SUBSTUDY_PORTFOLIO",
        "parameters": {
          "compare": [
            "FOUR_FULL_SUBSTUDIES",
            "ONE_OR_TWO_FOCUSED_SUBSTUDIES"
          ],
          "consider": [
            "DEPENDENCIES",
            "EXPERIMENT_ATTRIBUTION",
            "WORKLOAD"
          ]
        }
      },
      "human_contribution": [
        "REQUESTED_SCOPE_DISCIPLINE",
        "REQUIRED_DEPENDENCY_AND_WORKLOAD_REASONING"
      ],
      "assistant_support": [
        "COMPARED_COMBINATIONS",
        "RECOMMENDED_PRIMARY_AND_SUPPORTING_STUDIES"
      ],
      "resolution": "REVIEW_COMPLETED",
      "evidence_refs": [
        "PROGRESS_LOG.md#2026年9月30日-研究组合与技术路线确认"
      ],
      "limit": "RECOMMENDATION_REQUIRES_SEPARATE_HUMAN_SELECTION"
    },
    {
      "id": "PR008",
      "date": "2026-09-30",
      "record_type": "RETROSPECTIVE_NORMALIZED",
      "human_command": {
        "operation": "CONFIRM_RESEARCH_SCOPE",
        "target": "RESEARCH_PORTFOLIO",
        "parameters": {
          "framework": "COMPLETE_ADAPTIVE_SCHEDULING",
          "A": "CORE_DECISION_METHOD",
          "D": "HUMAN_FACTOR_TRADEOFF_ANALYSIS",
          "B": "ROBUSTNESS_CHECK",
          "C": "RECOVERY_EVALUATION",
          "next_action": "DEFINE_TECHNICAL_ROUTE"
        }
      },
      "human_contribution": [
        "SELECTED_RESEARCH_PORTFOLIO",
        "CONFIRMED_SCOPE",
        "DIRECTED_TECHNICAL_PLANNING"
      ],
      "assistant_support": [
        "FORMALIZED_IMPLEMENTATION_ROUTE"
      ],
      "resolution": "HUMAN_CONFIRMED",
      "evidence_refs": [
        "README.md",
        "PROGRESS_LOG.md#2026年9月30日-研究组合与技术路线确认"
      ],
      "limit": "NO_INDEPENDENT_B_OR_C_RESEARCH_PROGRAM"
    },
    {
      "id": "PR009",
      "date": "2026-09-30",
      "record_type": "RETROSPECTIVE_NORMALIZED",
      "human_command": {
        "operation": "CONFIRM_TECHNICAL_ROUTE",
        "target": "TECHNICAL_ROUTE_V1",
        "parameters": {
          "decision_method": "EVENT_DRIVEN_ROLLING_STATE_AWARE_LNS",
          "execution": [
            "LIGHTWEIGHT_EVENT_SIMULATION",
            "ISAAC_SIM_CLOSED_LOOP"
          ],
          "small_instance_reference": "CP_SAT_ON_MATCHED_SIMPLIFIED_MODEL",
          "validation": [
            "A_COMPARISONS",
            "D_TRADEOFFS",
            "B_ROBUSTNESS",
            "C_RECOVERY"
          ],
          "implementation_readiness": "TO_BE_VERIFIED"
        }
      },
      "human_contribution": [
        "APPROVED_TECHNICAL_ROUTE",
        "AUTHORIZED_GOVERNANCE_FORMALIZATION"
      ],
      "assistant_support": [
        "DOCUMENTED_MODEL_ALGORITHM_AND_ACCEPTANCE_GATES"
      ],
      "resolution": "HUMAN_CONFIRMED",
      "evidence_refs": [
        "README.md",
        "PROGRESS_LOG.md#2026年9月30日-研究组合与技术路线确认"
      ],
      "limit": "RUNTIME_PARAMETERS_AND_STAGE_ACCEPTANCE_PENDING"
    },
    {
      "id": "PR010",
      "date": "2026-09-30",
      "record_type": "CURRENT_NORMALIZED",
      "human_command": {
        "operation": "AUTHOR_GOVERNANCE_DOCUMENTS",
        "target": "PROJECT_DOCUMENTATION",
        "parameters": {
          "deliverables": [
            "LOCAL_INTERNAL_CHARTER",
            "PUBLIC_CHARTER",
            "PUBLIC_PROGRESS_LOG",
            "NORMALIZED_PROMPT_LEDGER"
          ],
          "public_content_sanitized": true,
          "raw_prompt_copy": false,
          "preserve_evidenced_human_leadership": true,
          "github_action": "PREPARE_FILES_ONLY"
        }
      },
      "human_contribution": [
        "DEFINED_DOCUMENT_GOVERNANCE",
        "SET_PRIVACY_BOUNDARY",
        "REQUIRED_STRUCTURED_PROCESS_TRACE",
        "ASSERTED_HUMAN_DECISION_ROLE"
      ],
      "assistant_support": [
        "DRAFTED_DOCUMENTS",
        "CONFIGURED_LOCAL_EXCLUSIONS",
        "CHECKED_PUBLIC_CONTENT"
      ],
      "resolution": "DRAFTED_PENDING_REVIEW",
      "evidence_refs": [
        "README.md",
        "PROGRESS_LOG.md",
        "PROMPT_LEDGER.md"
      ],
      "limit": "NO_REMOTE_CREATION_COMMIT_PUSH_OR_PUBLICATION"
    },
    {
      "id": "PR011",
      "date": "2026-09-30",
      "record_type": "CURRENT_NORMALIZED",
      "human_command": {
        "operation": "REFINE_EXECUTION_AND_PUBLICATION_WORKFLOW",
        "target": "STEPWISE_PROJECT_GOVERNANCE",
        "parameters": {
          "replace_coarse_phases_with_actionable_steps": true,
          "include_external_engineering": [
            "REPOSITORY_NAMING",
            "REPOSITORY_CREATION",
            "VERSION_CONTROL",
            "CI",
            "PUBLICATION_TRACE"
          ],
          "human_approval_required_for_each_upload": true,
          "publish_each_completed_approved_step": true,
          "defer_all_uploads_until_project_end": false,
          "current_authorized_action": "REVISE_DOCUMENTS_LOCALLY",
          "repository_metadata_status": "PENDING_CONFIRMATION"
        }
      },
      "human_contribution": [
        "IDENTIFIED_INSUFFICIENT_TASK_GRANULARITY",
        "IDENTIFIED_MISSING_EXTERNAL_ENGINEERING",
        "DEFINED_STEPWISE_REVIEW_AND_PUBLICATION_GATE"
      ],
      "assistant_support": [
        "DECOMPOSED_WORK_INTO_STEPS",
        "DEFINED_ARTIFACTS_AND_ACCEPTANCE_EVIDENCE",
        "DOCUMENTED_REPOSITORY_BOOTSTRAP_AND_APPROVAL_RECEIPTS"
      ],
      "resolution": "DRAFTED_PENDING_REVIEW",
      "evidence_refs": [
        "README.md#步骤化路线图",
        "PROGRESS_LOG.md#2026年9月30日-步骤化执行与逐次发布修订"
      ],
      "limit": "WORKFLOW_REQUIREMENT_CONFIRMED_BUT_NO_STEP_UPLOAD_OR_REPOSITORY_CREATION_APPROVAL"
    },
    {
      "id": "PR012",
      "date": "2026-09-30",
      "record_type": "CURRENT_NORMALIZED",
      "human_command": {
        "operation": "ACCEPT_GOVERNANCE_AND_START_STEP",
        "target": "S00_GOVERNANCE_AND_BOOTSTRAP",
        "parameters": {
          "accepted_document_version": "0.2.0",
          "step_id": "S00",
          "reuse_current_directory": true,
          "create_extra_branch": false,
          "create_worktree": false,
          "authorized_scope": "LOCAL_S00_PREPARATION",
          "permitted_remote_actions": []
        }
      },
      "human_contribution": [
        "REVIEWED_GOVERNANCE_BASELINE",
        "AUTHORIZED_S00",
        "SET_WORKSPACE_AND_BRANCH_CONSTRAINTS"
      ],
      "assistant_support": [
        "PREPARED_S00_FILES",
        "PRESERVED_PUBLICATION_GATE"
      ],
      "resolution": "HUMAN_CONFIRMED",
      "evidence_refs": [
        "PROGRESS_LOG.md#2026年9月30日-s00-本地首发准备",
        "docs/steps/S00.md"
      ],
      "limit": "BASELINE_ACCEPTANCE_AND_STEP_START_ARE_NOT_FIRST_PUBLICATION_APPROVAL"
    },
    {
      "id": "PR013",
      "date": "2026-09-30",
      "record_type": "CURRENT_NORMALIZED",
      "human_command": {
        "operation": "CONFIRM_REPOSITORY_CONFIGURATION",
        "target": "S00_GOVERNANCE_AND_BOOTSTRAP",
        "parameters": {
          "step_id": "S00",
          "owner": "CONFIRMED_PERSONAL_ACCOUNT",
          "repository_name": "adaptive-hrc-scheduling",
          "visibility": "public",
          "initial_default_branch": "main",
          "description": "Adaptive human–robot scheduling for modular construction with fatigue and disruptions.",
          "license": "MIT",
          "commit_identity": "CONFIRMED_EXISTING_NAME_AND_NOREPLY_EMAIL",
          "permitted_remote_actions": []
        }
      },
      "human_contribution": [
        "SELECTED_REPOSITORY_CONFIGURATION",
        "SELECTED_MIT_LICENSE",
        "CONFIRMED_COMMIT_IDENTITY"
      ],
      "assistant_support": [
        "READ_ONLY_ACCOUNT_AND_IDENTITY_CHECK",
        "PREPARED_LICENSE_AND_PUBLICATION_PACKET"
      ],
      "resolution": "HUMAN_CONFIRMED",
      "evidence_refs": [
        "PROGRESS_LOG.md#2026年9月30日-s00-本地首发准备",
        "docs/steps/S00.md"
      ],
      "limit": "CONFIGURATION_CONFIRMED_BUT_EXACT_SNAPSHOT_CREATION_AND_PUSH_APPROVAL_PENDING"
    },
    {
      "id": "PR014",
      "date": "2026-09-30",
      "record_type": "CURRENT_NORMALIZED",
      "human_command": {
        "operation": "APPROVE_STEP_PUBLICATION",
        "target": "S00_GOVERNANCE_AND_BOOTSTRAP",
        "parameters": {
          "step_id": "S00",
          "packet_id": "S00-20260930-r1",
          "decision": "ACCEPTED_AND_APPROVED",
          "packet_sha256": "119d332b7b3ee581104cadd9c1ba74d3fc0eabc5b3d34ee645cf527dfee6045f",
          "permitted_remote_actions": [
            "CREATE_EMPTY_PUBLIC_REPOSITORY",
            "PUSH_MAIN_AND_STEP_TAG"
          ]
        }
      },
      "human_contribution": [
        "REVIEWED_AND_APPROVED_EXACT_FIRST_PUBLICATION"
      ],
      "assistant_support": [
        "EXECUTED_APPROVED_PUBLICATION",
        "VERIFIED_REMOTE_SNAPSHOT"
      ],
      "resolution": "HUMAN_CONFIRMED",
      "evidence_refs": [
        "PROGRESS_LOG.md#2026年9月30日-s00-首发回执补录",
        "docs/steps/S00.md"
      ],
      "limit": "AUTHORIZATION_LIMITED_TO_R1_SNAPSHOT"
    },
    {
      "id": "PR015",
      "date": "2026-09-30",
      "record_type": "CURRENT_NORMALIZED",
      "human_command": {
        "operation": "REQUEST_CRITICAL_REVIEW",
        "target": "S00_GOVERNANCE_AND_BOOTSTRAP",
        "parameters": {
          "step_id": "S00",
          "check_completion": true,
          "review_logic": true,
          "permitted_remote_actions": []
        }
      },
      "human_contribution": [
        "REQUESTED_COMPLETENESS_AND_LOGIC_AUDIT"
      ],
      "assistant_support": [
        "VERIFIED_COMPLETION_AND_REMOTE_STATE",
        "IDENTIFIED_EVIDENCE_TOOL_AND_TIME_WORDING_ISSUES"
      ],
      "resolution": "REVIEW_COMPLETED",
      "evidence_refs": [
        "PROGRESS_LOG.md#2026年9月30日-s00-有限修订",
        "docs/steps/S00.md"
      ],
      "limit": "AUDIT_DOES_NOT_AUTHORIZE_UPLOAD"
    },
    {
      "id": "PR016",
      "date": "2026-09-30",
      "record_type": "CURRENT_NORMALIZED",
      "human_command": {
        "operation": "REQUEST_STEP_REVISION",
        "target": "S00_GOVERNANCE_AND_BOOTSTRAP",
        "parameters": {
          "step_id": "S00",
          "revision": 2,
          "scope": [
            "LOCAL_PACKET_OVERWRITE_PROTECTION",
            "GOVERNANCE_TIME_AND_STATUS_CLARITY",
            "RECORD_EXISTING_R1_RECEIPT"
          ],
          "start_S01": false,
          "permitted_remote_actions": []
        }
      },
      "human_contribution": [
        "AUTHORIZED_LIMITED_LOCAL_REPAIR"
      ],
      "assistant_support": [
        "FIXED_LOCAL_EVIDENCE_PROTECTION",
        "CLARIFIED_HISTORICAL_AND_CURRENT_STATUS",
        "PREPARED_REVISION_REVIEW_PACKET"
      ],
      "resolution": "INCORPORATED",
      "evidence_refs": [
        "PROGRESS_LOG.md#2026年9月30日-s00-有限修订",
        "docs/steps/S00.md"
      ],
      "limit": "REPAIR_AUTHORIZATION_IS_NOT_EXACT_R2_UPLOAD_APPROVAL"
    }
  ]
}
```

## 后续记录要求

新增记录沿用 PR 编号及当前 schema。只记录实际发生的指令与决策，不能根据进度计划预生成“已确认”记录。技术参数、实现问题和实验结论若尚未由负责人确认，保留相应状态，不自动升级。

schema 必须保留操作、目标、参数、人的贡献、辅助工作、处理状态、证据引用和限制。参数优先使用布尔值、枚举、列表及稳定对象名；确需说明时使用短句，不复述原始聊天口吻。

实际编码、实验执行、审阅和验收在进度日志中按证据记录；本文件不将这些工作默认归属于任何一方。研究领导权由真实目标设定、纠偏和确认体现，辅助使用也应如实披露。

若后续发现语义归一化有误，追加更正记录并引用被更正的 PR 编号，不能制造“原始输入从未改变”的印象。

## 逐步审批的后续记录规则

后续审批记录的 parameters 包含 step_id、packet_id、decision 和 permitted_remote_actions。APPROVE_STEP_PUBLICATION 只能记录已发生且针对确切快照的人工上传批准；路线确认、继续工作或文档认可不能机械转成上传许可。

批准原话和私有证据位置不公开，规范化决策编号与进度日志对应。某步没有新的实质指令时只维护进度与发布记录，不为凑编号伪造提示词。实际回执按进度日志规则补录，不能预写成功。

PR010 保留此前仅准备文件的历史语义；PR011 增加今后的逐步审批发布机制，该记录当时授权仍是本地文档修订。PR012、PR013 进一步确认治理基线、启动 S00 和落实元数据；PR014 补录随后发生的 r1 首发批准。PR015、PR016 仅授权审阅与有限修复，r2 仍必须取得针对新快照的上传批准。
