"""同一报告快照的本地渲染；下载不调用模型或重新选择资料。"""
from functools import lru_cache
from html import escape
from io import BytesIO
from pathlib import Path
import re

from backend.app.analysis import FIELD_LABELS, MISSING_LABELS, ORIGIN_LABELS

COMPARISON_LABELS = {"comparable": "条件可比", "not_comparable": "不可直接比较", "insufficient": "条件信息不足"}


def blocks(report):
    doc = report.document
    yield "heading", (1, report.title)
    yield "paragraph", f"报告 ID：{report.id}；范围修订：{doc.analysis_revision}；生成时间：{report.created_at.isoformat()}"
    yield "heading", (2, "研究范围与执行记录")
    yield "paragraph", f"研究问题：{doc.scope.topic}；年份：{doc.scope.start_year or '不限'}—{doc.scope.end_year or '不限'}"
    yield "paragraph", f"关注维度：{'、'.join(doc.scope.focus_dimensions) or '六类基础字段'}"
    if doc.scope.output_requirements:
        yield "paragraph", "用户输出要求：" + doc.scope.output_requirements
    yield "paragraph", f"实际外部调用：{doc.total_calls}；模型调用：{doc.model_calls}；Token：{doc.token_usage.get('total_tokens') if doc.token_usage.get('total_tokens') is not None else '未知'}"
    yield "paragraph", f"分析截至快照的执行时间：{doc.execution_seconds:.2f}秒；执行上限/操作性门槛：" + "；".join(f"{key}={value:g}" for key, value in doc.limits.items())
    if report.stop_reason:
        yield "paragraph", "终止原因：" + report.stop_reason
    yield "table", (["轮次", "查询与子问题", "结果/失败"], [[str(q.round_number), q.query_text + "\n" + "、".join(q.subproblems), f"{q.total_results} / {q.error_category or '无'}"] for q in doc.queries])
    for section in doc.sections:
        yield "heading", (2, section.title)
        for claim in section.claims:
            yield "paragraph", f"[{ORIGIN_LABELS[claim.origin]}] {claim.text} [证据：{', '.join(claim.evidence_ids)}]"
    if not doc.sections:
        yield "paragraph", "尚未完成模型综合，以下为已保存的来源与分析。"
    yield "heading", (2, "纳入与排除")
    titles = {p.id: p.title for p in doc.papers + doc.excluded_papers}
    urls = {p.id: p.url for p in doc.papers + doc.excluded_papers}
    for selection in doc.selections:
        label = "纳入" if selection.relevant else "排除" if selection.reviewed else "未审阅"
        link = f"（{urls[selection.paper_id]}）" if selection.paper_id in urls else ""
        yield "paragraph", f"{titles.get(selection.paper_id, selection.paper_id)}{link}：{label}；{selection.reason}；子问题：{'、'.join(selection.subproblems) or '无'} [证据：{', '.join(selection.evidence_ids) or '无'}]"
    yield "heading", (2, "论文信息与实际阅读")
    analyzed = {a.paper_id: a for a in doc.analyses}
    for paper in doc.papers:
        yield "heading", (3, paper.title)
        yield "paragraph", f"{paper.id}；来源 {paper.url}；获取于 {paper.fetched_at.isoformat()}"
        for source in doc.sources:
            if source.paper_id == paper.id:
                yield "paragraph", f"保存的来源：{source.source_type.value}；快照 {source.source_text_id}；页 {source.page_number or '不适用'}；状态 {source.status}；{source.original_length}字符"
        analysis = analyzed.get(paper.id)
        if analysis is None:
            yield "paragraph", "未完成结构化提取。"
            continue
        yield "paragraph", f"分析状态：{analysis.status}" + (f"；{analysis.error}" if analysis.error else "")
        rows = []
        for field in analysis.fields:
            rows.append([FIELD_LABELS.get(field.field_name, field.field_name), field.value or MISSING_LABELS.get(field.missing_reason.value if field.missing_reason else '', '缺失'), ORIGIN_LABELS[field.origin] + ("；" + field.note if field.note else ''), ', '.join(field.evidence_ids) or '无'])
        yield "table", (["字段", "值/缺失", "性质与说明", "证据 ID"], rows)
        for experiment in analysis.experiments:
            yield "paragraph", "实验 " + experiment.id + "：" + "；".join(f"{key}={value if value is not None else '缺失'}" for key, value in experiment.model_dump(exclude={'id', 'paper_id', 'evidence_ids'}).items()) + " [证据：" + ', '.join(experiment.evidence_ids) + "]"
        for span in analysis.ranges:
            yield "paragraph", f"提供给模型：{span.source_type.value} / 快照 {span.source_text_id} / 页 {span.page_number or '不适用'} / 字符[{span.location_start},{span.location_end})，该快照共{span.original_length}字符"
    if doc.assessment:
        assessment = doc.assessment
        yield "heading", (2, "方法比较")
        for comparison in assessment.comparisons:
            yield "paragraph", f"{titles.get(comparison.left_paper_id, comparison.left_paper_id)} 与 {titles.get(comparison.right_paper_id, comparison.right_paper_id)}：{COMPARISON_LABELS[comparison.status]}"
            yield "paragraph", f"{comparison.metric or '指标缺失'}：{comparison.left_value or '缺失'} / {comparison.right_value or '缺失'}；{'；'.join(comparison.reasons)} [证据：{', '.join(comparison.evidence_ids)}]"
        if not assessment.comparisons:
            yield "paragraph", "没有同指标的跨论文实验记录。"
        yield "heading", (2, "覆盖与字段缺口")
        yield "paragraph", f"操作性规则：{assessment.rule}"
        for sub, papers in assessment.supporting_papers.items():
            yield "paragraph", f"{sub}：{len(papers)}个有依据的论文组；{', '.join(papers) or '无'}"
        for pid, (n, d) in assessment.field_counts.items():
            yield "paragraph", f"{titles.get(pid, pid)}：约定字段有证据 {n}/{d}"
        for pair in assessment.duplicate_candidates:
            yield "paragraph", f"疑似重复（未合并）：{' / '.join(pair)}"
    yield "heading", (2, "缺口、冲突与局限")
    for gap in report.gaps:
        yield "paragraph", gap
    yield "heading", (2, "证据与参考文献")
    for evidence in doc.evidence:
        yield "paragraph", f"证据 {evidence.id}；论文 {evidence.paper_id}；快照 {evidence.source_text_id}；页 {evidence.page_number or '不适用'}；字符[{evidence.location_start},{evidence.location_end})"
        yield "paragraph", evidence.quote
    for paper in doc.papers:
        yield "paragraph", f"{paper.title}；{', '.join(paper.authors) or '作者缺失'}；{paper.year or '年份缺失'}；{paper.url}；DOI：{paper.doi or '缺失'}"


def markdown(report):
    lines = []
    cell = lambda text: str(text).replace('\\', '\\\\').replace('|', '\\|').replace('\n', '<br>')
    for kind, value in blocks(report):
        if kind == "heading":
            level, title = value
            lines.append("#" * level + " " + title)
        elif kind == "paragraph":
            lines.append(value)
        else:
            headers, rows = value
            if rows:
                lines += ["| " + " | ".join(map(cell, headers)) + " |", "| " + " | ".join('---' for _ in headers) + " |"]
                lines += ["| " + " | ".join(map(cell, row)) + " |" for row in rows]
        lines.append("")
    return "\n".join(lines)


def xml_text(text):
    # PDF 原文中的控制字符不能直接写入 OOXML 或 Paragraph 标记。
    return re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "\ufffd", str(text))


def word(report):
    from docx import Document
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from docx.shared import Pt
    document = Document()
    style = document.styles['Normal']
    style.font.name, style.font.size = '宋体', Pt(10)
    style.element.get_or_add_rPr().get_or_add_rFonts().set(qn('w:eastAsia'), '宋体')
    for kind, value in blocks(report):
        if kind == "heading":
            level, text = value
            document.add_heading(xml_text(text), level=min(level, 3))
        elif kind == "paragraph":
            document.add_paragraph(xml_text(value))
        else:
            headers, rows = value
            if not rows:
                continue
            table = document.add_table(rows=1, cols=len(headers))
            table.style = 'Table Grid'
            for cell, text in zip(table.rows[0].cells, headers):
                cell.text = xml_text(text)
            repeat = OxmlElement('w:tblHeader')
            table.rows[0]._tr.get_or_add_trPr().append(repeat)
            for row in rows:
                for cell, text in zip(table.add_row().cells, row):
                    cell.text = xml_text(text)
    output = BytesIO()
    document.save(output)
    return output.getvalue()


@lru_cache(maxsize=1)
def pdf_font():
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    pdfmetrics.registerFont(TTFont('ScoutCJK', str(Path(__file__).parent / 'assets/fonts/ZCOOLXiaoWei-Regular.ttf')))
    return 'ScoutCJK'


def pdf(report):
    from reportlab.lib import colors
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.pagesizes import A4
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
    font = pdf_font()
    body = ParagraphStyle('body', fontName=font, fontSize=9, leading=14, wordWrap='CJK', spaceAfter=5)
    cell = ParagraphStyle('cell', parent=body, fontSize=8, leading=12)
    headings = {level: ParagraphStyle(f'h{level}', parent=body, fontSize=18 - level * 2, leading=22 - level * 2, spaceBefore=12, keepWithNext=True) for level in (1, 2, 3)}
    paragraph = lambda text, style: Paragraph(escape(xml_text(text)).replace('\n', '<br/>'), style)
    story = []
    for kind, value in blocks(report):
        if kind == "heading":
            level, text = value
            story.append(paragraph(text, headings[level]))
        elif kind == "paragraph":
            story.append(paragraph(value, body))
        else:
            headers, rows = value
            if not rows:
                continue
            table = Table([[paragraph(text, cell) for text in row] for row in [headers, *rows]],
                colWidths=[(A4[0] - 80) / len(headers)] * len(headers), repeatRows=1, splitInRow=1)
            table.setStyle(TableStyle([('VALIGN', (0,0), (-1,-1), 'TOP'), ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#eeeeee')),
                ('LINEBELOW', (0,0), (-1,0), .5, colors.black), ('BOTTOMPADDING', (0,0), (-1,-1), 6)]))
            story.extend([table, Spacer(1, 8)])
    output = BytesIO()
    SimpleDocTemplate(output, pagesize=A4, leftMargin=40, rightMargin=40, topMargin=40, bottomMargin=40, title=report.title).build(story)
    return output.getvalue()
