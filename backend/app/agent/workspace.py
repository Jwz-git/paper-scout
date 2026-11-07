"""对话 agent 的工作区工具：检索、阅读、查找、记录、纳入判断、查看和报告。

外部请求只在这里发出，并经 budget.external 计数；工具失败抛出 ToolError，作为观察结果交回模型修正。"""
import re
from uuid import uuid4

from backend.app.adapters.arxiv import ArXivError
from backend.app.adapters.pdf import PdfError
from backend.app.analysis import FIELD_LABELS, compare_experiments, locate, normalized, paper_groups
from backend.app.domain.conversation import ChatCitation
from backend.app.domain.models import (
    Assessment, Evidence, Experiment, Extraction, PaperAnalysis, PaperSelection, ReadRange, Report,
    ReportClaim, ReportDocument, ReportSection, ReportSource, SearchQuery, SourceText, SourceType, TaskInput, utc_now,
)
from backend.app.reports import markdown

PAGE_CHARS = 8000
FIND_CONTEXT = 400
FIND_LIMIT = 8
MIN_QUOTE = 8
# 这些失败不保存为全文缺失，之后还可以重试下载。unsafe_url 取决于当时的 DNS 结果，换网络或代理设置后可能恢复。
TRANSIENT_PDF = {"download_timeout", "network_error", "dns_error", "unsafe_url"}
REPORT_RULE = "按论文统计六类基础字段中有原文证据的数量；不代表语义已核验"


class ToolError(Exception):
    """agent 可以修正的工具失败；不结束本轮。"""


def short(text, size=60):
    return text if len(text) <= size else text[:size] + "…"


def short_id(prefix):
    # 模型需要逐字复制这些标识，短标识更不容易抄错。
    return prefix + uuid4().hex[:12]


def pages_label(numbers):
    numbers, parts = sorted(set(numbers)), []
    for n in numbers:
        if parts and n == parts[-1][1] + 1:
            parts[-1][1] = n
        else:
            parts.append([n, n])
    return "、".join(str(a) if a == b else f"{a}–{b}" for a, b in parts)


def read_summary(analysis):
    if analysis is None or not analysis.ranges:
        return "未读"
    labels = ["摘要"] if any(r.source_type == SourceType.ABSTRACT for r in analysis.ranges) else []
    pages = [r.page_number for r in analysis.ranges if r.source_type == SourceType.FULLTEXT and r.page_number]
    if pages:
        labels.append("全文第 " + pages_label(pages) + " 页")
    return "；".join(labels) or "未读"


class Workspace:
    def __init__(self, db, run, arxiv, pdf, budget, lock, offline=False):
        self.db, self.run, self.arxiv, self.pdf = db, run, arxiv, pdf
        self.budget, self.lock, self.offline = budget, lock, offline

    # --- 资料 ---
    def papers(self):
        return {p.id: p for p in self.db.get_papers_by_run(self.run.id)}

    def paper(self, paper_id, allowed=None):
        if allowed is not None and paper_id != allowed:
            raise ToolError(f"这个子任务只能处理 {allowed}")
        paper = self.papers().get(paper_id)
        if paper is None:
            raise ToolError(f"工作区中没有论文 {paper_id}；先 search，或用 workspace 查看已有论文的 paper_id")
        return paper

    def selections(self):
        return {s.paper_id: s for s in self.db.list_selections(self.run.id, self.run.analysis_revision)}

    def analyses(self):
        return {a.paper_id: a for a in self.db.list_analyses(self.run.id, self.run.analysis_revision)}

    def sources(self, paper):
        texts = self.db.get_source_texts(paper.id, self.run.id)
        if not any(s.source_type == SourceType.ABSTRACT for s in texts):
            created = [
                SourceText(id=short_id("src_"), paper_id=paper.id, source_type=SourceType.METADATA, source_url=paper.url,
                           content=paper.model_dump_json(), fetched_at=paper.fetched_at),
                SourceText(id=short_id("src_"), paper_id=paper.id, source_type=SourceType.ABSTRACT, source_url=paper.url,
                           content=paper.abstract or "", status="ok" if paper.abstract else "not_available", fetched_at=paper.fetched_at),
            ]
            self.db.save_source_texts(created, self.run.id)
            texts += created
        return texts

    def describe(self, paper):
        return {"paper_id": paper.id, "title": paper.title, "authors": paper.authors[:6] + (["等"] if len(paper.authors) > 6 else []),
                "year": paper.year, "url": paper.url, "has_pdf": bool(paper.pdf_url)}

    def saved_fulltext(self, paper):
        # 旧记录里的暂时性失败不算全文状态，否则这篇论文再也不会重新下载。
        return [s for s in self.db.get_source_texts(paper.id, self.run.id)
                if s.source_type == SourceType.FULLTEXT and s.status not in TRANSIENT_PDF]

    def fulltext_status(self, paper):
        texts = self.saved_fulltext(paper)
        if not texts:
            return "未下载（用 read 指定页码下载）" if paper.pdf_url else "没有 PDF 地址"
        pages = [s for s in texts if s.page_number is not None]
        readable = [s.page_number for s in pages if s.status == "ok"]
        if not readable:
            return f"不可用（{next(s.status for s in texts if s.status != 'ok')}）"
        note = "；超过页数上限，只解析了前面部分" if any(s.status == "page_limit" for s in texts) else ""
        return f"已下载，共 {len(pages)} 页，可读第 {pages_label(readable)} 页{note}"

    def mark_read(self, paper, windows):
        """记录实际交给模型的原文范围；引文只能来自这些范围。"""
        current = self.analyses().get(paper.id) or PaperAnalysis(
            id="", run_id=self.run.id, paper_id=paper.id, analysis_revision=self.run.analysis_revision,
            round_number=self.run.current_round, status="completed")
        known = {(r.source_text_id, r.location_start, r.location_end) for r in current.ranges}
        added = []
        for source, start, end in windows:
            if (source.id, start, end) not in known:
                known.add((source.id, start, end))
                added.append(ReadRange(source_text_id=source.id, source_type=source.source_type, page_number=source.page_number,
                                       location_start=start, location_end=end, original_length=len(source.content)))
        if added:
            self.db.save_analysis(current.model_copy(update={"id": uuid4().hex, "ranges": current.ranges + added, "created_at": utc_now()}))

    async def fulltext(self, paper):
        """返回 {页码: 快照}；首次使用时下载并解析 PDF，同一时间只下载一篇。"""
        texts = self.saved_fulltext(paper)
        if not texts:
            if self.offline:
                raise ToolError("当前是“仅用已有资料”模式，这篇论文还没有下载全文")
            if not paper.pdf_url:
                raise ToolError("这篇论文没有可下载的 PDF 地址，只能读摘要")
            async with self.lock:
                texts = self.saved_fulltext(paper)
                if not texts:
                    if self.budget.fulltexts >= self.budget.max_fulltext:
                        raise ToolError(f"本轮全文下载已达上限 {self.budget.max_fulltext} 篇")
                    try:
                        texts = await self.pdf.download_and_extract(paper.pdf_url, paper.id, on_request=self.budget.external)
                    except PdfError as exc:
                        if exc.code in TRANSIENT_PDF:
                            raise ToolError(f"全文下载暂时失败（{exc.code}），可以稍后重试") from None
                        texts = [SourceText(id="", paper_id=paper.id, source_type=SourceType.FULLTEXT, source_url=paper.pdf_url,
                                            page_number=None, content="", status=exc.code)]
                    finally:
                        self.budget.fulltexts += 1
                    for text in texts:
                        text.id = short_id("src_")
                    self.db.save_source_texts(texts, self.run.id)
        pages = {s.page_number: s for s in texts if s.page_number is not None}
        if not any(s.status == "ok" for s in pages.values()):
            raise ToolError(f"全文不可用（{next((s.status for s in texts if s.status != 'ok'), 'not_read')}）；只能基于摘要")
        return pages

    # --- 工具 ---
    async def search(self, action):
        if self.offline:
            raise ToolError("当前是“仅用已有资料”模式，不能检索")
        query = action.query
        if action.start_year is not None or action.end_year is not None:
            start, end = action.start_year or 1800, action.end_year or utc_now().year
            if start > end:
                raise ToolError("start_year 不能大于 end_year")
            query = f"({query}) AND submittedDate:[{start}01010000 TO {end}12312359]"
        entry = SearchQuery(id=uuid4().hex, run_id=self.run.id, round_number=self.run.current_round, query_text=query,
                            raw_query=action.query, analysis_revision=self.run.analysis_revision)
        try:
            results = await self.arxiv.search(query, max_results=action.max_results, on_request=self.budget.external)
        except ArXivError as exc:
            entry.error_category = exc.code
            self.db.save_query(entry)
            raise ToolError(f"arXiv 检索失败（{exc.code}）") from None
        # 年份条件也作用于元数据；未知年份在有年份限制时不纳入。
        kept = [p for p in results if (action.start_year is None or p.year is not None and p.year >= action.start_year)
                and (action.end_year is None or p.year is not None and p.year <= action.end_year)]
        known, selections = self.papers(), self.selections()
        self.db.save_papers(kept, self.run.id, selected=False)
        entry.total_results = len(results)
        self.db.save_query(entry)
        def status(paper):
            if paper.id in selections:
                return "已纳入" if selections[paper.id].relevant else "已排除"
            return "已在候选中" if paper.id in known else "新"
        data = {"total": len(results), "kept": len(kept), "papers": [
            {"paper_id": p.id, "title": p.title, "year": p.year, "authors": p.authors[:3] + (["等"] if len(p.authors) > 3 else []),
             "abstract": short(p.abstract or "", 500), "status": status(p)} for p in kept]}
        new = sum(1 for p in kept if p.id not in known)
        return f"检索「{short(action.query, 80)}」：{len(results)} 条结果，新增 {new} 篇候选", data

    async def read(self, action, allowed=None, room=None):
        """room 是这一步还能返回的原文字符数；放不下的页不读、不记为已读。"""
        paper = self.paper(action.paper_id, allowed)
        sources = self.sources(paper)
        if not action.pages:
            abstract = next(s for s in sources if s.source_type == SourceType.ABSTRACT)
            if abstract.status == "ok":
                self.mark_read(paper, [(abstract, 0, len(abstract.content))])
            data = {"paper": self.describe(paper), "fulltext": self.fulltext_status(paper),
                    "abstract": {"source_text_id": abstract.id, "text": abstract.content} if abstract.status == "ok" else None}
            return f"读摘要：{short(paper.title)}", data
        pages = await self.fulltext(paper)
        shown, windows, unreadable, skipped, used = [], [], [], [], 0
        for number in action.pages:
            page = pages.get(number)
            if page is None or page.status != "ok":
                unreadable.append(number)
                continue
            text = page.content[:PAGE_CHARS]
            if room is not None and used + len(text) > room:
                skipped.append(number)
                continue
            used += len(text)
            windows.append((page, 0, len(text)))
            item = {"page": number, "source_text_id": page.id, "text": text}
            if len(text) < len(page.content):
                item["truncated"] = f"本页共 {len(page.content)} 字符，只显示前 {len(text)} 字符；其余部分用 find 定位"
            shown.append(item)
        self.mark_read(paper, windows)
        if not shown:
            if skipped:
                raise ToolError("这一步返回的原文已到上限，没有读取；下一步再读这些页")
            raise ToolError(f"请求的页不可读；{self.fulltext_status(paper)}")
        data = {"paper_id": paper.id, "total_pages": len(pages), "pages": shown}
        if unreadable:
            data["unreadable_pages"] = unreadable
        if skipped:
            data["skipped_pages"] = {"pages": skipped, "reason": "这一步返回的原文已到上限，这些页没有读取，下一步再读"}
        return f"读全文第 {pages_label([p['page'] for p in shown])} 页：{short(paper.title)}", data

    async def find(self, action, allowed=None):
        paper = self.paper(action.paper_id, allowed)
        texts = [s for s in self.sources(paper) if s.source_type == SourceType.ABSTRACT and s.status == "ok"]
        note = None
        try:
            pages = await self.fulltext(paper)
            texts += [pages[n] for n in sorted(pages) if pages[n].status == "ok"]
        except ToolError as exc:
            note = f"{exc}；只在摘要中查找"
        pattern = re.compile(re.escape(action.text), re.IGNORECASE)
        windows, total = [], 0
        for source in texts:
            for match in pattern.finditer(source.content):
                total += 1
                if len(windows) < FIND_LIMIT:
                    windows.append((source, max(0, match.start() - FIND_CONTEXT), min(len(source.content), match.end() + FIND_CONTEXT)))
        self.mark_read(paper, windows)
        data = {"paper_id": paper.id, "text": action.text, "total_matches": total, "matches": [
            {"page": s.page_number, "source_text_id": s.id, "location_start": start, "text": s.content[start:end]}
            for s, start, end in windows]}
        if total > len(windows):
            data["more"] = f"只返回前 {len(windows)} 处；换更具体的文字缩小范围"
        if note:
            data["note"] = note
        return f"在「{short(paper.title, 40)}」中查找「{short(action.text, 40)}」：{total} 处", data

    def cite(self, quote, paper, sources, ranges):
        source = sources.get(quote.source_text_id)
        if source is None:
            raise ToolError(f"来源 {quote.source_text_id} 不属于这篇论文；source_text_id 要从 read/find 的结果中复制")
        if len(normalized(quote.quote)[0]) < MIN_QUOTE:
            raise ToolError("引文太短，无法可靠定位；复制完整的句子或短语")
        spans = locate(source.content, quote.quote)
        if not spans:
            raise ToolError("引文与原文不一致，在该来源中找不到；请逐字复制，不要翻译、改写或拼接")
        if len(spans) > 1:
            raise ToolError("引文在该来源中出现多次，无法唯一定位；多复制一些前后文字")
        start, end = spans[0]
        if not any(r.location_start <= start and end <= r.location_end for r in ranges if r.source_text_id == source.id):
            raise ToolError("引文所在位置还没有读过；先 read 对应页或 find 到这段文字")
        return Evidence(id=short_id("ev_"), source_text_id=source.id, paper_id=paper.id, page_number=source.page_number,
                        quote=source.content[start:end], location_start=start, location_end=end)

    def note(self, action, allowed=None):
        paper = self.paper(action.paper_id, allowed)
        current = self.analyses().get(paper.id)
        if current is None or not current.ranges:
            raise ToolError("还没有读过这篇论文；先 read 或 find 再记录")
        sources = {s.id: s for s in self.db.get_source_texts(paper.id, self.run.id)}
        evidence, fields, experiments, saved, rejected = [], [], [], [], []
        for item in action.findings:
            try:
                refs = [self.cite(q, paper, sources, current.ranges) for q in item.citations]
            except ToolError as exc:
                rejected.append({"field_name": item.field_name, "error": str(exc)})
                continue
            evidence += refs
            fields.append(Extraction(id=uuid4().hex, run_id=self.run.id, paper_id=paper.id, field_name=item.field_name,
                value=item.value, missing_reason=item.missing_reason, origin=item.origin, is_inference=item.origin == "inference",
                note=item.note, evidence_ids=[e.id for e in refs]))
            saved.append({"field_name": item.field_name, "value": short(item.value, 300) if item.value else None,
                          "evidence_ids": [e.id for e in refs]})
        for item in action.experiments:
            label = " / ".join(v for v in (item.dataset, item.metric) if v) or "实验"
            try:
                refs = [self.cite(q, paper, sources, current.ranges) for q in item.citations]
            except ToolError as exc:
                rejected.append({"experiment": label, "error": str(exc)})
                continue
            evidence += refs
            experiments.append(Experiment(id=uuid4().hex, paper_id=paper.id, **item.model_dump(exclude={"citations"}),
                                          evidence_ids=[e.id for e in refs]))
            saved.append({"experiment": label, "value": " ".join(v for v in (item.value, item.unit) if v) or None,
                          "evidence_ids": [e.id for e in refs]})
        if not saved:
            raise ToolError("没有保存任何发现：" + "；".join(f"{r.get('field_name') or r.get('experiment')}：{r['error']}" for r in rejected))
        with self.db._get_connection():
            self.db.save_evidence(evidence)
            self.db.save_analysis(current.model_copy(update={"id": uuid4().hex, "fields": current.fields + fields,
                "experiments": current.experiments + experiments, "created_at": utc_now()}))
        data = {"saved": saved}
        if rejected:
            data["rejected"] = rejected
        summary = f"记录「{short(paper.title, 40)}」{len(saved)} 条发现" + (f"，{len(rejected)} 条引文未通过核对" if rejected else "")
        return summary, data

    def decide(self, action):
        papers = self.papers()
        unknown = [d.paper_id for d in action.decisions if d.paper_id not in papers]
        if unknown:
            raise ToolError("工作区中没有这些论文：" + "、".join(unknown))
        self.db.save_selections(self.run.id, [PaperSelection(paper_id=d.paper_id, analysis_revision=self.run.analysis_revision,
            relevant=d.include, reason=d.reason) for d in action.decisions])
        included = [d.paper_id for d in action.decisions if d.include]
        return (f"纳入 {len(included)} 篇，排除 {len(action.decisions) - len(included)} 篇",
                {"included": included, "excluded": [d.paper_id for d in action.decisions if not d.include]})

    def overview(self, limit=40):
        papers, selections, analyses = self.papers(), self.selections(), self.analyses()
        def row(paper):
            analysis = analyses.get(paper.id)
            return {"paper_id": paper.id, "title": short(paper.title, 120), "year": paper.year, "read": read_summary(analysis),
                    "findings": len(analysis.fields) + len(analysis.experiments) if analysis else 0}
        included = [row(p) for p in papers.values() if p.id in selections and selections[p.id].relevant]
        excluded = [{"paper_id": p.id, "title": short(p.title, 80), "reason": short(selections[p.id].reason, 120)}
                    for p in papers.values() if p.id in selections and not selections[p.id].relevant]
        candidates = [row(p) for p in papers.values() if p.id not in selections]
        queries = self.db.list_queries(self.run.id)
        report = self.db.get_report(self.run.id)
        return {"counts": {"included": len(included), "candidates": len(candidates), "excluded": len(excluded),
                           "evidence": len(self.db.run_evidence(self.run.id)), "queries": len(queries)},
                "included": included[:limit], "candidates": candidates[:limit], "excluded": excluded[:20],
                "recent_queries": [{"query": q.raw_query or q.query_text, "results": q.total_results, "error": q.error_category} for q in queries[-12:]],
                "latest_report": {"title": report.title, "created_at": report.created_at.isoformat()} if report else None}

    def view(self, action):
        if action.paper_id is None:
            return "查看工作区", self.overview()
        paper = self.paper(action.paper_id)
        abstract = next(s for s in self.sources(paper) if s.source_type == SourceType.ABSTRACT)
        analysis = self.analyses().get(paper.id)
        selection = self.selections().get(paper.id)
        evidence = {e.id: e for e in self.db.get_evidence(paper.id, self.run.id)}
        data = {"paper": self.describe(paper), "abstract": short(abstract.content, 1500), "fulltext": self.fulltext_status(paper),
                "decision": {"include": selection.relevant, "reason": selection.reason} if selection else None,
                "read": read_summary(analysis), "findings": [], "experiments": []}
        if analysis:
            data["findings"] = [{"field_name": f.field_name, "value": f.value, "missing_reason": f.missing_reason, "origin": f.origin,
                                 "evidence": [{"evidence_id": i, "page": evidence[i].page_number, "quote": short(evidence[i].quote, 200)}
                                              for i in f.evidence_ids if i in evidence]} for f in analysis.fields]
            data["experiments"] = [{**e.model_dump(exclude={"id", "paper_id"})} for e in analysis.experiments]
        return f"查看论文：{short(paper.title)}", data

    def report(self, action, limits):
        evidence = {e.id: e for e in self.db.run_evidence(self.run.id)}
        cited = [i for s in action.sections for c in s.claims for i in c.evidence_ids]
        unknown = sorted(set(cited) - set(evidence))
        if unknown:
            raise ToolError("这些证据标识不存在，报告未保存：" + "、".join(unknown[:10]) + "；证据标识来自 note 的返回结果或 workspace")
        papers, selections = self.papers(), self.selections()
        cited_papers = {evidence[i].paper_id for i in cited}
        refused = sorted(p for p in cited_papers if p in selections and not selections[p].relevant)
        if refused:
            raise ToolError("报告引用了已排除论文的证据：" + "、".join(refused) + "；先用 decide 改为纳入，或换用其他证据")
        automatic = [PaperSelection(paper_id=p, analysis_revision=self.run.analysis_revision, relevant=True,
                                    reason="报告引用了这篇论文的证据") for p in sorted(cited_papers - set(selections))]
        if automatic:
            self.db.save_selections(self.run.id, automatic)
            selections = self.selections()
        included = [p for p in papers.values() if p.id in selections and selections[p.id].relevant]
        excluded = [p for p in papers.values() if p.id in selections and not selections[p.id].relevant]
        analyses = [a for a in self.analyses().values() if a.paper_id in {p.id for p in included}]
        by_paper = {a.paper_id: a for a in analyses}
        groups, duplicates = paper_groups(included)
        gaps = list(action.gaps)
        for paper in included:
            analysis = by_paper.get(paper.id)
            if analysis is None or not analysis.ranges:
                gaps.append(f"{short(paper.title)}：尚未阅读，只有检索元数据")
            elif not any(r.source_type == SourceType.FULLTEXT for r in analysis.ranges):
                gaps.append(f"{short(paper.title)}：未读取全文，当前最多基于摘要")
        counts = {p.id: [len({f.field_name for f in (by_paper[p.id].fields if p.id in by_paper else [])
                              if f.field_name in FIELD_LABELS and f.value and f.evidence_ids}), len(FIELD_LABELS)] for p in included}
        assessment = Assessment(id=uuid4().hex, run_id=self.run.id, round_number=self.run.current_round,
            analysis_revision=self.run.analysis_revision, rule=REPORT_RULE, field_counts=counts, paper_groups=groups,
            duplicate_candidates=duplicates, comparisons=compare_experiments(analyses, groups), gaps=gaps, decision="report")
        referenced = set(cited) | {i for a in analyses for f in a.fields for i in f.evidence_ids} \
            | {i for a in analyses for e in a.experiments for i in e.evidence_ids}
        read = {r.source_text_id for a in analyses for r in a.ranges}
        sources = [s for p in included for s in self.db.get_source_texts(p.id, self.run.id)
                   if s.id in read or (s.source_type == SourceType.FULLTEXT and s.status != "ok")]
        document = ReportDocument(analysis_revision=self.run.analysis_revision, scope=TaskInput(topic=action.question),
            papers=included, excluded_papers=excluded, queries=self.db.list_queries(self.run.id),
            selections=list(selections.values()), analyses=analyses, assessment=assessment,
            sections=[ReportSection(title=s.title, claims=[ReportClaim(**c.model_dump()) for c in s.claims]) for s in action.sections],
            evidence=[e for i, e in evidence.items() if i in referenced],
            sources=[ReportSource(source_text_id=s.id, paper_id=s.paper_id, source_type=s.source_type, page_number=s.page_number,
                status=s.status, source_url=s.source_url, location_start=0, location_end=len(s.content), original_length=len(s.content)) for s in sources],
            total_calls=self.run.total_calls, model_calls=self.run.model_calls, token_usage=self.run.token_usage,
            execution_seconds=self.run.total_execution_seconds, limits=limits)
        report = Report(id=uuid4().hex, run_id=self.run.id, title=action.title, content_markdown="", document=document, gaps=gaps)
        report.content_markdown = markdown(report)
        with self.db._get_connection():
            self.db.save_report(report)
            self.db.save_assessment(assessment)
        claims = sum(len(s.claims) for s in action.sections)
        return (f"写入报告《{short(action.title, 60)}》：{len(included)} 篇论文，{claims} 条主张",
                {"report_id": report.id, "papers": len(included), "claims": claims, "gaps": gaps})

    def citations(self, ids):
        evidence = {e.id: e for e in self.db.run_evidence(self.run.id)}
        unknown = [i for i in ids if i not in evidence]
        if unknown:
            raise ToolError("这些证据标识不存在：" + "、".join(unknown[:10]) + "；只能引用 note 返回或 workspace 中的证据标识")
        sources = {s.id: s for s in self.db.run_source_texts(self.run.id)}
        result = []
        for i in dict.fromkeys(ids):
            item = evidence[i]
            source = sources[item.source_text_id]
            result.append(ChatCitation(source_text_id=item.source_text_id, paper_id=item.paper_id, run_id=self.run.id,
                source_type=source.source_type, source_url=source.source_url, page_number=item.page_number, quote=item.quote,
                location_start=item.location_start, location_end=item.location_end, evidence_id=item.id))
        return result
