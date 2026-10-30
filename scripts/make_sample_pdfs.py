"""Make PDF versions of the sample documents (fake data) for upload demos. Needs: pip install fpdf2"""
import pathlib
from fpdf import FPDF

src = pathlib.Path(__file__).resolve().parents[1] / "sample_docs"
out = src / "pdf"
out.mkdir(exist_ok=True)
for f in sorted(src.glob("*.txt")):
    if f.name == "contract.txt":
        continue
    pdf = FPDF()
    pdf.add_page()
    lines = f.read_text().splitlines()
    pdf.set_font("Helvetica", "B", 18)
    pdf.cell(0, 12, lines[0], new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", size=12)
    for ln in lines[1:]:
        pdf.cell(0, 8, ln, new_x="LMARGIN", new_y="NEXT")
    pdf.output(str(out / (f.stem + ".pdf")))
    print("wrote", f.stem + ".pdf")
