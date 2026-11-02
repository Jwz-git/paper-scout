"""PDF 解析子进程入口；只接收内存字节，不读取应用配置。"""

import io
import json
import re
import sys

from pypdf import PdfReader
from pypdf.errors import LimitReachedError, ParseError, PdfReadError


PDF_CONTENT_ERRORS = (PdfReadError, ParseError, LimitReachedError)


def parse_pdf(data: bytes, max_pages: int) -> dict:
    try:
        reader = PdfReader(io.BytesIO(data))
        total_pages = len(reader.pages)
    except PDF_CONTENT_ERRORS:
        return {"error": {"code": "parse_failed", "message": "PDF 文件损坏、加密或不可解析。"}}

    pages = []
    for index in range(min(total_pages, max_pages)):
        try:
            raw = reader.pages[index].extract_text() or ""
            text = re.sub(r"\n\s*\n", "\n\n", raw.replace("\x00", "")).strip()
            status = "ok" if text else "not_read"
        except PDF_CONTENT_ERRORS:
            text, status = "", "parse_failed"
        pages.append({"page_number": index + 1, "content": text, "status": status})
    return {"total_pages": total_pages, "pages": pages}


if __name__ == "__main__":
    # 未识别的异常让进程失败，调用者不得把程序故障伪装为论文缺失。
    result = parse_pdf(sys.stdin.buffer.read(), int(sys.argv[1]))
    sys.stdout.write(json.dumps(result, ensure_ascii=False))
