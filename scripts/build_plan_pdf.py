#!E:/George/projects/apps/polymarket/.tools/python/python.exe
from __future__ import annotations

import subprocess
import sys
from datetime import datetime
from pathlib import Path

import pdfplumber
from pypdf import PdfReader
from reportlab.lib import colors
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import ParagraphStyle, StyleSheet1, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / 'output' / 'pdf'
TMP_DIR = ROOT / 'tmp' / 'pdfs'
PDF_PATH = OUTPUT_DIR / 'ibkr-canada-picks-and-shovels-plan.pdf'
TEXT_PATH = TMP_DIR / 'ibkr-canada-picks-and-shovels-plan.txt'
PNG_PREFIX = TMP_DIR / 'ibkr-canada-picks-and-shovels-plan-page'
POPLER_PATH = ROOT / '.tools' / 'poppler' / 'poppler-24.08.0' / 'Library' / 'bin' / 'pdftoppm.exe'
TITLE = 'IBKR Canada Picks-and-Shovels Investor MVP Plan'

PALETTE = {
    'bg': colors.HexColor('#f4f1ea'),
    'paper': colors.HexColor('#fffdf8'),
    'ink': colors.HexColor('#18212b'),
    'muted': colors.HexColor('#5d6b78'),
    'line': colors.HexColor('#c8d0d8'),
    'primary': colors.HexColor('#16324a'),
    'accent': colors.HexColor('#c65d3d'),
    'blue_soft': colors.HexColor('#e5eef5'),
    'sand_soft': colors.HexColor('#efe3d1'),
    'rose_soft': colors.HexColor('#f7e3dc'),
    'mint_soft': colors.HexColor('#e4f1ea'),
}

SUMMARY_ITEMS = [
    'Use Interactive Brokers Canada for a single-user investing app, with automation limited to US-listed stocks and ETFs.',
    'Strategy focuses on differentiated suppliers to fast-growing spend waves, not the eventual downstream winner.',
    'V1 theme is AI picks-and-shovels: compute, networking, power/cooling, foundry/packaging, and related infrastructure bottlenecks.',
    'The model does not use RSI, MACD, moving averages, beta screens, or chart patterns.',
    'Rollout stays conservative: IBKR paper first, then small live positions behind hard limits.',
]

QUALIFY_ITEMS = [
    'Company sells an indispensable input into a specific growth wave.',
    'Demand rises if multiple downstream competitors keep spending.',
    'Business has bottleneck positioning, pricing power, or hard-to-replace differentiation.',
    'Official filings or earnings materials show accelerating demand, orders, backlog, guidance, or revenue tied to the theme.',
]

REJECT_ITEMS = [
    'Canadian-listed securities, because IBKR API automation is restricted for Canadian residents on Canadian marketplaces.',
    'Generic necessities without a measurable new incremental growth driver.',
    'Commodity-like businesses where pricing is not differentiated.',
    'Theses built mainly on technical indicators or market beta.',
]

SCORE_CARDS = [
    ('Theme linkage', 'Direct', 'Clear exposure to the spend wave rather than broad macro demand.'),
    ('Multi-winner exposure', 'Required', 'Company should benefit if several downstream players spend more.'),
    ('Growth proof', 'Documented', 'Use filings, earnings, guidance, orders, and backlog signals.'),
    ('Listing rule', 'US only', 'Canadian-listed instruments are rejected before execution.'),
]

SEED_EXAMPLES = [
    'NVDA: AI compute bottleneck',
    'ANET: AI networking and cluster fabric',
    'VRT: data center power and cooling',
    'AVGO: AI networking and custom silicon',
    'TSM: US-listed ADR with foundry and advanced packaging leverage',
]

IMPLEMENTATION_ITEMS = {
    'Broker and market access': [
        'Use Interactive Brokers Canada as the live broker and primary brokerage integration.',
        'Use IBKR Web API or TWS API for account state, orders, positions, and execution events.',
        'Constrain the investable universe to US-listed securities only.',
        'Apply a hard reject_canadian_listing rule before any live order can be generated.',
    ],
    'Research and strategy engine': [
        'Define ThemeDefinition objects with theme_name, spend_driver, enablement_layer, winner_agnostic_case, and disqualifiers.',
        'Score each company on theme_linkage, multi_winner_exposure, bottleneck_or_differentiation, growth_proof, management_proof, and valuation_sanity.',
        'Apply hard reject_ubiquity, reject_commodity, and reject_non_us_listing rules before buy decisions.',
    ],
    'Research pipeline': [
        'Ingest investor-relations releases, earnings slides, annual reports, 10-K/10-Q/20-F filings, and market news.',
        'Normalize evidence into source_type, publish_date, metric, quoted_growth, theme_relevance, and confidence records.',
        'Maintain a manually approved seed universe of 10 to 20 US-listed names.',
    ],
    'Portfolio and persistence': [
        'V1 is long-only, whole-share only, stocks/ETFs only, regular-hours only, no options, no shorting, and no margin.',
        'Dashboard pages cover themes, approved universe, evidence, company scores, positions, decisions, broker health, and alerts.',
        'SQLite stores themes, companies, evidence records, scores, order intents, fills, positions, alerts, and audit logs.',
    ],
}

FLOW_STRIP = [
    ('Theme', 'Define the spend wave'),
    ('Evidence', 'Read filings and IR material'),
    ('Score', 'Apply the strategy rubric'),
    ('Broker gate', 'Reject Canadian listings'),
    ('Execute', 'Paper or capped live orders'),
]

INTERFACE_ITEMS = {
    'Core interfaces': [
        'BrokerAdapter: get_account(), get_clock(), list_positions(), submit_order(), cancel_order(), list_open_orders(), stream_order_updates()',
        'ResearchSource: fetch_items(company), normalize_item(), extract_evidence()',
        'ThemeEngine: score_company(symbol, theme_id) -> ThemeCompanyScore',
        'DecisionEngine: build_position_actions(theme_id) -> list[Decision]',
        'RiskEngine: evaluate(intent, portfolio_state) -> Allow | Block(reason[])',
    ],
    'Strategy types': [
        'ThemeDefinition: theme thesis, spend driver, enablement layer, winner-agnostic case, disqualifiers',
        'EvidenceRecord: source metadata plus extracted growth/order/backlog/guidance evidence',
        'ThemeCompanyScore: normalized scorecard with component scores and rejection reasons',
        'Decision: symbol, side, target_weight, max_notional, thesis, invalidation_rules, review_date',
    ],
}

LIMIT_ITEMS = [
    'Bankroll cap: $250',
    'Max order size: min($25, 10% of bankroll)',
    'Max 5 open names',
    'Max 2 names per theme',
    'Max daily loss: $25',
    'Block illiquid names, non-US-listed names, names below the minimum price floor, or names that fail thesis-quality checks',
]

TEST_ITEMS = [
    'Verify technical indicators and beta inputs are never read by the decision engine.',
    'Test each score axis plus hard reject_ubiquity, reject_commodity, and reject_non_us_listing rules.',
    'Positive-case tests for approved picks-and-shovels names when demand evidence accelerates.',
    'Negative-case tests for Canadian-listed symbols and broad commodity or generic-necessity businesses.',
    'Paper-mode integration: new evidence -> score update -> decision -> risk pass/block -> simulated IBKR fill -> dashboard update.',
]

ASSUMPTION_ITEMS = [
    'Personal-use app, not multi-user SaaS.',
    'Seed theme for v1 is AI picks-and-shovels, not a broad market allocator.',
    'The investable universe is restricted to US-listed stocks and ETFs because the user is in Canada.',
    'Starter examples include NVDA, ANET, VRT, AVGO, and TSM.',
]

REQUIRED_TEXT = [
    'Summary',
    'Implementation Changes',
    'Public Interfaces / Types',
    'Test Plan',
    'Assumptions / Defaults',
]


def build_styles() -> StyleSheet1:
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name='HeroTitle', parent=styles['Title'], fontName='Helvetica-Bold', fontSize=24, leading=28, textColor=colors.white, spaceAfter=8))
    styles.add(ParagraphStyle(name='HeroSubtitle', parent=styles['BodyText'], fontName='Helvetica', fontSize=11.0, leading=14.2, textColor=PALETTE['ink'], spaceAfter=10))
    styles.add(ParagraphStyle(name='SectionKicker', parent=styles['BodyText'], fontName='Helvetica-Bold', fontSize=8.2, leading=10, textColor=PALETTE['accent'], spaceAfter=5))
    styles.add(ParagraphStyle(name='SectionTitle', parent=styles['Heading1'], fontName='Helvetica-Bold', fontSize=18, leading=21, textColor=PALETTE['primary'], spaceAfter=8))
    styles.add(ParagraphStyle(name='Body', parent=styles['BodyText'], fontName='Helvetica', fontSize=10.0, leading=13.0, textColor=PALETTE['ink'], spaceAfter=5))
    styles.add(ParagraphStyle(name='SmallBody', parent=styles['BodyText'], fontName='Helvetica', fontSize=8.9, leading=11.1, textColor=PALETTE['ink'], spaceAfter=4))
    styles.add(ParagraphStyle(name='PanelTitle', parent=styles['Heading3'], fontName='Helvetica-Bold', fontSize=11, leading=13, textColor=PALETTE['primary'], spaceAfter=7))
    styles.add(ParagraphStyle(name='CardLabel', parent=styles['BodyText'], fontName='Helvetica-Bold', fontSize=8.2, leading=10, textColor=PALETTE['accent'], spaceAfter=3))
    styles.add(ParagraphStyle(name='CardValue', parent=styles['BodyText'], fontName='Helvetica-Bold', fontSize=12.8, leading=14.3, textColor=PALETTE['primary'], spaceAfter=4))
    styles.add(ParagraphStyle(name='PlanBullet', parent=styles['BodyText'], fontName='Helvetica', fontSize=9.4, leading=12.0, leftIndent=12, bulletIndent=0, textColor=PALETTE['ink'], spaceAfter=3))
    styles.add(ParagraphStyle(name='PlanBulletSmall', parent=styles['BodyText'], fontName='Helvetica', fontSize=8.6, leading=10.7, leftIndent=10, bulletIndent=0, textColor=PALETTE['ink'], spaceAfter=2))
    return styles


def bullet_paragraphs(items: list[str], style: ParagraphStyle) -> list[Paragraph]:
    return [Paragraph(item, style, bulletText='-') for item in items]


def panel(title: str, content: list, width: float, background) -> Table:
    box = Table([[[Paragraph(title, STYLES['PanelTitle']), *content]]], colWidths=[width])
    box.setStyle(
        TableStyle(
            [
                ('BACKGROUND', (0, 0), (-1, -1), background),
                ('BOX', (0, 0), (-1, -1), 0.8, PALETTE['line']),
                ('TOPPADDING', (0, 0), (-1, -1), 9),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 9),
                ('LEFTPADDING', (0, 0), (-1, -1), 11),
                ('RIGHTPADDING', (0, 0), (-1, -1), 11),
            ]
        )
    )
    return box


def metric_card(label: str, value: str, detail: str, width: float, height: float) -> Table:
    card = Table([[[Paragraph(label, STYLES['CardLabel']), Paragraph(value, STYLES['CardValue']), Paragraph(detail, STYLES['SmallBody'])]]], colWidths=[width], rowHeights=[height])
    card.setStyle(
        TableStyle(
            [
                ('BACKGROUND', (0, 0), (-1, -1), PALETTE['paper']),
                ('BOX', (0, 0), (-1, -1), 0.8, PALETTE['line']),
                ('TOPPADDING', (0, 0), (-1, -1), 10),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
                ('LEFTPADDING', (0, 0), (-1, -1), 10),
                ('RIGHTPADDING', (0, 0), (-1, -1), 10),
            ]
        )
    )
    return card


def architecture_card(title: str, detail: str, width: float) -> Table:
    card = Table([[Paragraph(f'<b>{title}</b><br/>{detail}', STYLES['SmallBody'])]], colWidths=[width])
    card.setStyle(
        TableStyle(
            [
                ('BACKGROUND', (0, 0), (-1, -1), PALETTE['paper']),
                ('BOX', (0, 0), (-1, -1), 0.8, PALETTE['line']),
                ('TOPPADDING', (0, 0), (-1, -1), 8),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
                ('LEFTPADDING', (0, 0), (-1, -1), 8),
                ('RIGHTPADDING', (0, 0), (-1, -1), 8),
            ]
        )
    )
    return card


def build_title_page(doc: SimpleDocTemplate) -> list:
    card_width = (doc.width - 24) / 3
    return [
        Spacer(1, 1.55 * inch),
        Paragraph(TITLE, STYLES['HeroTitle']),
        Paragraph(
            'Designed review draft for a Canadian setup that automates only US-listed picks-and-shovels names through IBKR.',
            STYLES['HeroSubtitle'],
        ),
        Spacer(1, 0.3 * inch),
        Table(
            [[
                metric_card('Review date', datetime.now().strftime('%B %d, %Y'), 'Local build artifact generated for review.', (doc.width - 12) / 2, 0.7 * inch),
                metric_card('Project shape', 'Canada + IBKR MVP', 'Single-user app, local runtime, future broker abstraction retained.', (doc.width - 12) / 2, 0.7 * inch),
            ]],
            colWidths=[(doc.width - 12) / 2, (doc.width - 12) / 2],
            style=[('VALIGN', (0, 0), (-1, -1), 'TOP')],
        ),
        Spacer(1, 0.18 * inch),
        panel(
            'Review purpose',
            [
                Paragraph(
                    'This version adapts the strategy for a Canadian resident. The system uses IBKR and treats Canadian-listed securities as out of scope for API-driven trading.',
                    STYLES['Body'],
                )
            ],
            doc.width,
            PALETTE['sand_soft'],
        ),
        Spacer(1, 0.18 * inch),
        Paragraph('AT A GLANCE', STYLES['SectionKicker']),
        Paragraph('MVP decisions already locked', STYLES['SectionTitle']),
        Table(
            [
                [
                    metric_card('Broker', 'IBKR Canada', 'Use Interactive Brokers Canada for paper and live automation.', card_width, 1.12 * inch),
                    metric_card('Market access', 'US-listed only', 'Canadian-listed products are rejected before execution.', card_width, 1.12 * inch),
                    metric_card('Theme', 'AI infrastructure', 'Compute, networking, power/cooling, and foundry bottlenecks.', card_width, 1.12 * inch),
                ],
                [
                    metric_card('Signals', 'No technicals', 'No RSI, MACD, moving averages, or beta screens.', card_width, 1.12 * inch),
                    metric_card('Account', 'Long-only v1', 'Whole shares only, no margin, no shorting, no options.', card_width, 1.12 * inch),
                    metric_card('Cadence', 'Event-driven', 'Re-rank on filings, earnings, and capex signals.', card_width, 1.12 * inch),
                ],
            ],
            colWidths=[card_width, card_width, card_width],
            style=[('VALIGN', (0, 0), (-1, -1), 'TOP')],
        ),
    ]


def build_strategy_page(doc: SimpleDocTemplate) -> list:
    half = (doc.width - 12) / 2
    card_width = (doc.width - 18) / 2
    return [
        Spacer(1, 0.28 * inch),
        Paragraph('STRATEGY LOGIC', STYLES['SectionKicker']),
        Paragraph('Summary', STYLES['SectionTitle']),
        *bullet_paragraphs(SUMMARY_ITEMS, STYLES['PlanBullet']),
        Spacer(1, 0.08 * inch),
        Table(
            [[
                panel('What qualifies', bullet_paragraphs(QUALIFY_ITEMS, STYLES['PlanBulletSmall']), half, PALETTE['blue_soft']),
                panel('What fails the strategy', bullet_paragraphs(REJECT_ITEMS, STYLES['PlanBulletSmall']), half, PALETTE['rose_soft']),
            ]],
            colWidths=[half, half],
            style=[('VALIGN', (0, 0), (-1, -1), 'TOP')],
        ),
        Spacer(1, 0.1 * inch),
        Table(
            [
                [metric_card(*SCORE_CARDS[0], card_width, 0.88 * inch), metric_card(*SCORE_CARDS[1], card_width, 0.88 * inch)],
                [metric_card(*SCORE_CARDS[2], card_width, 0.88 * inch), metric_card(*SCORE_CARDS[3], card_width, 0.88 * inch)],
            ],
            colWidths=[card_width, card_width],
            style=[('VALIGN', (0, 0), (-1, -1), 'TOP')],
        ),
        Spacer(1, 0.1 * inch),
        panel('Starter US-listed basket', bullet_paragraphs(SEED_EXAMPLES, STYLES['PlanBulletSmall']), doc.width, PALETTE['sand_soft']),
    ]


def build_implementation_page(doc: SimpleDocTemplate) -> list:
    strip_width = (doc.width - 16) / 5
    half = (doc.width - 12) / 2
    return [
        Spacer(1, 0.28 * inch),
        Paragraph('SYSTEM SHAPE', STYLES['SectionKicker']),
        Paragraph('Implementation Changes', STYLES['SectionTitle']),
        Paragraph(
            'The engine reads official company material, extracts theme-linked growth evidence, scores a curated US-listed universe, enforces the Canadian market-access rule, and only then hands approved trades to IBKR.',
            STYLES['Body'],
        ),
        Table(
            [[architecture_card(title, detail, strip_width) for title, detail in FLOW_STRIP]],
            colWidths=[strip_width] * 5,
            style=[('VALIGN', (0, 0), (-1, -1), 'TOP')],
        ),
        Spacer(1, 0.14 * inch),
        Table(
            [[
                panel('Broker and market access', bullet_paragraphs(IMPLEMENTATION_ITEMS['Broker and market access'], STYLES['PlanBulletSmall']), half, PALETTE['blue_soft']),
                panel('Research and strategy engine', bullet_paragraphs(IMPLEMENTATION_ITEMS['Research and strategy engine'], STYLES['PlanBulletSmall']), half, PALETTE['mint_soft']),
            ]],
            colWidths=[half, half],
            style=[('VALIGN', (0, 0), (-1, -1), 'TOP')],
        ),
        Spacer(1, 0.12 * inch),
        Table(
            [[
                panel('Research pipeline', bullet_paragraphs(IMPLEMENTATION_ITEMS['Research pipeline'], STYLES['PlanBulletSmall']), half, PALETTE['rose_soft']),
                panel('Portfolio and persistence', bullet_paragraphs(IMPLEMENTATION_ITEMS['Portfolio and persistence'], STYLES['PlanBulletSmall']), half, PALETTE['sand_soft']),
            ]],
            colWidths=[half, half],
            style=[('VALIGN', (0, 0), (-1, -1), 'TOP')],
        ),
    ]


def build_controls_page(doc: SimpleDocTemplate) -> list:
    half = (doc.width - 12) / 2
    return [
        Spacer(1, 0.28 * inch),
        Paragraph('INTERFACES AND QA', STYLES['SectionKicker']),
        Paragraph('Public Interfaces / Types', STYLES['SectionTitle']),
        Table(
            [[
                panel('Core interfaces', bullet_paragraphs(INTERFACE_ITEMS['Core interfaces'], STYLES['PlanBulletSmall']), half, PALETTE['paper']),
                panel('Strategy types', bullet_paragraphs(INTERFACE_ITEMS['Strategy types'], STYLES['PlanBulletSmall']), half, PALETTE['paper']),
            ]],
            colWidths=[half, half],
            style=[('VALIGN', (0, 0), (-1, -1), 'TOP')],
        ),
        Spacer(1, 0.1 * inch),
        panel('Default v1 limits', bullet_paragraphs(LIMIT_ITEMS, STYLES['PlanBulletSmall']), doc.width, PALETTE['sand_soft']),
        Spacer(1, 0.1 * inch),
        Table(
            [[
                panel('Test Plan', bullet_paragraphs(TEST_ITEMS, STYLES['PlanBulletSmall']), half, PALETTE['blue_soft']),
                panel('Assumptions / Defaults', bullet_paragraphs(ASSUMPTION_ITEMS, STYLES['PlanBulletSmall']), half, PALETTE['rose_soft']),
            ]],
            colWidths=[half, half],
            style=[('VALIGN', (0, 0), (-1, -1), 'TOP')],
        ),
    ]


def draw_first_page(canvas, doc) -> None:
    width, height = LETTER
    canvas.saveState()
    canvas.setFillColor(PALETTE['bg'])
    canvas.rect(0, 0, width, height, fill=1, stroke=0)
    canvas.setFillColor(PALETTE['primary'])
    canvas.rect(0, height - 210, width, 210, fill=1, stroke=0)
    canvas.setFillColor(PALETTE['accent'])
    canvas.rect(0, height - 210, width * 0.34, 12, fill=1, stroke=0)
    canvas.setFillColor(colors.HexColor('#254865'))
    canvas.rect(width * 0.69, height - 120, width * 0.31, 120, fill=1, stroke=0)
    canvas.setFillColor(PALETTE['muted'])
    canvas.setFont('Helvetica', 8)
    canvas.drawString(doc.leftMargin, 24, TITLE)
    canvas.drawRightString(width - doc.rightMargin, 24, f'Page {doc.page}')
    canvas.restoreState()


def draw_later_pages(canvas, doc) -> None:
    width, height = LETTER
    canvas.saveState()
    canvas.setFillColor(PALETTE['bg'])
    canvas.rect(0, 0, width, height, fill=1, stroke=0)
    canvas.setStrokeColor(PALETTE['line'])
    canvas.setLineWidth(0.8)
    canvas.line(doc.leftMargin, height - 42, width - doc.rightMargin, height - 42)
    canvas.setFillColor(PALETTE['accent'])
    canvas.rect(doc.leftMargin, height - 44, 80, 2.5, fill=1, stroke=0)
    canvas.setFillColor(PALETTE['muted'])
    canvas.setFont('Helvetica', 8)
    canvas.drawString(doc.leftMargin, 24, TITLE)
    canvas.drawRightString(width - doc.rightMargin, 24, f'Page {doc.page}')
    canvas.restoreState()


def build_pdf() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    TMP_DIR.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(
        str(PDF_PATH),
        pagesize=LETTER,
        leftMargin=0.7 * inch,
        rightMargin=0.7 * inch,
        topMargin=0.62 * inch,
        bottomMargin=0.55 * inch,
        title=TITLE,
        author='OpenAI Codex',
    )
    story = []
    story.extend(build_title_page(doc))
    story.append(PageBreak())
    story.extend(build_strategy_page(doc))
    story.append(PageBreak())
    story.extend(build_implementation_page(doc))
    story.append(PageBreak())
    story.extend(build_controls_page(doc))
    doc.build(story, onFirstPage=draw_first_page, onLaterPages=draw_later_pages)


def run_text_checks() -> None:
    reader = PdfReader(str(PDF_PATH))
    extracted = '\n'.join(page.extract_text() or '' for page in reader.pages)
    TEXT_PATH.write_text(extracted, encoding='utf-8')
    missing = [heading for heading in REQUIRED_TEXT if heading not in extracted]
    if missing:
        raise RuntimeError(f"Missing required section text: {', '.join(missing)}")
    with pdfplumber.open(str(PDF_PATH)) as pdf:
        if len(pdf.pages) != 4:
            raise RuntimeError(f'Expected exactly 4 pages in the generated PDF, found {len(pdf.pages)}.')


def render_pngs() -> None:
    if not POPLER_PATH.exists():
        raise FileNotFoundError(f'pdftoppm not found at {POPLER_PATH}')
    for png in TMP_DIR.glob('ibkr-canada-picks-and-shovels-plan-page-*.png'):
        png.unlink()
    subprocess.run([str(POPLER_PATH), '-png', str(PDF_PATH), str(PNG_PREFIX)], check=True, cwd=str(ROOT))
    renders = sorted(TMP_DIR.glob('ibkr-canada-picks-and-shovels-plan-page-*.png'))
    if len(renders) != 4:
        raise RuntimeError(f'Expected 4 rendered PNG pages, found {len(renders)}.')


def main() -> int:
    build_pdf()
    run_text_checks()
    render_pngs()
    print(f'Generated PDF: {PDF_PATH}')
    print(f'Extracted text: {TEXT_PATH}')
    print(f'Rendered pages: {TMP_DIR}')
    return 0


STYLES = build_styles()


if __name__ == '__main__':
    sys.exit(main())
