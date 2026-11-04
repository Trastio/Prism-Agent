# 评估基建小包 · 四 sheet xlsx 渲染助手（复用 prism-api 同款 openpyxl，零新增 npm 依赖）
# 用法：python eval/render_xlsx.py <out.xlsx> <sheets.json>
# sheets.json: {"sheets":[{"name","header","rows","note"}]}
import json
import sys

from openpyxl import Workbook
from openpyxl.styles import Font
from openpyxl.utils import get_column_letter


def main(xlsx_path: str, sheets_json: str) -> None:
    with open(sheets_json, encoding="utf-8") as f:
        data = json.load(f)
    wb = Workbook()
    wb.remove(wb.active)
    bold = Font(bold=True)
    for s in data["sheets"]:
        name = s["name"] if s["name"] != "_boundary" else "适用边界"
        ws = wb.create_sheet(title=name[:31])  # openpyxl sheet 名上限 31 字符
        header = s.get("header") or []
        if header:
            ws.append(header)
            for c in ws[1]:
                c.font = bold
        for row in s.get("rows") or []:
            ws.append([str(x) if x is not None else "" for x in row])
        if s.get("note"):
            ws.append([])
            note_cell = ws.cell(row=ws.max_row + 1, column=1, value=f"> {s['note']}")
            note_cell.font = Font(italic=True)
        # 粗略列宽（按表头与首行内容，中文按 2 字符宽估）
        for i, h in enumerate(header, start=1):
            sample = [h] + [str(r[i - 1]) if i - 1 < len(r) else "" for r in (s.get("rows") or [])[:20]]
            width = min(60, max(8, max(len(x.encode("gbk", errors="ignore")) for x in sample) + 2))
            ws.column_dimensions[get_column_letter(i)].width = width
    wb.save(xlsx_path)
    print(f"xlsx 已写入: {xlsx_path}（{len(data['sheets'])} sheet）")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("用法: python render_xlsx.py <out.xlsx> <sheets.json>", file=sys.stderr)
        sys.exit(2)
    main(sys.argv[1], sys.argv[2])
