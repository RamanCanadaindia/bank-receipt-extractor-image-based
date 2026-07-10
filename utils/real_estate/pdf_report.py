import io
from datetime import datetime
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.lib.units import inch
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak, KeepTogether
)
from utils.real_estate.models import PropertyEvaluation

def generate_property_pdf(eval_res: PropertyEvaluation) -> bytes:
    """Generates a professional, polished investment analysis report PDF using ReportLab"""
    buffer = io.BytesIO()
    
    # 1. Page Template Setup
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        rightMargin=0.5 * inch,
        leftMargin=0.5 * inch,
        topMargin=0.5 * inch,
        bottomMargin=0.5 * inch
    )
    
    # 2. Typography Styles
    styles = getSampleStyleSheet()
    
    primary_color = colors.HexColor("#1A365D")   # Deep navy
    secondary_color = colors.HexColor("#2B6CB0") # Slate blue
    text_color = colors.HexColor("#2D3748")      # Charcoal
    accent_green = colors.HexColor("#2F855A")    # Emerald green
    
    title_style = ParagraphStyle(
        "DocTitle",
        parent=styles["Heading1"],
        fontName="Helvetica-Bold",
        fontSize=24,
        leading=28,
        textColor=primary_color,
        spaceAfter=6
    )
    
    subtitle_style = ParagraphStyle(
        "DocSub",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=11,
        leading=14,
        textColor=colors.HexColor("#718096"),
        spaceAfter=15
    )
    
    section_title = ParagraphStyle(
        "SectionTitle",
        parent=styles["Heading2"],
        fontName="Helvetica-Bold",
        fontSize=14,
        leading=18,
        textColor=primary_color,
        spaceBefore=12,
        spaceAfter=6,
        keepWithNext=True
    )
    
    body_bold = ParagraphStyle(
        "BodyBold",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=10,
        leading=13,
        textColor=text_color
    )
    
    body_style = ParagraphStyle(
        "BodyText",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=9,
        leading=12,
        textColor=text_color
    )
    
    rec_style = ParagraphStyle(
        "RecommendationText",
        parent=styles["Normal"],
        fontName="Helvetica-Oblique",
        fontSize=10,
        leading=14,
        textColor=colors.HexColor("#1A365D")
    )
    
    story = []
    
    # --- HEADER / COVER TITLE ---
    story.append(Paragraph("REAL ESTATE INVESTMENT REPORT", title_style))
    story.append(Paragraph(f"Generated on {datetime.now().strftime('%Y-%m-%d %I:%M %p')} | Confidential Investor Brochure", subtitle_style))
    
    # --- PROPERTY SPECIFICATIONS TABLE ---
    listing = eval_res.listing
    story.append(Paragraph("Property Specifications", section_title))
    
    specs_data = [
        [Paragraph("Address:", body_bold), Paragraph(listing.address, body_style), Paragraph("MLS® Number:", body_bold), Paragraph(listing.mls_number, body_style)],
        [Paragraph("Property Type:", body_bold), Paragraph(listing.property_type, body_style), Paragraph("Year Built:", body_bold), Paragraph(str(listing.year_built), body_style)],
        [Paragraph("Price:", body_bold), Paragraph(f"${listing.price:,.0f}", body_bold), Paragraph("Layout:", body_bold), Paragraph(f"{listing.beds} Bed, {listing.baths} Bath", body_style)],
        [Paragraph("Size (Sqft):", body_bold), Paragraph(f"{listing.sqft:,.0f} sqft", body_style), Paragraph("Original Price:", body_bold), Paragraph(f"${eval_res.comparables.average_comp_price:,.0f}", body_style)]
    ]
    
    specs_table = Table(specs_data, colWidths=[1.2*inch, 2.3*inch, 1.3*inch, 2.2*inch])
    specs_table.setStyle(TableStyle([
        ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor("#E2E8F0")),
        ('PADDING', (0,0), (-1,-1), 6),
        ('BACKGROUND', (0,0), (0,-1), colors.HexColor("#F7FAFC")),
        ('BACKGROUND', (2,0), (2,-1), colors.HexColor("#F7FAFC")),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
    ]))
    story.append(specs_table)
    story.append(Spacer(1, 10))
    
    # --- INVESTMENT RECOMMENDATION SUMMARY CARD ---
    story.append(Paragraph("Executive Recommendation & AI Summary", section_title))
    rec_box_data = [[Paragraph(eval_res.ai_recommendation, rec_style)]]
    rec_table = Table(rec_box_data, colWidths=[7.0*inch])
    rec_table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), colors.HexColor("#EBF8FF")), # Light blue tint
        ('BOX', (0,0), (-1,-1), 1.5, primary_color),
        ('PADDING', (0,0), (-1,-1), 10),
    ]))
    story.append(rec_table)
    story.append(Spacer(1, 15))
    
    # --- INVESTMENT PERFORMANCE & YIELDS ---
    story.append(Paragraph("Key Investment Yields", section_title))
    cf = eval_res.cash_flow
    roi = eval_res.roi
    
    yields_data = [
        [Paragraph("Overall Rank Score:", body_bold), Paragraph(f"<b>{eval_res.composite_score:.2f} / 10</b>", body_bold), Paragraph("Cap Rate:", body_bold), Paragraph(f"{cf.cap_rate}%", body_style)],
        [Paragraph("Monthly Net Cash Flow:", body_bold), Paragraph(f"${cf.net_cash_flow_monthly:,.2f}", body_bold), Paragraph("Cash-on-Cash Return:", body_bold), Paragraph(f"{cf.cash_on_cash_pct}%", body_style)],
        [Paragraph("Year 5 IRR:", body_bold), Paragraph(f"{roi.irr_5y:.1f}%", body_style), Paragraph("DSCR:", body_bold), Paragraph(f"{cf.dscr}", body_style)]
    ]
    yields_table = Table(yields_data, colWidths=[1.8*inch, 1.7*inch, 1.8*inch, 1.7*inch])
    yields_table.setStyle(TableStyle([
        ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor("#E2E8F0")),
        ('PADDING', (0,0), (-1,-1), 6),
        ('BACKGROUND', (0,0), (0,-1), colors.HexColor("#F7FAFC")),
        ('BACKGROUND', (2,0), (2,-1), colors.HexColor("#F7FAFC")),
    ]))
    story.append(yields_table)
    story.append(Spacer(1, 10))
    
    # --- PAGE BREAK FOR SECOND SECTION ---
    story.append(PageBreak())
    
    # --- DETAILED CASH FLOW STATEMENT ---
    story.append(Paragraph("Granular Monthly Cash Flow Statement", section_title))
    
    cf_statement = [
        [Paragraph("Revenue Item", body_bold), Paragraph("Monthly", body_bold), Paragraph("Expense Item", body_bold), Paragraph("Monthly", body_bold)],
        [Paragraph("Gross Rental Revenue", body_style), Paragraph(f"${cf.gross_rent:,.2f}", body_style), Paragraph("Mortgage Payment (P&I)", body_style), Paragraph(f"${cf.mortgage_payment:,.2f}", body_style)],
        ["", "", Paragraph("Strata Strata / Maintenance Fee", body_style), Paragraph(f"${cf.strata_fee_monthly:,.2f}", body_style)],
        ["", "", Paragraph("Property Taxes", body_style), Paragraph(f"${cf.property_tax_monthly:,.2f}", body_style)],
        ["", "", Paragraph("Property Insurance", body_style), Paragraph(f"${cf.insurance_monthly:,.2f}", body_style)],
        ["", "", Paragraph("Vacancy Allowance", body_style), Paragraph(f"${cf.vacancy_allowance_monthly:,.2f}", body_style)],
        ["", "", Paragraph("Maintenance Reserve", body_style), Paragraph(f"${cf.maintenance_reserve_monthly:,.2f}", body_style)],
        ["", "", Paragraph("Property Management", body_style), Paragraph(f"${cf.property_management_monthly:,.2f}", body_style)],
        ["", "", Paragraph("Utilities (Landlord Paid)", body_style), Paragraph(f"${cf.utilities_monthly:,.2f}", body_style)],
        ["", "", Paragraph("Misc / Admin Expenses", body_style), Paragraph(f"${cf.misc_monthly:,.2f}", body_style)],
        [Paragraph("Total Income", body_bold), Paragraph(f"${cf.gross_rent:,.2f}", body_bold), Paragraph("Total Operating Expenses", body_bold), Paragraph(f"${cf.gross_rent - cf.net_cash_flow_monthly:,.2f}", body_bold)],
        [Paragraph("Net Monthly Cash Flow", body_bold), Paragraph(f"${cf.net_cash_flow_monthly:,.2f}", body_bold), "", ""]
    ]
    
    cf_table = Table(cf_statement, colWidths=[2.0*inch, 1.5*inch, 2.0*inch, 1.5*inch])
    cf_table.setStyle(TableStyle([
        ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor("#CBD5E0")),
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor("#EDF2F7")),
        ('SPAN', (0,2), (1,9)), # Empty left fields
        ('PADDING', (0,0), (-1,-1), 4),
        ('BACKGROUND', (0,-2), (1,-1), colors.HexColor("#F7FAFC")),
        ('BACKGROUND', (2,-2), (3,-2), colors.HexColor("#F7FAFC")),
        ('TEXTCOLOR', (1,-1), (1,-1), accent_green if cf.net_cash_flow_monthly >= 0 else colors.red),
    ]))
    story.append(cf_table)
    story.append(Spacer(1, 10))
    
    # --- 10 YEAR ROI PROJECTIONS TABLE ---
    story.append(Paragraph("10-Year Wealth Creation Projections", section_title))
    
    roi_data = [
        [Paragraph("Metric", body_bold), Paragraph("Year 1", body_bold), Paragraph("Year 5", body_bold), Paragraph("Year 10", body_bold)],
        [Paragraph("Accumulated Net Cash Flow", body_style), Paragraph(f"${cf.net_cash_flow_annual:,.2f}", body_style), Paragraph(f"${cf.net_cash_flow_annual * 5:,.2f}", body_style), Paragraph(f"${cf.net_cash_flow_annual * 10:,.2f}", body_style)],
        [Paragraph("Estimated Property Value", body_style), Paragraph(f"${listing.price * (1 + eval_res.appreciation.expected_annual_appreciation_pct/100):,.0f}", body_style), Paragraph(f"${eval_res.appreciation.property_value_y5:,.0f}", body_style), Paragraph(f"${eval_res.appreciation.property_value_y10:,.0f}", body_style)],
        [Paragraph("Remaining Mortgage Balance", body_style), Paragraph(f"${eval_res.mortgage.remaining_balance_y5:,.0f} (est)", body_style), Paragraph(f"${eval_res.mortgage.remaining_balance_y5:,.0f}", body_style), Paragraph(f"${eval_res.mortgage.remaining_balance_y10:,.0f}", body_style)],
        [Paragraph("Total Wealth Created", body_bold), Paragraph(f"${roi.year_1_roi_pct}% Return", body_style), Paragraph(f"${roi.total_wealth_created_5y:,.2f}", body_bold), Paragraph(f"${roi.total_wealth_created_10y:,.2f}", body_bold)]
    ]
    roi_table = Table(roi_data, colWidths=[2.5*inch, 1.5*inch, 1.5*inch, 1.5*inch])
    roi_table.setStyle(TableStyle([
        ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor("#CBD5E0")),
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor("#EDF2F7")),
        ('PADDING', (0,0), (-1,-1), 5),
    ]))
    story.append(roi_table)
    story.append(Spacer(1, 10))
    
    # --- RISK MATRIX SUMMARY ---
    story.append(Paragraph("Risk & Location Diagnostics", section_title))
    r = eval_res.risk
    
    risk_data_list = [
        [Paragraph("Flood Hazard Risk:", body_bold), Paragraph(r.flood_risk, body_style), Paragraph("Safety / Crime Profile:", body_bold), Paragraph(r.crime_rate, body_style)],
        [Paragraph("Interest Rate sensitivity:", body_bold), Paragraph(r.interest_rate_sensitivity, body_style), Paragraph("Market Volatility:", body_bold), Paragraph(r.market_volatility, body_style)],
        [Paragraph("Overall Risk Profile Rating:", body_bold), Paragraph(f"<b>{r.risk_level}</b> ({r.risk_score}/10)", body_bold), Paragraph("School Catchment Rating:", body_bold), Paragraph(f"{eval_res.schools.average_school_rating}/10", body_style)]
    ]
    risk_table = Table(risk_data_list, colWidths=[2.0*inch, 1.5*inch, 2.0*inch, 1.5*inch])
    risk_table.setStyle(TableStyle([
        ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor("#E2E8F0")),
        ('PADDING', (0,0), (-1,-1), 5),
        ('BACKGROUND', (0,0), (0,-1), colors.HexColor("#F7FAFC")),
        ('BACKGROUND', (2,0), (2,-1), colors.HexColor("#F7FAFC")),
    ]))
    story.append(risk_table)
    
    # 4. Build Document Flowable
    doc.build(story)
    
    return buffer.getvalue()
