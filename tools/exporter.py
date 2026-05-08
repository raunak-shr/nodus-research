import os
from pathlib import Path

import markdown
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.units import inch
import markdown
from bs4 import BeautifulSoup
from langchain_core.tools import tool

@tool
def export_report(report_md_content:str, filename: str)->str:
    """
    Exports a report to PDF format.
    """
    html = markdown.markdown(report_md_content)
    soup = BeautifulSoup(html, 'html.parser')
    story = []

    styles = getSampleStyleSheet()
    heading_style = ParagraphStyle('Heading', parent=styles['Heading1'], spaceAfter=12)
    body_style = styles['BodyText']
    filename = filename.replace(".pdf", "")
    project_root = Path("tools/data/reports/filename.pdf").resolve().parents[4]
    new_file_path = os.path.join(project_root, "data", "reports", f"{filename}.pdf")
    # if os.path.exists(new_file_path):
    #     return "A file with same name already exists: {}".format(filename)
    try:
        for tag in soup.contents:
            if tag.name == 'h1':
                story.append(Paragraph(f"<b>{tag.text}</b>", heading_style))
            elif tag.name == 'h2':
                story.append(Paragraph(f"<b>{tag.text}</b>", styles['Heading2']))
            elif tag.name == 'p':
                story.append(Paragraph(tag.text, body_style))
            elif tag.name == 'ul':
                for li in tag.find_all('li'):
                    story.append(Paragraph(f"• {li.text}", body_style))
            elif tag.name == 'ol':
                for idx, li in enumerate(tag.find_all('li'), 1):
                    story.append(Paragraph(f"{idx}. {li.text}", body_style))

        story.append(Spacer(1, 0.2 * inch))
        doc = SimpleDocTemplate(new_file_path, pagesize=LETTER)
        doc.build(story)

        return "PDF Exported successfully!: {}".format(new_file_path)
    except Exception as e:
        return "Error exporting PDF: {}".format(str(e))

def main():
    report_content = (
        "# Research Report\n\n"
        "This is a **Markdown** document with some data.\n\n"
        "- Fact 1\n"
        "- Fact 2"
    )

    result = export_report.invoke({"report_md_content": report_content,
                                   "filename": "report.pdf"})
    print(result)

if __name__=="__main__":
    main()