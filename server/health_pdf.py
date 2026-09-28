"""PDF-сводка дневников для врача (reportlab). Кириллица — DejaVuSans из content/fonts.

Только факты: агрегаты за 30 дней, графики по дням и таблицы последних измерений
по включённым дневникам. Никаких оценок «норма/не норма» — правило кейса.
"""

import io
from datetime import datetime, timedelta, timezone
from pathlib import Path

from reportlab.graphics.charts.linecharts import HorizontalLineChart
from reportlab.graphics.shapes import Drawing, Rect, String
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from sqlalchemy.orm import Session

from core.db.models import HealthRecord, User
from core.schemas import HealthReportOut

FONT_DIR = Path(__file__).resolve().parents[1] / "content" / "fonts"
INK = colors.HexColor("#1B2433")
MUTED = colors.HexColor("#7A8699")
LINE = colors.HexColor("#E5E9F2")
BLUE = colors.HexColor("#006DF8")
RED = colors.HexColor("#DE2129")
GREEN = colors.HexColor("#22C55E")

_registered = False


def _register_fonts() -> None:
    global _registered
    if _registered:
        return
    pdfmetrics.registerFont(TTFont("DejaVu", str(FONT_DIR / "DejaVuSans.ttf")))
    pdfmetrics.registerFont(TTFont("DejaVu-Bold", str(FONT_DIR / "DejaVuSans-Bold.ttf")))
    _registered = True


def _styles() -> dict[str, ParagraphStyle]:
    return {
        "title": ParagraphStyle("title", fontName="DejaVu", fontSize=20, leading=24, textColor=INK),
        "sub": ParagraphStyle("sub", fontName="DejaVu", fontSize=9.5, leading=13, textColor=MUTED),
        "h2": ParagraphStyle("h2", fontName="DejaVu-Bold", fontSize=13, leading=17, spaceBefore=10, textColor=INK),
        "body": ParagraphStyle("body", fontName="DejaVu", fontSize=10, leading=14.5, textColor=INK),
        "muted": ParagraphStyle("muted", fontName="DejaVu", fontSize=8.5, leading=11.5, textColor=MUTED),
        "cell": ParagraphStyle("cell", fontName="DejaVu", fontSize=9, leading=12, textColor=INK),
        "cell-h": ParagraphStyle("cell-h", fontName="DejaVu-Bold", fontSize=9, leading=12, textColor=INK),
    }


def _num(v: float | None) -> str:
    return "—" if v is None else f"{v:.1f}".rstrip("0").rstrip(".").replace(".", ",")


def _daily_averages(rows: list[HealthRecord], getter) -> tuple[list[str], list[float | None]]:
    """Среднее за день для графика; возвращаем (подписи, значения)."""
    by_day: dict[str, tuple[str, list[float]]] = {}
    for r in rows:
        at = r.at.astimezone() if r.at.tzinfo else r.at
        key = at.strftime("%Y-%m-%d")
        v = getter(r)
        if v is None:
            continue
        label = at.strftime("%d.%m")
        if key in by_day:
            by_day[key][1].append(v)
        else:
            by_day[key] = (label, [v])
    ordered = sorted(by_day.items())
    return [lbl for _, (lbl, _) in ordered], [sum(vs) / len(vs) for _, (_, vs) in ordered]


def _fill_gaps(values: list[float | None]) -> list[float]:
    """reportlab требует числовые ряды одной длины: пропуски закрываем соседними точками."""
    known = [v for v in values if v is not None]
    if not known:
        return []
    out: list[float] = []
    last = known[0]
    for v in values:
        if v is not None:
            last = v
        out.append(last)
    return out


def _line_chart(
    labels: list[str],
    series: list[tuple[colors.Color, list[float]]],
    legend_items: list[tuple[colors.Color, str]] | None = None,
    width: float = 460,
    height: float = 150,
) -> Drawing | None:
    """Линейный график с сеткой; несколько рядов — на общей шкале."""
    if len(labels) < 2 or any(len(vals) != len(labels) for _, vals in series):
        return None
    legend_h = 16 if legend_items else 0
    drawing = Drawing(width, height + legend_h)
    chart = HorizontalLineChart()
    chart.x, chart.y = 30, 18 + legend_h
    chart.width, chart.height = width - 60, height - 38
    chart.data = [vals for _, vals in series]
    for i, (color, _) in enumerate(series):
        chart.lines[i].strokeColor = color
        chart.lines[i].strokeWidth = 1.6
    # подписи через одну-две, чтобы не слипались
    step = max(1, len(labels) // 8)
    chart.categoryAxis.categoryNames = [labels[i] if i % step == 0 else "" for i in range(len(labels))]
    chart.categoryAxis.labels.fontName = "DejaVu"
    chart.categoryAxis.labels.fontSize = 7
    chart.categoryAxis.labels.fillColor = MUTED
    chart.categoryAxis.strokeColor = LINE
    chart.categoryAxis.tickStrokeColor = LINE
    chart.valueAxis.gridStrokeColor = LINE
    chart.valueAxis.strokeColor = None
    chart.valueAxis.tickStrokeColor = None
    chart.valueAxis.labels.fontName = "DejaVu"
    chart.valueAxis.labels.fontSize = 7
    chart.valueAxis.labels.fillColor = MUTED
    chart.valueAxis.labelTextFormat = lambda v: f"{_num(v)}"
    drawing.add(chart)
    if legend_items:
        x = 30
        for color, label in legend_items:
            drawing.add(Rect(x, 2, 8, 8, fillColor=color, strokeColor=None))
            drawing.add(String(x + 12, 3, label, fontName="DejaVu", fontSize=8, fillColor=MUTED))
            x += 100
    return drawing


def _bp_chart(rows: list[HealthRecord]) -> Drawing | None:
    """Давление: систолическое, диастолическое и пульс на общей шкале."""
    ascending = list(reversed(rows))
    labels, sys_vals = _daily_averages(ascending, lambda r: r.systolic)
    if len([v for v in sys_vals if v is not None]) < 2:
        return None
    _, dia_vals = _daily_averages(ascending, lambda r: r.diastolic)
    _, pulse_vals = _daily_averages(ascending, lambda r: r.pulse)
    # reportlab требует числовые ряды одной длины: пропуски (например, пульс) закрываем соседними точками
    series = [
        (BLUE, _fill_gaps(sys_vals)),
        (RED, _fill_gaps(dia_vals)),
        (GREEN, _fill_gaps(pulse_vals)),
    ]
    return _line_chart(
        labels, series,
        legend_items=[(BLUE, "верхнее"), (RED, "нижнее"), (GREEN, "пульс")],
    )


def _simple_chart(rows: list[HealthRecord], getter, color: colors.Color) -> Drawing | None:
    ascending = list(reversed(rows))
    labels, values = _daily_averages(ascending, getter)
    return _line_chart(labels, [(color, values)])


def _record_line(r: HealthRecord) -> tuple[str, str]:
    at = r.at.astimezone() if r.at.tzinfo else r.at
    when = at.strftime("%d.%m.%Y %H:%M")
    context = " · ".join(x for x in (r.tag, r.meal_tag) if x)
    if r.type == "bp":
        value = f"{r.systolic}/{r.diastolic}" + (f", пульс {r.pulse}" if r.pulse is not None else "")
    elif r.type == "weight":
        value = f"{_num(r.weight_kg)} кг"
    elif r.type == "sugar":
        value = f"{_num(r.sugar_mmol)} ммоль/л"
    else:
        value = f"{r.mood}" + (f", боль {r.pain}/10" if r.pain is not None else "")
    if r.note:
        context = f"{context}; «{r.note}»" if context else f"«{r.note}»"
    return when, f"{value}{' · ' + context if context else ''}"


def build_health_pdf(db: Session, user: User, report: HealthReportOut, enabled: dict[str, bool]) -> bytes:
    """PDF сводки: агрегаты + графики + таблицы измерений по включённым дневникам."""
    _register_fonts()
    st = _styles()

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=16 * mm, rightMargin=16 * mm, topMargin=14 * mm, bottomMargin=14 * mm,
        title="МедМаршрут — сводка для врача",
    )
    now = datetime.now(timezone.utc).astimezone()
    period_start = (now - timedelta(days=30)).strftime("%d.%m.%Y")
    patient = f"{user.first_name} {user.last_name}".strip() or "Пациент"

    story: list = [
        Paragraph("МедМаршрут", st["title"]),
        Spacer(1, 2),
        Paragraph("Сводка для врача · только фактические измерения", st["sub"]),
        Spacer(1, 6),
        Paragraph(
            f"Период: {period_start} — {now.strftime('%d.%m.%Y')} · Пациент: {patient} · "
            f"Сформировано {now.strftime('%d.%m.%Y %H:%M')}",
            st["sub"],
        ),
        Spacer(1, 4),
    ]

    # ---- агрегаты ----
    agg: list[str] = []
    if report.bp_avg:
        agg.append(f"Давление: среднее <b>{report.bp_avg}</b> ({report.bp_count} изм."
                   + (f", пульс ~{report.pulse_avg} уд/мин" if report.pulse_avg else "") + ")")
    if report.weight_latest is not None:
        delta = report.weight_delta
        delta_txt = "" if delta is None or delta == 0 else f" ({'+' if delta > 0 else '−'}{_num(abs(delta))} кг за период)"
        agg.append(f"Вес: <b>{_num(report.weight_latest)} кг</b>{delta_txt} ({report.weight_count} изм.)")
    if report.sugar_avg:
        agg.append(f"Сахар крови: среднее <b>{_num(report.sugar_avg)} ммоль/л</b> ({report.sugar_count} изм.)")
    if agg:
        story.append(Paragraph("Показатели за период", st["h2"]))
        for a in agg:
            story.append(Paragraph(a, st["body"]))
        story.append(Spacer(1, 4))

    # ---- дневники: график + таблица ----
    if enabled.get("bp"):
        rows = (
            db.query(HealthRecord)
            .filter(HealthRecord.user_id == user.id, HealthRecord.type == "bp", HealthRecord.at >= now - timedelta(days=30))
            .order_by(HealthRecord.at.desc())
            .limit(30)
            .all()
        )
        if rows:
            story.append(Paragraph("Давление и пульс", st["h2"]))
            chart = _bp_chart(rows)
            if chart:
                story.append(chart)
                story.append(Spacer(1, 4))
            data = [["Дата", "Значение"]] + [_record_line(r) for r in rows]
            table = Table(data, colWidths=[34 * mm, None])
            table.setStyle(TableStyle([
                ("FONTNAME", (0, 0), (-1, 0), "DejaVu-Bold"),
                ("FONTNAME", (0, 1), (-1, -1), "DejaVu"),
                ("FONTSIZE", (0, 0), (-1, -1), 8.5),
                ("TEXTCOLOR", (0, 0), (-1, 0), MUTED),
                ("TEXTCOLOR", (0, 1), (-1, -1), INK),
                ("LINEBELOW", (0, 0), (-1, -2), 0.4, LINE),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ]))
            story.append(table)

    diary_specs = [
        ("weight", "Вес", lambda r: r.weight_kg, GREEN, lambda r: f"{_num(r.weight_kg)} кг"),
        ("sugar", "Сахар крови", lambda r: r.sugar_mmol, RED, lambda r: f"{_num(r.sugar_mmol)}"),
    ]
    for dtype, title, getter, color, fmt in diary_specs:
        if not enabled.get(dtype):
            continue
        rows = (
            db.query(HealthRecord)
            .filter(HealthRecord.user_id == user.id, HealthRecord.type == dtype, HealthRecord.at >= now - timedelta(days=30))
            .order_by(HealthRecord.at.desc())
            .limit(30)
            .all()
        )
        if not rows:
            continue
        story.append(Paragraph(title, st["h2"]))
        chart = _simple_chart(rows, getter, color)
        if chart:
            story.append(chart)
            story.append(Spacer(1, 4))
        data = [["Дата", "Значение"]] + [_record_line(r) for r in rows]
        table = Table(data, colWidths=[34 * mm, None])
        table.setStyle(TableStyle([
            ("FONTNAME", (0, 0), (-1, 0), "DejaVu-Bold"),
            ("FONTNAME", (0, 1), (-1, -1), "DejaVu"),
            ("FONTSIZE", (0, 0), (-1, -1), 8.5),
            ("TEXTCOLOR", (0, 0), (-1, 0), MUTED),
            ("TEXTCOLOR", (0, 1), (-1, -1), INK),
            ("LINEBELOW", (0, 0), (-1, -2), 0.4, LINE),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ]))
        story.append(table)

    # ---- лекарства ----
    if report.meds:
        story.append(Paragraph("Приём лекарств (за 30 дней)", st["h2"]))
        data = [["Курс", "Принято", "План", "%"]] + [
            [m.name, str(m.taken), str(m.planned), f"{m.pct}%"] for m in report.meds
        ]
        table = Table(data, colWidths=[None, 22 * mm, 22 * mm, 22 * mm])
        table.setStyle(TableStyle([
            ("FONTNAME", (0, 0), (-1, 0), "DejaVu-Bold"),
            ("FONTNAME", (0, 1), (-1, -1), "DejaVu"),
            ("FONTSIZE", (0, 0), (-1, -1), 8.5),
            ("TEXTCOLOR", (0, 0), (-1, 0), MUTED),
            ("TEXTCOLOR", (0, 1), (-1, -1), INK),
            ("LINEBELOW", (0, 0), (-1, -2), 0.4, LINE),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
        ]))
        story.append(table)

    # ---- заметки ----
    if report.notes:
        story.append(Paragraph("Заметки о самочувствии", st["h2"]))
        for n in report.notes:
            at = n.at.astimezone() if n.at.tzinfo else n.at
            story.append(Paragraph(f"<b>{at.strftime('%d.%m.%Y %H:%M')}</b> — «{n.note}»", st["body"]))

    if not (agg or report.meds or report.notes):
        story.append(Spacer(1, 8))
        story.append(Paragraph("За период записей нет — дневники пусты.", st["body"]))

    story.append(Spacer(1, 14))
    story.append(Paragraph(
        "Документ сформирован приложением «МедМаршрут» по записям пользователя. "
        "Содержит только фактические измерения без интерпретации; оценку выполняет врач.",
        st["muted"],
    ))

    doc.build(story)
    return buf.getvalue()
