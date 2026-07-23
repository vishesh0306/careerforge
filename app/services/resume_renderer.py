from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape
from weasyprint import HTML

from app.schemas.resume import ResumeContent

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"

_env = Environment(
    loader=FileSystemLoader(str(TEMPLATES_DIR)),
    autoescape=select_autoescape(["html"]),
)


def render_resume_pdf(resume: ResumeContent) -> bytes:
    template = _env.get_template("resume.html")
    html_content = template.render(resume=resume)
    return HTML(string=html_content).write_pdf()
