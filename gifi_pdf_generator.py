import io
from datetime import datetime
import report_config
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors

def safe_float(val):
    if val is None:
        return 0.0
    if isinstance(val, (int, float)):
        return float(val)
    try:
        clean_val = str(val).strip()
        if clean_val.startswith("(") and clean_val.endswith(")"):
            clean_val = "-" + clean_val[1:-1]
        clean_val = clean_val.replace("$", "").replace(",", "").strip()
        if not clean_val or clean_val.lower() in ('none', 'null', '-', '—'):
            return 0.0
        return float(clean_val)
    except ValueError:
        return 0.0

def add_page_decorations(canvas, doc):
    """
    Draws headers and page numbers on non-cover pages.
    """
    canvas.saveState()
    canvas.setFont('Times-Roman', 9)
    # Page 1 is the Cover Page (no page number)
    if doc.page > 1:
        page_num_str = str(doc.page - 1)
        canvas.drawCentredString(letter[0] / 2.0, 36, page_num_str)
        # Small disclaimer at bottom
        canvas.drawCentredString(letter[0] / 2.0, 50, "Unaudited - See Accompanying Notes")
    canvas.restoreState()

def generate_financial_pdf(meta, classified, compiler_name, compilation_date, report_type, basis_of_accounting):
    """
    Generates a formal, printable PDF document using ReportLab.
    """
    buffer = io.BytesIO()
    
    # Page margins: 1 inch (72 points)
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        leftMargin=72,
        rightMargin=72,
        topMargin=72,
        bottomMargin=72
    )
    
    styles = getSampleStyleSheet()
    
    # Financial Statement Fonts (Times-Roman standard)
    style_cover_title = ParagraphStyle(
        'CoverTitle',
        parent=styles['Normal'],
        fontName='Times-Bold',
        fontSize=26,
        leading=32,
        alignment=1, # Center
        spaceAfter=15
    )
    
    style_cover_sub = ParagraphStyle(
        'CoverSub',
        parent=styles['Normal'],
        fontName='Times-Roman',
        fontSize=14,
        leading=18,
        alignment=1, # Center
        spaceAfter=10
    )
    
    style_cover_company = ParagraphStyle(
        'CoverCompany',
        parent=styles['Normal'],
        fontName='Times-Bold',
        fontSize=20,
        leading=24,
        alignment=1, # Center
        spaceAfter=15
    )
    
    style_header_name = ParagraphStyle(
        'HeaderName',
        parent=styles['Normal'],
        fontName='Times-Bold',
        fontSize=14,
        leading=18,
        alignment=1, # Center
        spaceAfter=4
    )
    
    style_header_sub = ParagraphStyle(
        'HeaderSub',
        parent=styles['Normal'],
        fontName='Times-Italic',
        fontSize=11,
        leading=14,
        alignment=1, # Center
        spaceAfter=15
    )
    
    style_body = ParagraphStyle(
        'ReportBody',
        parent=styles['Normal'],
        fontName='Times-Roman',
        fontSize=11,
        leading=16,
        spaceAfter=12
    )
    
    style_table_text = ParagraphStyle(
        'TableText',
        parent=styles['Normal'],
        fontName='Times-Roman',
        fontSize=10,
        leading=12
    )
    
    style_table_text_bold = ParagraphStyle(
        'TableTextBold',
        parent=styles['Normal'],
        fontName='Times-Bold',
        fontSize=10,
        leading=12
    )
    
    style_table_text_indent = ParagraphStyle(
        'TableTextIndent',
        parent=styles['Normal'],
        fontName='Times-Roman',
        fontSize=10,
        leading=12,
        leftIndent=15
    )
    
    style_table_num = ParagraphStyle(
        'TableNum',
        parent=styles['Normal'],
        fontName='Times-Roman',
        fontSize=10,
        leading=12,
        alignment=2 # Right
    )
    
    style_table_num_bold = ParagraphStyle(
        'TableNumBold',
        parent=styles['Normal'],
        fontName='Times-Bold',
        fontSize=10,
        leading=12,
        alignment=2 # Right
    )
    
    story = []
    
    # ------------------ PAGE 1: COVER PAGE ------------------
    def format_business_number(bn):
        if not bn:
            return ""
        clean = str(bn).replace(" ", "").strip()
        if "RC" in clean:
            parts = clean.split("RC")
            return f"{parts[0]} RC{parts[1]}"
        else:
            digits = "".join(filter(str.isdigit, clean))
            if digits:
                return f"{digits} RC0001"
            return clean

    story.append(Spacer(1, 100))
    story.append(Paragraph("FINANCIAL STATEMENTS", style_cover_title))
    story.append(Spacer(1, 30))
    story.append(Paragraph(meta.get("corporation_name", "Corporation").upper(), style_cover_company))
    story.append(Spacer(1, 100))
    
    # Format year end
    tax_year_end_formatted = meta.get("tax_year_end", "")
    try:
        dt_ye = datetime.strptime(tax_year_end_formatted.replace("/", "-"), "%Y-%m-%d")
        tax_year_end_display = dt_ye.strftime("%B %d, %Y")
    except Exception:
        tax_year_end_display = tax_year_end_formatted
        
    story.append(Paragraph(f"For the year ended<br/><strong>{tax_year_end_display}</strong>", style_cover_sub))
    story.append(Spacer(1, 20))
    story.append(Paragraph("(Unaudited)", style_cover_sub))
    story.append(PageBreak())
    
    # ------------------ PAGE 2: NOTICE TO READER ------------------
    report_title_header = "NOTICE TO READER"
    
    story.append(Spacer(1, 20))
    story.append(Paragraph(report_title_header, ParagraphStyle('RepTitle', parent=styles['Normal'], fontName='Times-Bold', fontSize=14, leading=18, alignment=1, spaceAfter=30)))
    
    for block in report_config.NOTICE_TO_READER_TEXT.split("\n\n"):
        story.append(Paragraph(block, style_body))
        story.append(Spacer(1, 10))
        
    story.append(Spacer(1, 30))
    if compiler_name:
        story.append(Paragraph(f"<strong>{compiler_name}</strong>", style_body))
    story.append(Paragraph(compilation_date, style_body))
    story.append(PageBreak())
    
    # ------------------ PAGE 3: BALANCE SHEET ------------------
    story.append(Paragraph(meta.get("corporation_name", "Corporation").upper(), style_header_name))
    story.append(Paragraph(f"Balance Sheet as at {tax_year_end_display}<br/>(Unaudited)", style_header_sub))
    
    # Calculate financial totals
    cur_assets_sum_cur = sum(x["current_year"] for x in classified["current_assets"])
    cur_assets_sum_pri = sum(x["prior_year"] for x in classified["current_assets"])
    
    tang_assets_net_cur = 0.0
    tang_assets_net_pri = 0.0
    for x in classified["tangible_assets"]:
        if "amort" in x["description"].lower() or "accumulated" in x["description"].lower() or x["gifi_code"] in (1743, 2009):
            tang_assets_net_cur -= abs(x["current_year"])
            tang_assets_net_pri -= abs(x["prior_year"])
        else:
            tang_assets_net_cur += x["current_year"]
            tang_assets_net_pri += x["prior_year"]
            
    long_assets_sum_cur = sum(x["current_year"] for x in classified["long_term_assets"])
    long_assets_sum_pri = sum(x["prior_year"] for x in classified["long_term_assets"])
    
    total_assets_calc_cur = cur_assets_sum_cur + tang_assets_net_cur + long_assets_sum_cur
    total_assets_calc_pri = cur_assets_sum_pri + tang_assets_net_pri + long_assets_sum_pri
    
    cur_liab_sum_cur = sum(x["current_year"] for x in classified["current_liabilities"])
    cur_liab_sum_pri = sum(x["prior_year"] for x in classified["current_liabilities"])
    
    long_liab_sum_cur = sum(x["current_year"] for x in classified["long_term_liabilities"])
    long_liab_sum_pri = sum(x["prior_year"] for x in classified["long_term_liabilities"])
    
    total_liab_calc_cur = cur_liab_sum_cur + long_liab_sum_cur
    total_liab_calc_pri = cur_liab_sum_pri + long_liab_sum_pri
    
    shares_sum_cur = sum(x["current_year"] for x in classified["equity_shares"])
    shares_sum_pri = sum(x["prior_year"] for x in classified["equity_shares"])
    
    re_curr = sum(x["current_year"] for x in classified["retained_earnings"] if x["gifi_code"] == 3600)
    re_prior = sum(x["prior_year"] for x in classified["retained_earnings"] if x["gifi_code"] == 3600)
    if re_curr == 0.0 and len(classified["retained_earnings"]) > 0:
        re_curr = classified["retained_earnings"][0]["current_year"]
        re_prior = classified["retained_earnings"][0]["prior_year"]
        
    total_equity_calc_cur = shares_sum_cur + re_curr
    total_equity_calc_pri = shares_sum_pri + re_prior
    
    total_liab_equity_cur = total_liab_calc_cur + total_equity_calc_cur
    total_liab_equity_pri = total_liab_calc_pri + total_equity_calc_pri
       # Table details
    bs_data = [
        [Paragraph("<strong>Account Description</strong>", style_table_text_bold), 
         Paragraph("<strong>Current Year</strong>", ParagraphStyle('R_Bold', parent=style_table_num_bold)), 
         "",
         Paragraph("<strong>Prior Year</strong>", ParagraphStyle('R_Bold', parent=style_table_num_bold))]
    ]
    
    t_styles = [
        ('LINEBELOW', (0,0), (1,0), 1.5, colors.black),
        ('LINEBELOW', (3,0), (3,0), 1.5, colors.black),
        ('VALIGN', (0,0), (-1,-1), 'BOTTOM'),
        ('BOTTOMPADDING', (0,0), (-1,-1), 4),
        ('TOPPADDING', (0,0), (-1,-1), 4),
    ]
    
    # Helper to format accounting numbers
    def fmt_acc(val):
        if val < 0:
            return f"({abs(val):,.2f})"
        elif val == 0:
            return "—"
        return f"{val:,.2f}"
        
    # ASSETS
    bs_data.append([Paragraph("<strong>ASSETS</strong>", style_table_text_bold), "", "", ""])
    
    # Current Assets
    if classified["current_assets"]:
        bs_data.append([Paragraph("<strong>Current Assets</strong>", style_table_text_bold), "", "", ""])
        for x in classified["current_assets"]:
            bs_data.append([
                Paragraph(x["description"], style_table_text_indent),
                Paragraph(fmt_acc(x["current_year"]), style_table_num),
                "",
                Paragraph(fmt_acc(x["prior_year"]), style_table_num)
            ])
        # Total Current
        line_row = len(bs_data)
        bs_data.append([
            Paragraph("Total Current Assets", style_table_text_bold),
            Paragraph(fmt_acc(cur_assets_sum_cur), style_table_num_bold),
            "",
            Paragraph(fmt_acc(cur_assets_sum_pri), style_table_num_bold)
        ])
        t_styles.append(('LINEABOVE', (1, line_row), (1, line_row), 1, colors.black))
        t_styles.append(('LINEABOVE', (3, line_row), (3, line_row), 1, colors.black))
        
    # Tangible Capital Assets
    if classified["tangible_assets"]:
        bs_data.append([Paragraph("<strong>Tangible Capital Assets</strong>", style_table_text_bold), "", "", ""])
        for x in classified["tangible_assets"]:
            desc = x["description"]
            is_amort = "amort" in desc.lower() or "accumulated" in desc.lower() or x["gifi_code"] in (1743, 2009)
            display_desc = f"Less: {desc}" if is_amort else desc
            val_cur = -abs(x["current_year"]) if is_amort else x["current_year"]
            val_pri = -abs(x["prior_year"]) if is_amort else x["prior_year"]
            
            bs_data.append([
                Paragraph(display_desc, style_table_text_indent),
                Paragraph(fmt_acc(val_cur), style_table_num),
                "",
                Paragraph(fmt_acc(val_pri), style_table_num)
            ])
        # Net Tangible
        line_row = len(bs_data)
        bs_data.append([
            Paragraph("Net Tangible Capital Assets", style_table_text_bold),
            Paragraph(fmt_acc(tang_assets_net_cur), style_table_num_bold),
            "",
            Paragraph(fmt_acc(tang_assets_net_pri), style_table_num_bold)
        ])
        t_styles.append(('LINEABOVE', (1, line_row), (1, line_row), 1, colors.black))
        t_styles.append(('LINEABOVE', (3, line_row), (3, line_row), 1, colors.black))
        
    # Long Term Assets
    if classified["long_term_assets"]:
        bs_data.append([Paragraph("<strong>Long Term Assets</strong>", style_table_text_bold), "", "", ""])
        for x in classified["long_term_assets"]:
            bs_data.append([
                Paragraph(x["description"], style_table_text_indent),
                Paragraph(fmt_acc(x["current_year"]), style_table_num),
                "",
                Paragraph(fmt_acc(x["prior_year"]), style_table_num)
            ])
        line_row = len(bs_data)
        bs_data.append([
            Paragraph("Total Long Term Assets", style_table_text_bold),
            Paragraph(fmt_acc(long_assets_sum_cur), style_table_num_bold),
            "",
            Paragraph(fmt_acc(long_assets_sum_pri), style_table_num_bold)
        ])
        t_styles.append(('LINEABOVE', (1, line_row), (1, line_row), 1, colors.black))
        t_styles.append(('LINEABOVE', (3, line_row), (3, line_row), 1, colors.black))
        
    # TOTAL ASSETS
    line_row = len(bs_data)
    bs_data.append([
        Paragraph("<strong>TOTAL ASSETS</strong>", style_table_text_bold),
        Paragraph(fmt_acc(total_assets_calc_cur), style_table_num_bold),
        "",
        Paragraph(fmt_acc(total_assets_calc_pri), style_table_num_bold)
    ])
    t_styles.append(('LINEABOVE', (1, line_row), (1, line_row), 1, colors.black))
    t_styles.append(('LINEABOVE', (3, line_row), (3, line_row), 1, colors.black))
    t_styles.append(('LINEBELOW', (1, line_row), (1, line_row), 2, colors.black))
    t_styles.append(('LINEBELOW', (3, line_row), (3, line_row), 2, colors.black))
    
    # LIABILITIES
    bs_data.append([Paragraph("<strong>LIABILITIES</strong>", style_table_text_bold), "", "", ""])
    
    # Current Liabilities
    if classified["current_liabilities"]:
        bs_data.append([Paragraph("<strong>Current Liabilities</strong>", style_table_text_bold), "", "", ""])
        for x in classified["current_liabilities"]:
            bs_data.append([
                Paragraph(x["description"], style_table_text_indent),
                Paragraph(fmt_acc(x["current_year"]), style_table_num),
                "",
                Paragraph(fmt_acc(x["prior_year"]), style_table_num)
            ])
        line_row = len(bs_data)
        bs_data.append([
            Paragraph("Total Current Liabilities", style_table_text_bold),
            Paragraph(fmt_acc(cur_liab_sum_cur), style_table_num_bold),
            "",
            Paragraph(fmt_acc(cur_liab_sum_pri), style_table_num_bold)
        ])
        t_styles.append(('LINEABOVE', (1, line_row), (1, line_row), 1, colors.black))
        t_styles.append(('LINEABOVE', (3, line_row), (3, line_row), 1, colors.black))
        
    # Long Term Liabilities
    if classified["long_term_liabilities"]:
        bs_data.append([Paragraph("<strong>Long Term Liabilities</strong>", style_table_text_bold), "", "", ""])
        for x in classified["long_term_liabilities"]:
            bs_data.append([
                Paragraph(x["description"], style_table_text_indent),
                Paragraph(fmt_acc(x["current_year"]), style_table_num),
                "",
                Paragraph(fmt_acc(x["prior_year"]), style_table_num)
            ])
        line_row = len(bs_data)
        bs_data.append([
            Paragraph("Total Long Term Liabilities", style_table_text_bold),
            Paragraph(fmt_acc(long_liab_sum_cur), style_table_num_bold),
            "",
            Paragraph(fmt_acc(long_liab_sum_pri), style_table_num_bold)
        ])
        t_styles.append(('LINEABOVE', (1, line_row), (1, line_row), 1, colors.black))
        t_styles.append(('LINEABOVE', (3, line_row), (3, line_row), 1, colors.black))
        
    # SHAREHOLDER EQUITY
    bs_data.append([Paragraph("<strong>SHAREHOLDER EQUITY</strong>", style_table_text_bold), "", "", ""])
    for x in classified["equity_shares"]:
        bs_data.append([
            Paragraph(x["description"], style_table_text_indent),
            Paragraph(fmt_acc(x["current_year"]), style_table_num),
            "",
            Paragraph(fmt_acc(x["prior_year"]), style_table_num)
        ])
    bs_data.append([
        Paragraph("Retained Earnings (Deficit)", style_table_text_indent),
        Paragraph(fmt_acc(re_curr), style_table_num),
        "",
        Paragraph(fmt_acc(re_prior), style_table_num)
    ])
    # Total Equity
    line_row = len(bs_data)
    bs_data.append([
        Paragraph("Total Shareholder Equity", style_table_text_bold),
        Paragraph(fmt_acc(total_equity_calc_cur), style_table_num_bold),
        "",
        Paragraph(fmt_acc(total_equity_calc_pri), style_table_num_bold)
    ])
    t_styles.append(('LINEABOVE', (1, line_row), (1, line_row), 1, colors.black))
    t_styles.append(('LINEABOVE', (3, line_row), (3, line_row), 1, colors.black))
    
    # TOTAL LIABILITIES & EQUITY
    line_row = len(bs_data)
    bs_data.append([
        Paragraph("<strong>TOTAL LIABILITIES & EQUITY</strong>", style_table_text_bold),
        Paragraph(fmt_acc(total_liab_equity_cur), style_table_num_bold),
        "",
        Paragraph(fmt_acc(total_liab_equity_pri), style_table_num_bold)
    ])
    t_styles.append(('LINEABOVE', (1, line_row), (1, line_row), 1, colors.black))
    t_styles.append(('LINEABOVE', (3, line_row), (3, line_row), 1, colors.black))
    t_styles.append(('LINEBELOW', (1, line_row), (1, line_row), 2, colors.black))
    t_styles.append(('LINEBELOW', (3, line_row), (3, line_row), 2, colors.black))
    
    bs_table = Table(bs_data, colWidths=[240, 90, 20, 90])
    bs_table.setStyle(TableStyle(t_styles))
    
    story.append(bs_table)
    story.append(Spacer(1, 30))
    story.append(PageBreak())
    
    # ------------------ PAGE 4: INCOME STATEMENT ------------------
    story.append(Paragraph(meta.get("corporation_name", "Corporation").upper(), style_header_name))
    story.append(Paragraph(f"Income Statement<br/>For the year ended {tax_year_end_display}<br/>(Unaudited)", style_header_sub))
    
    total_rev_cur = sum(x["current_year"] for x in classified["revenues"])
    total_rev_pri = sum(x["prior_year"] for x in classified["revenues"])
    
    total_cogs_cur = sum(x["current_year"] for x in classified["cost_of_sales"])
    total_cogs_pri = sum(x["prior_year"] for x in classified["cost_of_sales"])
    
    gross_profit_cur = total_rev_cur - total_cogs_cur
    gross_profit_pri = total_rev_pri - total_cogs_pri
    
    total_exp_cur = sum(x["current_year"] for x in classified["expenses"])
    total_exp_pri = sum(x["prior_year"] for x in classified["expenses"])
    
    net_income_before_tax_cur = gross_profit_cur - total_exp_cur
    net_income_before_tax_pri = gross_profit_pri - total_exp_pri
    
    tax_cur = 0.0
    tax_pri = 0.0
    if classified.get("current_income_taxes"):
        tax_cur = classified["current_income_taxes"]["current_year"]
        tax_pri = classified["current_income_taxes"]["prior_year"]
        
    net_income_after_tax_cur = net_income_before_tax_cur - tax_cur
    net_income_after_tax_pri = net_income_before_tax_pri - tax_pri
    
    is_data = [
        [Paragraph("<strong>Account Description</strong>", style_table_text_bold), 
         Paragraph("<strong>Current Year</strong>", ParagraphStyle('R_Bold', parent=style_table_num_bold)), 
         "",
         Paragraph("<strong>Prior Year</strong>", ParagraphStyle('R_Bold', parent=style_table_num_bold))]
    ]
    
    is_styles = [
        ('LINEBELOW', (0,0), (1,0), 1.5, colors.black),
        ('LINEBELOW', (3,0), (3,0), 1.5, colors.black),
        ('VALIGN', (0,0), (-1,-1), 'BOTTOM'),
        ('BOTTOMPADDING', (0,0), (-1,-1), 4),
        ('TOPPADDING', (0,0), (-1,-1), 4),
    ]
    
    # REVENUE
    is_data.append([Paragraph("<strong>REVENUE</strong>", style_table_text_bold), "", "", ""])
    for x in classified["revenues"]:
        is_data.append([
            Paragraph(x["description"], style_table_text_indent),
            Paragraph(fmt_acc(x["current_year"]), style_table_num),
            "",
            Paragraph(fmt_acc(x["prior_year"]), style_table_num)
        ])
    line_row = len(is_data)
    is_data.append([
        Paragraph("Total Revenue", style_table_text_bold),
        Paragraph(fmt_acc(total_rev_cur), style_table_num_bold),
        "",
        Paragraph(fmt_acc(total_rev_pri), style_table_num_bold)
    ])
    is_styles.append(('LINEABOVE', (1, line_row), (1, line_row), 1, colors.black))
    is_styles.append(('LINEABOVE', (3, line_row), (3, line_row), 1, colors.black))
    
    # COST OF SALES
    if classified["cost_of_sales"]:
        is_data.append([Paragraph("<strong>COST OF SALES</strong>", style_table_text_bold), "", "", ""])
        for x in classified["cost_of_sales"]:
            is_data.append([
                Paragraph(x["description"], style_table_text_indent),
                Paragraph(fmt_acc(x["current_year"]), style_table_num),
                "",
                Paragraph(fmt_acc(x["prior_year"]), style_table_num)
            ])
        line_row = len(is_data)
        is_data.append([
            Paragraph("Total Cost of Sales", style_table_text_bold),
            Paragraph(fmt_acc(total_cogs_cur), style_table_num_bold),
            "",
            Paragraph(fmt_acc(total_cogs_pri), style_table_num_bold)
        ])
        is_styles.append(('LINEABOVE', (1, line_row), (1, line_row), 1, colors.black))
        is_styles.append(('LINEABOVE', (3, line_row), (3, line_row), 1, colors.black))
        
        line_row = len(is_data)
        is_data.append([
            Paragraph("Gross Profit", style_table_text_bold),
            Paragraph(fmt_acc(gross_profit_cur), style_table_num_bold),
            "",
            Paragraph(fmt_acc(gross_profit_pri), style_table_num_bold)
        ])
        is_styles.append(('LINEABOVE', (1, line_row), (1, line_row), 1, colors.black))
        is_styles.append(('LINEABOVE', (3, line_row), (3, line_row), 1, colors.black))
        
    # EXPENSES
    is_data.append([Paragraph("<strong>OPERATING EXPENSES</strong>", style_table_text_bold), "", "", ""])
    for x in classified["expenses"]:
        is_data.append([
            Paragraph(x["description"], style_table_text_indent),
            Paragraph(fmt_acc(x["current_year"]), style_table_num),
            "",
            Paragraph(fmt_acc(x["prior_year"]), style_table_num)
        ])
    line_row = len(is_data)
    is_data.append([
        Paragraph("Total Operating Expenses", style_table_text_bold),
        Paragraph(fmt_acc(total_exp_cur), style_table_num_bold),
        "",
        Paragraph(fmt_acc(total_exp_pri), style_table_num_bold)
    ])
    is_styles.append(('LINEABOVE', (1, line_row), (1, line_row), 1, colors.black))
    is_styles.append(('LINEABOVE', (3, line_row), (3, line_row), 1, colors.black))
    
    # NET INCOME BEFORE TAX
    line_row = len(is_data)
    is_data.append([
        Paragraph("<strong>NET INCOME BEFORE INCOME TAXES</strong>", style_table_text_bold),
        Paragraph(fmt_acc(net_income_before_tax_cur), style_table_num_bold),
        "",
        Paragraph(fmt_acc(net_income_before_tax_pri), style_table_num_bold)
    ])
    is_styles.append(('LINEABOVE', (1, line_row), (1, line_row), 1, colors.black))
    is_styles.append(('LINEABOVE', (3, line_row), (3, line_row), 1, colors.black))
    
    # INCOME TAX
    is_data.append([
        Paragraph("Current Income Taxes", style_table_text_indent),
        Paragraph(fmt_acc(tax_cur), style_table_num),
        "",
        Paragraph(fmt_acc(tax_pri), style_table_num)
    ])
    
    # NET INCOME AFTER TAX
    line_row = len(is_data)
    is_data.append([
        Paragraph("<strong>NET INCOME (LOSS) FOR THE YEAR</strong>", style_table_text_bold),
        Paragraph(fmt_acc(net_income_after_tax_cur), style_table_num_bold),
        "",
        Paragraph(fmt_acc(net_income_after_tax_pri), style_table_num_bold)
    ])
    is_styles.append(('LINEABOVE', (1, line_row), (1, line_row), 1, colors.black))
    is_styles.append(('LINEABOVE', (3, line_row), (3, line_row), 1, colors.black))
    is_styles.append(('LINEBELOW', (1, line_row), (1, line_row), 2, colors.black))
    is_styles.append(('LINEBELOW', (3, line_row), (3, line_row), 2, colors.black))
    
    is_table = Table(is_data, colWidths=[240, 90, 20, 90])
    is_table.setStyle(TableStyle(is_styles))
    
    story.append(is_table)
    story.append(PageBreak())
    
    # ------------------ PAGE 5: NOTES ------------------
    story.append(Paragraph(meta.get("corporation_name", "Corporation").upper(), style_header_name))
    story.append(Paragraph(f"Notes to Financial Statements<br/>For the year ended {tax_year_end_display}<br/>(Unaudited)", style_header_sub))
    
    story.append(Spacer(1, 20))
    story.append(Paragraph("<strong>NOTE 1: BASIS OF ACCOUNTING</strong>", ParagraphStyle('NoteHead', parent=styles['Normal'], fontName='Times-Bold', fontSize=11, spaceAfter=8)))
    
    note_text = report_config.NOTE_1_TEXT
    story.append(Paragraph(note_text, style_body))
    
    # Build Document
    doc.build(story, onFirstPage=lambda c, d: None, onLaterPages=add_page_decorations)
    
    pdf_val = buffer.getvalue()
    buffer.close()
    return pdf_val
