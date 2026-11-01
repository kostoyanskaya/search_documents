"""Generates the small bilingual evaluation corpus (run once; the output
is committed)."""

import io
import pathlib

from docx import Document
from openpyxl import Workbook
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

OUT = pathlib.Path(__file__).parent / "corpus"
OUT.mkdir(exist_ok=True)

# --- Russian contract (docx)
d = Document()
d.add_heading("Договор поставки № 45", 1)
d.add_paragraph(
    "Настоящий договор заключён между ООО «Ромашка» (Поставщик) "
    "и АО «Вектор» (Покупатель)."
)
d.add_heading("Срок и оплата", 2)
d.add_paragraph(
    "Срок действия договора составляет 12 месяцев с даты подписания. "
    "Покупатель обязан оплатить поставленный товар "
    "в течение 30 календарных дней."
)
d.add_heading("Ответственность", 2)
d.add_paragraph(
    "За просрочку платежа начисляется неустойка в размере 0,1% от суммы "
    "долга за каждый день просрочки. "
    "Споры рассматриваются в Арбитражном суде города Москвы."
)
d.save(OUT / "ru_contract.docx")

# --- English lease (docx)
d = Document()
d.add_heading("Residential Lease Agreement", 1)
d.add_paragraph(
    "This lease is made between Northwind Properties (Landlord) "
    "and Alex Morgan (Tenant)."
)
d.add_heading("Term and rent", 2)
d.add_paragraph(
    "The lease term is 24 months. Monthly rent is 3,400 USD, payable on "
    "the first day of each month. "
    "A security deposit of 6,800 USD is required."
)
d.add_heading("Termination", 2)
d.add_paragraph(
    "Either party may terminate the lease with 60 days written notice. "
    "Pets are not allowed without written consent of the Landlord."
)
d.save(OUT / "en_lease.docx")

# --- Russian sales table (CSV, cp1251, ';' separator, decimal comma)
rows = [
    "Город;Дата;Выручка",
    "Москва;15.01.2023;1 250 000,50",
    "Казань;15.02.2023;980 000,00",
    "Москва;01.03.2023;(5 000,25)",
    "Санкт-Петербург;10.03.2023;640 000,00",
    "Казань;20.04.2023;310 000,00",
]
(OUT / "ru_sales.csv").write_bytes(("\n".join(rows) + "\n").encode("cp1251"))

# --- English employees (xlsx)
wb = Workbook()
ws = wb.active
ws.title = "Staff"
ws.append(["Name", "Department", "Salary", "Hired"])
for r in [
    ("Anna Lee", "Engineering", 5200, "2021-03-01"),
    ("Boris Petrov", "Engineering", 4800, "2022-07-15"),
    ("Clara Diaz", "Sales", 3900, "2020-11-20"),
    ("Dmitri Ivanov", "Sales", 4100, "2023-02-01"),
    ("Eva Novak", "HR", 3600, "2019-05-10"),
]:
    ws.append(list(r))
wb.save(OUT / "en_employees.xlsx")

# --- Mixed-language report (pdf): page 1 Russian, page 2 English
pdfmetrics.registerFont(
    TTFont("DejaVu", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")
)
buf = io.BytesIO()
c = canvas.Canvas(buf)
c.setFont("DejaVu", 12)
for text in (
    [
        "Годовой отчёт компании «Вектор» за 2023 год.",
        "Выручка составила 4 800 000 рублей, чистая прибыль — 520 000 рублей.",
        "Доля рынка компании выросла до 14 процентов.",
    ],
    [
        "Annual report of Vector Corp for 2023.",
        "Net revenue reached 52 million USD "
        "with an operating margin of 18 percent.",
        "The company employs 310 people in three offices.",
    ],
):
    for i, line in enumerate(text):
        c.drawString(60, 780 - i * 24, line)
    c.showPage()
c.save()
(OUT / "mixed_report.pdf").write_bytes(buf.getvalue())
print("corpus written:", sorted(p.name for p in OUT.iterdir()))
