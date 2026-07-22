#!/usr/bin/env python3
"""Build a lossless, evidence-balanced model handoff bundle from v2 artifacts."""

from __future__ import annotations

import argparse
from collections import defaultdict
from typing import Any

from contracts_v2 import (
    ContractError,
    artifact_header,
    emit_json,
    load_json_object,
    require_same_identity,
    validate_evidence_pack_artifact,
    validate_paper_record_artifact,
)

PROFILE_WRITING_GUIDANCE: dict[str, dict[str, Any]] = {
    "experimental_physics": {
        "core_chain": ["实验体系", "测量", "观测", "推断", "替代解释"],
        "preferred_sections": ["实验体系与测量", "结果与证据链", "物理解释与替代解释"],
        "forbidden_template": "不得强制使用输入—操作—输出或机器学习任务模板。",
    },
    "theoretical_physics": {
        "core_chain": ["理论问题", "模型与假设", "推导或计算", "预测", "适用边界"],
        "preferred_sections": ["理论模型", "关键推导", "可检验预测"],
        "forbidden_template": "不得把理论推导改写成数据管线。",
    },
    "materials_fabrication": {
        "core_chain": ["材料与器件", "加工步骤", "表征", "性能结果", "工艺边界"],
        "preferred_sections": ["材料与工艺", "关键加工窗口", "表征与器件结果"],
        "forbidden_template": "不得用模型训练语言描述加工工艺。",
    },
    "ai_method": {
        "core_chain": ["任务定义", "输入", "关键变换", "训练与推理", "输出与评估"],
        "preferred_sections": ["数据与任务定义", "方法主线", "训练与推理"],
        "forbidden_template": "只有 AI 方法论文才可使用输入—输出式机制描述。",
    },
    "benchmark": {
        "core_chain": ["任务覆盖", "数据构建", "评测协议", "基线", "偏差与边界"],
        "preferred_sections": ["数据构建", "评测维度", "基线与结果"],
        "forbidden_template": "不得把榜单名次写成方法机制。",
    },
    "clinical": {
        "core_chain": ["样本来源", "变量与量表", "分析协议", "结果", "外推边界"],
        "preferred_sections": ["样本与招募", "变量与分析", "临床意义"],
        "forbidden_template": "不得把相关性结果写成临床因果结论。",
    },
    "humanities": {
        "core_chain": ["研究对象", "材料", "理论框架", "论证路径", "解释边界"],
        "preferred_sections": ["材料来源", "理论框架", "论证路径"],
        "forbidden_template": "不得把解释性论证伪装成实验因果链。",
    },
    "survey": {
        "core_chain": ["综述范围", "分类框架", "代表性证据", "争议", "研究空白"],
        "preferred_sections": ["范围与分类", "关键脉络", "争议与空白"],
        "forbidden_template": "不得虚构单一实验协议。",
    },
    "generic": {
        "core_chain": ["研究问题", "材料或方法", "主要结果", "解释", "边界"],
        "preferred_sections": ["研究问题", "方法与证据", "主要结果"],
        "forbidden_template": "证据不足时保持通用结构，不得默认套用 AI 模板。",
    },
}


def parser() -> argparse.ArgumentParser:
    command = argparse.ArgumentParser(description=__doc__)
    command.add_argument("--paper-record", required=True)
    command.add_argument("--evidence", required=True)
    command.add_argument("--visual-pages", default="")
    command.add_argument("--output", default="")
    return command


def _optional_artifact(value: str) -> dict[str, Any]:
    return load_json_object(value) if value else {}


def _check_optional_identity(
    paper_record: dict[str, Any],
    optional: dict[str, Any],
) -> None:
    if optional.get("schema_version") == "2.0":
        require_same_identity(paper_record, optional)


def _by_type(units: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for unit in units:
        if not isinstance(unit, dict):
            continue
        for kind in unit.get("types", []) or ["general"]:
            grouped[str(kind)].append(unit)
    return dict(grouped)


def build_bundle(
    paper_record: dict[str, Any],
    evidence: dict[str, Any],
    visual_pages: dict[str, Any] | None = None,
) -> dict[str, Any]:
    validate_paper_record_artifact(paper_record)
    validate_evidence_pack_artifact(
        evidence,
        paper_record_artifact=paper_record,
    )
    paper_id, run_id = require_same_identity(paper_record, evidence)
    visual_pages = visual_pages or {}
    _check_optional_identity(paper_record, visual_pages)

    record = paper_record["paper_record"]
    metadata = record["metadata"]
    pack = evidence.get("evidence_pack")
    if not isinstance(pack, dict):
        raise ContractError("evidence artifact is missing evidence_pack")
    units = [item for item in pack.get("evidence_units", []) if isinstance(item, dict)]
    paper_type = str(pack.get("paper_type", "generic"))
    guidance = PROFILE_WRITING_GUIDANCE.get(paper_type, PROFILE_WRITING_GUIDANCE["generic"])
    status = str(evidence["status"])
    failures = list(evidence.get("failures", []))

    artifact = artifact_header(
        "synthesis_bundle",
        paper_id=paper_id,
        run_id=run_id,
        status=status,
        failures=failures,
    )
    artifact.update(
        {
            "title": metadata.get("title", ""),
            "metadata": metadata,
            "document_index": record.get("documents", []),
            "paper_type": paper_type,
            "paper_type_rationale": pack.get("paper_type_rationale", ""),
            "evidence_quality": pack.get("evidence_quality", "unknown"),
            "coverage": pack.get("coverage", {}),
            "evidence_units": units,
            "evidence_by_type": _by_type(units),
            "section_texts": pack.get("section_texts", {}),
            "sections": pack.get("sections", []),
            "candidate_chunks": pack.get("candidate_chunks", {}),
            "equation_candidates": pack.get("equation_candidates", []),
            "figure_captions": pack.get("figure_captions", []),
            "table_captions": pack.get("table_captions", []),
            "visual_pages": visual_pages,
            "summary": evidence.get("summary", {}),
            "note_plan_contract": {
                "artifact_type": "note_plan",
                "required_fields": [
                    "paper_type",
                    "dominant_domain",
                    "evidence_ids",
                    "must_cover",
                    "key_claims",
                    "key_numbers",
                    "real_comparisons",
                    "section_plan",
                ],
                "evidence_reference_rule": (
                    "关键结论必须引用 evidence_id，并保留主文或补充材料页码。"
                ),
                "paper_type_guidance": guidance,
            },
            "writing_contract": {
                "language": "zh-CN",
                "layout": "single_file_two_layer",
                "quick_layer": [
                    "30 秒速览",
                    "关键结论（至少 3 条且绑定 evidence_id/页码）",
                    "关键数字（论文有量化结果时为 3—6 项）",
                    "适用边界",
                    "快速入口",
                    "条件式术语表",
                ],
                "deep_layer": [
                    "折叠式摘要翻译",
                    "研究背景、真正问题与创新",
                    *guidance["preferred_sections"],
                    "物理或领域解释与替代解释",
                    "局限、未决问题和可复用结论",
                    "相关论文",
                    "引用",
                ],
                "paper_type_guidance": guidance,
                "language_rules": [
                    "首次出现的术语用自然中文并在括号中保留英文原词，后文优先中文。",
                    "不得逐句翻译正文或把术语堆积当作深度分析。",
                    "每个公式须紧邻解释符号、适用条件及其回答的问题。",
                    "不得出现与论文类型不相干的机器学习模板语言。",
                    "静态 lint 通过后仍须独立完成中文可读性复核。",
                ],
                "traceability_rule": (
                    "每个核心主张必须关联 evidence_id 和主文/SI 页码；有图表或公式编号时一并保留。"
                ),
                "evidence_gate": (
                    "paper_record 与 evidence_pack 必须均为 pass；"
                    "任一全文、OCR 或关键证据门禁失败时停止，不生成降级笔记。"
                ),
            },
        }
    )
    return artifact


def main() -> None:
    args = parser().parse_args()
    artifact = build_bundle(
        load_json_object(args.paper_record),
        load_json_object(args.evidence),
        _optional_artifact(args.visual_pages),
    )
    emit_json(artifact, args.output or None)
    if artifact["status"] == "fail":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
