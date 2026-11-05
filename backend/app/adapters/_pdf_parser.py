"""PDF 解析子进程入口；只接收内存字节，不读取应用配置。"""

import io
import json
import re
import sys

from pypdf import PdfReader


def parse_pdf(data: bytes, max_pages: int) -> dict:
    # PDF 是不可信外部输入；pypdf 对畸形文件会抛出各类内置异常，均按该文件解析失败处理。
    try:
        reader = PdfReader(io.BytesIO(data))
        total_pages = len(reader.pages)
    except Exception:
        return {"error": {"code": "parse_failed", "message": "PDF 文件损坏、加密或不可解析。"}}

    pages = []
    for index in range(min(total_pages, max_pages)):
        try:
            raw = reader.pages[index].extract_text() or ""
            text = re.sub(r"\n\s*\n", "\n\n", raw.replace("\x00", "")).strip()
            status = "ok" if text else "not_read"
        except Exception:
            text, status = "", "parse_failed"
        pages.append({"page_number": index + 1, "content": text, "status": status})
    return {"total_pages": total_pages, "pages": pages}


if __name__ == "__main__":
    result = parse_pdf(sys.stdin.buffer.read(), int(sys.argv[1]))
    sys.stdout.write(json.dumps(result, ensure_ascii=False))
